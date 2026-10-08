"""The single Lambda behind the Function URL. Routes: GET / (health), POST /tg (Telegram webhook)."""
import base64
import hmac
import json
import logging

from teesri import telegram

log = logging.getLogger()
log.setLevel(logging.INFO)


def main(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "POST" and path == "/tg":
        return _telegram(event)
    if method == "GET" and path == "/":
        return _resp(200, "Teesri Shikayat is running.")
    return _resp(404, "not found")


def _telegram(event):
    got = (event.get("headers") or {}).get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(got, telegram.webhook_secret()):
        return _resp(401, "unauthorised")
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    update = json.loads(body)
    try:
        on_update(update)
    except Exception:
        # Telegram retries non-200s for hours; log loudly and acknowledge instead.
        log.exception("update %s failed", update.get("update_id"))
    return _resp(200, "ok")


def on_update(update: dict) -> None:
    msg = update.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    if "text" in msg:
        telegram.send_message(chat_id, f"echo: {msg['text']}")
    elif "voice" in msg:
        telegram.send_message(chat_id, f"voice note received ({msg['voice'].get('duration', '?')} s)")


def _resp(status: int, text: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": "text/plain; charset=utf-8"}, "body": text}
