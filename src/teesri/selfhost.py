"""The self-hosted model (model/worker.py on the model instance), reached through SQS and the table: no open ports.

call() sends one request for the llama.cpp server and waits for its answer. Transport lets Strands' LlamaCppModel
use it as if the server were local. If the instance is off (no fresh heartbeat), callers fall back at once, and
a goal never runs past its deadline (the case Lambda must still have time to use the template).
"""
import asyncio
import base64
import json
import os
import time
import uuid
import zlib

import boto3
import httpx

from teesri import store

HEARTBEAT_S = 60       # the worker writes one every 15 s
CALL_TIMEOUT_S = 90    # one model request
_sqs = None
_deadline = None       # set per agent goal by start_budget()


def enabled() -> bool:
    return os.environ.get("MODEL_BACKEND") == "selfhost" and bool(os.environ.get("MODEL_QUEUE_URL"))


def available() -> bool:
    if not enabled():
        return False
    hb = store.table().get_item(Key={"PK": "MODEL#heartbeat", "SK": "META"}).get("Item")
    return bool(hb) and time.time() - int(hb["ts"]) < HEARTBEAT_S


def start_budget(seconds: float) -> None:
    global _deadline
    _deadline = time.time() + seconds


def call(path: str, body: dict | None, timeout: float = CALL_TIMEOUT_S) -> tuple[int, str, str]:
    """(status, content type, body) of one llama.cpp server request."""
    global _sqs
    if _deadline is not None:
        timeout = min(timeout, _deadline - time.time())
    if timeout <= 0:
        raise TimeoutError("model budget for this goal is spent")
    _sqs = _sqs or boto3.client("sqs")
    rid, end = uuid.uuid4().hex, time.time() + timeout
    _sqs.send_message(QueueUrl=os.environ["MODEL_QUEUE_URL"],
                      MessageBody=json.dumps({"id": rid, "path": path, "body": body, "deadline": end}))
    key = {"PK": f"MODELRESP#{rid}", "SK": "META"}
    while time.time() < end:
        item = store.table().get_item(Key=key, ConsistentRead=True).get("Item")
        if item:
            store.table().delete_item(Key=key)
            return int(item["status"]), item.get("type", ""), zlib.decompress(base64.b64decode(item["body_z"])).decode()
        time.sleep(0.25)
    raise TimeoutError(f"model did not answer within {timeout:.0f} s")


def chat_json(system: str, user: str, schema: dict, max_tokens: int = 300) -> dict | None:
    """One answer constrained to `schema` (llama.cpp turns the schema into a grammar)."""
    status, _, text = call("/v1/chat/completions", {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "record", "schema": schema}},
    })
    if status != 200:
        return None
    return json.loads(json.loads(text)["choices"][0]["message"]["content"])


class Transport(httpx.AsyncBaseTransport):
    """httpx -> call(): what Strands' LlamaCppModel sends to "the server" goes over SQS instead."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raw = await request.aread()
        status, ctype, text = await asyncio.to_thread(call, request.url.path, json.loads(raw) if raw else None)
        return httpx.Response(status, headers={"content-type": ctype or "application/json"}, content=text.encode(),
                              request=request)


def strands_model(max_tokens: int = 800):
    from strands.models.llamacpp import LlamaCppModel
    m = LlamaCppModel(base_url="http://model.internal", params={"temperature": 0, "max_tokens": max_tokens})
    m.client = httpx.AsyncClient(base_url="http://model.internal", transport=Transport(), timeout=None)
    return m
