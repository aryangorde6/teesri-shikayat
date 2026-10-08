"""Minimal Telegram Bot API client (stdlib only). Secrets come from SSM, never from code or env."""
import json
import os
import secrets
import urllib.request

import boto3

_cache: dict[str, str] = {}
_ssm = None
API = "https://api.telegram.org"


def _param(name: str) -> str:
    global _ssm
    if name not in _cache:
        _ssm = _ssm or boto3.client("ssm")
        _cache[name] = _ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cache[name]


def _token() -> str:
    return _param(os.environ["TG_TOKEN_PARAM"])


def webhook_secret() -> str:
    return _param(os.environ["TG_SECRET_PARAM"])


def _post(method: str, body: bytes, content_type: str) -> dict:
    req = urllib.request.Request(f"{API}/bot{_token()}/{method}", data=body, headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=15) as r:
        out = json.load(r)
    if not out.get("ok"):
        raise RuntimeError(f"telegram {method} failed: {out.get('description')}")
    return out["result"]


def call(method: str, **payload) -> dict:
    return _post(method, json.dumps(payload).encode(), "application/json")


def send_message(chat_id: int, text: str, **kw) -> dict:
    return call("sendMessage", chat_id=chat_id, text=text, **kw)


def send_voice(chat_id: int, mp3: bytes) -> dict:
    boundary = secrets.token_hex(16)
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="voice"; filename="voice.mp3"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode() + mp3 + f"\r\n--{boundary}--\r\n".encode()
    return _post("sendVoice", body, f"multipart/form-data; boundary={boundary}")


def download_file(file_id: str) -> bytes:
    path = call("getFile", file_id=file_id)["file_path"]
    with urllib.request.urlopen(f"{API}/file/bot{_token()}/{path}", timeout=15) as r:
        return r.read()


def answer_callback(callback_id: str) -> None:
    call("answerCallbackQuery", callback_query_id=callback_id)


def clear_buttons(chat_id: int, message_id: int) -> None:
    call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})
