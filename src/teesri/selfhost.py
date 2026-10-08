"""The self-hosted model (model/worker.py on the model instance), reached through SQS and the table: no open ports.

call() sends one request for the llama.cpp server and waits for its answer. Transport lets Strands' LlamaCppModel
use it as if the server were local. If the instance is off (no fresh heartbeat), callers fall back at once, and
a goal never runs past its deadline (the case Lambda must still have time to use the template).
"""
import asyncio
import base64
import json
import os
import re
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


def as_stream(completion: dict) -> str:
    """A finished chat completion replayed as the server-sent events a streaming client expects."""
    choice = completion["choices"][0]
    msg, chunks = choice.get("message", {}), []
    delta = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{"index": i, **t} for i, t in enumerate(msg["tool_calls"])]
    chunks.append({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason") or "stop"}],
                   **({"usage": completion["usage"]} if "usage" in completion else {})})
    return "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def botched_call(completion: dict, body: dict) -> bool:
    """Gemma sometimes writes a tool call as plain text ("get_case_facts{}") instead of a structured call."""
    msg = completion["choices"][0].get("message", {})
    if msg.get("tool_calls") or not body.get("tools"):
        return False
    m = re.match(r"\s*(?:call:)?\s*([A-Za-z_]\w*)\s*[{(]", msg.get("content") or "")
    return bool(m) and m.group(1) in {t["function"]["name"] for t in body["tools"]}


class Transport(httpx.AsyncBaseTransport):
    """httpx -> call(): what Strands' LlamaCppModel sends to "the server" goes over SQS instead.

    Answers travel whole anyway, so a streaming request is asked for in one piece and replayed as a stream.
    If the answer is a tool call written as text, the same request is asked again with the tool-call grammar
    enforced (tool_choice "required"), so the call comes back structured."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raw = await request.aread()
        body = json.loads(raw) if raw else None
        stream = isinstance(body, dict) and body.pop("stream", False)
        if stream:
            body.pop("stream_options", None)
        status, ctype, text = await asyncio.to_thread(call, request.url.path, body)
        if status == 200 and isinstance(body, dict) and botched_call(json.loads(text), body):
            status, ctype, text = await asyncio.to_thread(call, request.url.path, {**body, "tool_choice": "required"})
        if stream and status == 200:
            ctype, text = "text/event-stream", as_stream(json.loads(text))
        return httpx.Response(status, headers={"content-type": ctype or "application/json"}, content=text.encode(),
                              request=request)


def strands_model(max_tokens: int = 800):
    from strands.models.llamacpp import LlamaCppModel
    m = LlamaCppModel(base_url="http://model.internal", params={"temperature": 0, "max_tokens": max_tokens})
    m.client = httpx.AsyncClient(base_url="http://model.internal", transport=Transport(), timeout=None)
    return m
