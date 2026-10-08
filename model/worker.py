"""Runs on the model instance (EC2, Graviton): the self-hosted model, for when Bedrock has no quota.

llama.cpp's server listens on 127.0.0.1 only. Requests arrive on an SQS queue and answers go to DynamoDB
(MODELRESP#<id>), so the instance has no inbound ports at all and every caller is checked by IAM.
The weights (open, Apache-2.0) are fetched once from Hugging Face, checked against a pinned SHA-256 and kept in S3.
A heartbeat item says the model is up; after IDLE_STOP_MIN minutes without a request the instance stops itself.
"""
import base64
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zlib

import boto3
from botocore.exceptions import ClientError

# file -> (Hugging Face repo, sha256, bytes). The SSM parameter /teesri/model/file picks one.
MODELS = {
    "Qwen3.5-4B-Q4_0.gguf": ("unsloth/Qwen3.5-4B-GGUF", "298fcb5fe7a77ccc79745ae24751560c5ac56874caff4bb39b1f2055bd72b8bb", 2583221408),
    "Qwen3.5-4B-Q4_K_M.gguf": ("unsloth/Qwen3.5-4B-GGUF", "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", 2740937888),
    "Qwen3.5-2B-Q4_K_M.gguf": ("unsloth/Qwen3.5-2B-GGUF", "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223", 1280835840),
    "gemma-4-E2B_q4_0-it.gguf": ("google/gemma-4-E2B-it-qat-q4_0-gguf", "fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634", 3349516256),
    "gemma-4-E4B_q4_0-it.gguf": ("google/gemma-4-E4B-it-qat-q4_0-gguf", "676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee", 5154941280),
}
REGION, BUCKET, QUEUE, TABLE = (os.environ[k] for k in ("AWS_REGION", "BUCKET", "QUEUE_URL", "TABLE"))
DIR, PORT = "/opt/teesri/models", 8080
IDLE_STOP_MIN = int(os.environ.get("IDLE_STOP_MIN", "60"))
s3, sqs, ssm = (boto3.client(n, region_name=REGION) for n in ("s3", "sqs", "ssm"))
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
last_request = time.time()


def weights(name: str) -> str:
    repo, sha, size = MODELS[name]
    path = f"{DIR}/{name}"
    if os.path.exists(path) and os.path.getsize(path) == size:
        return path
    os.makedirs(DIR, exist_ok=True)
    try:
        s3.download_file(BUCKET, f"models/{name}", path)
        return path
    except ClientError:
        pass
    print(f"fetching {name} from Hugging Face ({repo})", flush=True)  # first use only
    h = hashlib.sha256()
    with urllib.request.urlopen(f"https://huggingface.co/{repo}/resolve/main/{name}", timeout=60) as r, open(path, "wb") as f:
        while chunk := r.read(1 << 24):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != sha:
        os.remove(path)
        raise RuntimeError(f"{name}: checksum mismatch, not used")
    s3.upload_file(path, BUCKET, f"models/{name}")
    return path


def start_server(name: str) -> subprocess.Popen:
    args = ["/opt/llama/llama-server", "-m", weights(name), "--host", "127.0.0.1", "--port", str(PORT),
            "-c", "16384", "-np", "1", "-t", str(os.cpu_count()), "--no-webui", "--reasoning", "off"]
    proc = subprocess.Popen(args, env={**os.environ, "LD_LIBRARY_PATH": "/opt/llama"})
    while proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(1)
    raise RuntimeError("llama-server exited during start")


def heartbeat(name: str, proc: subprocess.Popen) -> None:
    while proc.poll() is None:
        now = int(time.time())
        table.put_item(Item={"PK": "MODEL#heartbeat", "SK": "META", "ts": now, "model": name, "ttl": now + 3600})
        if now - last_request > IDLE_STOP_MIN * 60:
            print("idle: stopping the instance", flush=True)
            subprocess.run(["shutdown", "-h", "now"])
        time.sleep(15)


def answer(req: dict) -> dict:
    body = req.get("body")
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{req.get('path', '/v1/chat/completions')}",
                               data=None if body is None else json.dumps(body).encode(),
                               method=req.get("method", "POST"), headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            status, ctype, text = resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as e:
        status, ctype, text = e.code, e.headers.get("Content-Type", ""), e.read()
    return {"status": status, "type": ctype, "body_z": base64.b64encode(zlib.compress(text)).decode(),
            "ms": int((time.time() - t0) * 1000)}


def main() -> None:
    global last_request
    name = ssm.get_parameter(Name="/teesri/model/file")["Parameter"]["Value"]
    proc = start_server(name)
    print(f"model ready: {name}", flush=True)
    threading.Thread(target=heartbeat, args=(name, proc), daemon=True).start()
    while proc.poll() is None:
        msgs = sqs.receive_message(QueueUrl=QUEUE, WaitTimeSeconds=20, MaxNumberOfMessages=1).get("Messages", [])
        for m in msgs:
            req = json.loads(m["Body"])
            sqs.delete_message(QueueUrl=QUEUE, ReceiptHandle=m["ReceiptHandle"])  # at most once: callers time out
            if req.get("deadline", 0) < time.time():
                continue
            last_request = time.time()
            out = answer(req)
            table.put_item(Item={"PK": f"MODELRESP#{req['id']}", "SK": "META", "ttl": int(time.time()) + 3600, **out})
    raise SystemExit("llama-server stopped")  # systemd restarts the worker


if __name__ == "__main__":
    main()
