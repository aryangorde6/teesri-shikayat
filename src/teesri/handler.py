"""The single Lambda. Entry points:
- Function URL: GET / (health), POST /tg (Telegram webhook)
- EventBridge: a Transcribe job finished -> extract fields -> report -> Hindi receipt
"""
import base64
import hmac
import json
import logging

from teesri import channel, extract, store, telegram, texts, voice, workflow

log = logging.getLogger()
log.setLevel(logging.INFO)


def main(event, context):
    if event.get("source") == "aws.transcribe":
        return on_transcribed(event["detail"])
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


# --- Telegram updates ---------------------------------------------------------

def on_update(update: dict) -> None:
    if not store.first_time(update["update_id"]):
        return
    if "callback_query" in update:
        return on_button(update["callback_query"])
    msg = update.get("message")
    if not msg or msg["chat"].get("type") != "private":
        return
    hh_id = f"tg{msg['chat']['id']}"
    if msg.get("text", "").startswith("/start"):
        return on_start(hh_id, msg["text"])
    if "location" in msg:
        return on_location(hh_id, msg["location"])
    if "voice" in msg:
        return on_voice(hh_id, msg)
    if store.is_enrolled(store.get_household(hh_id)):
        channel.send_text(hh_id, texts.SEND_VOICE)
    else:
        channel.send_text(hh_id, texts.WELCOME, location_keyboard=texts.SEND_LOCATION)


def on_start(hh_id: str, text: str) -> None:
    """/start <ward> arrives from the QR deep link t.me/TeesriShikayatBot?start=<ward>."""
    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        store.upsert_household(hh_id, ward=parts[1][:20], channel="telegram")
    channel.send_text(hh_id, texts.WELCOME, location_keyboard=texts.SEND_LOCATION)


def on_location(hh_id: str, loc: dict) -> None:
    lat, lon = float(loc["latitude"]), float(loc["longitude"])
    if store.is_enrolled(store.get_household(hh_id)):
        store.upsert_household(hh_id, lat=lat, lon=lon)
        return channel.send_text(hh_id, texts.LOCATION_UPDATED)
    store.upsert_household(hh_id, lat=lat, lon=lon, channel="telegram")
    channel.send_text(hh_id, texts.CONSENT, buttons=[[(texts.YES, "consent|yes"), (texts.NO, "consent|no")]])


def on_voice(hh_id: str, msg: dict) -> None:
    if not store.is_enrolled(store.get_household(hh_id)):
        return channel.send_text(hh_id, texts.WELCOME, location_keyboard=texts.SEND_LOCATION)
    ogg = telegram.download_file(msg["voice"]["file_id"])
    if voice.start_transcription(voice.job_name(hh_id, msg["message_id"]), ogg):
        channel.send_text(hh_id, "🎧 सुन रहे हैं…")


def on_button(cq: dict) -> None:
    telegram.answer_callback(cq["id"])
    chat_id, data = cq["message"]["chat"]["id"], cq.get("data", "")
    telegram.clear_buttons(chat_id, cq["message"]["message_id"])  # one answer per question
    hh_id = f"tg{chat_id}"
    kind, *rest = data.split("|")
    if kind == "consent":
        return on_consent(hh_id, rest[0] == "yes")
    if kind == "fb" and len(rest) == 3:
        return on_fallback_answer(hh_id, *rest)
    if kind == "ap" and len(rest) == 2:  # volunteer: हाँ, भेजें / अभी नहीं
        return channel.send_text(hh_id, workflow.approve(hh_id, rest[0], rest[1] == "y"))
    if kind == "ck" and len(rest) == 2:  # resident: पानी साफ़ है? हाँ / नहीं
        return channel.send_text(hh_id, workflow.answer_checkin(hh_id, rest[0], rest[1] == "y"))


def on_consent(hh_id: str, yes: bool) -> None:
    hh = store.get_household(hh_id)
    if not yes:
        store.delete_household(hh_id)
        return channel.send_text(hh_id, texts.DECLINED)
    if not hh or "lat" not in hh:
        return channel.send_text(hh_id, texts.WELCOME, location_keyboard=texts.SEND_LOCATION)
    if not hh.get("consent_ts"):
        store.upsert_household(hh_id, consent_ts=store.now_iso())
    channel.send_text(hh_id, texts.JOINED)


# --- Fallback questions (when the model can't read the voice note) -------------

def ask_colour(hh_id: str, rpt_id: str, heard: bool = False) -> None:
    text = texts.ASK_COLOUR if heard else texts.FALLBACK_COLOUR
    channel.send_text(hh_id, text, buttons=[[(t, f"fb|{rpt_id}|c|{v}") for t, v in texts.COLOUR_BUTTONS]])


def on_fallback_answer(hh_id: str, rpt_id: str, field: str, value: str) -> None:
    draft = store.get_draft(rpt_id)
    if not draft or draft.get("hh_id") != hh_id:
        return
    if field == "c" and value in extract.COLOURS:
        store.update_draft(rpt_id, "colour", value)
        channel.send_text(hh_id, texts.ASK_SMELL, buttons=[[(texts.YES, f"fb|{rpt_id}|s|1"), (texts.NO, f"fb|{rpt_id}|s|0")]])
    elif field == "s":
        store.update_draft(rpt_id, "smell", value == "1")
        channel.send_text(hh_id, texts.ASK_SINCE, buttons=[[(t, f"fb|{rpt_id}|d|{v}") for t, v in texts.SINCE_BUTTONS]])
    elif field == "d" and value.isdigit():
        fields = {"colour": draft.get("colour"), "smell": draft.get("smell"), "since_days": int(value),
                  "illness": [], "vulnerable": []}
        finalize(rpt_id, store.get_household(hh_id), fields, "buttons",
                 draft.get("transcript", ""), draft.get("transcript_key", ""))


# --- Transcribe finished ------------------------------------------------------

def on_transcribed(detail: dict) -> None:
    name = detail["TranscriptionJobName"]               # vn_<hh_id>_<message_id>
    hh_id, message_id = name[3:].rsplit("_", 1)
    rpt_id = f"{hh_id}-{message_id}"                     # deterministic: a re-delivered event can't make a 2nd report
    hh = store.get_household(hh_id)
    if not store.is_enrolled(hh):
        return
    transcript, key = ("", "")
    if detail.get("TranscriptionJobStatus") == "COMPLETED":
        transcript, key = voice.read_transcript(name)
    log.info("transcript %s: %s", rpt_id, transcript)
    fields = extract.extract(transcript)
    if fields:
        return finalize(rpt_id, hh, fields, "nova", transcript, key)
    store.put_draft(rpt_id, hh_id=hh_id, transcript=transcript, transcript_key=key)
    ask_colour(hh_id, rpt_id, heard=bool(transcript.strip()))


def finalize(rpt_id: str, hh: dict, fields: dict, source: str, transcript: str = "", key: str = "") -> None:
    if not store.put_report(rpt_id, hh, fields, source, transcript, key):
        return  # already recorded
    hh_id = hh["PK"].removeprefix("HH#")
    text = texts.receipt(fields)
    channel.send_text(hh_id, text)
    channel.send_voice(hh_id, voice.speak(text))


def _resp(status: int, text: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": "text/plain; charset=utf-8"}, "body": text}
