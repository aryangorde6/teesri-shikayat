"""Minimal Telegram Bot API client (stdlib only). Secrets come from SSM, never from code or env."""
import json
import os
import urllib.request

import boto3

_cache: dict[str, str] = {}
_ssm = None


def _param(name: str) -> str:
    global _ssm
    if name not in _cache:
        _ssm = _ssm or boto3.client("ssm")
        _cache[name] = _ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cache[name]


def webhook_secret() -> str:
    return _param(os.environ["TG_SECRET_PARAM"])


def call(method: str, **payload) -> dict:
    token = _param(os.environ["TG_TOKEN_PARAM"])
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        out = json.load(r)
    if not out.get("ok"):
        raise RuntimeError(f"telegram {method} failed: {out.get('description')}")
    return out["result"]


def send_message(chat_id: int, text: str, **kw) -> dict:
    return call("sendMessage", chat_id=chat_id, text=text, **kw)
