import json

import boto3
import pytest
from moto import mock_aws

from teesri import extract, handler, store, telegram, texts, voice

ME = "tg42"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("TABLE", "t")
    with mock_aws():
        boto3.resource("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
        )
        monkeypatch.setattr(store, "_table", None)
        sent = []
        monkeypatch.setattr(telegram, "webhook_secret", lambda: "s3cret")
        monkeypatch.setattr(telegram, "send_message", lambda chat, text, **kw: sent.append(("text", chat, text, kw.get("reply_markup"))))
        monkeypatch.setattr(telegram, "send_voice", lambda chat, mp3: sent.append(("voice", chat, mp3, None)))
        monkeypatch.setattr(telegram, "answer_callback", lambda cid: None)
        monkeypatch.setattr(telegram, "clear_buttons", lambda chat, mid: None)
        monkeypatch.setattr(voice, "speak", lambda text: b"mp3")
        yield sent


_uid = iter(range(1000, 9999))


def post(update, secret="s3cret"):
    update.setdefault("update_id", next(_uid))
    return handler.main({
        "rawPath": "/tg", "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-telegram-bot-api-secret-token": secret}, "body": json.dumps(update),
    }, None)


def msg(**kw):
    return {"message": {"message_id": next(_uid), "chat": {"id": 42, "type": "private"}, **kw}}


def tap(data):
    return {"callback_query": {"id": "c", "data": data, "message": {"message_id": 1, "chat": {"id": 42}}}}


def join():
    post(msg(text="/start B"))
    post(msg(location={"latitude": 18.9622, "longitude": 72.8368}))
    post(tap("consent|yes"))


def test_wrong_secret_is_rejected(env):
    assert post({"update_id": 1}, secret="nope")["statusCode"] == 401
    assert env == []


def test_enrolment_needs_location_then_consent(env):
    join()
    hh = store.get_household(ME)
    assert store.is_enrolled(hh) and hh["ward"] == "B"
    assert env[0][2] == texts.WELCOME and env[0][3]["keyboard"][0][0]["request_location"]
    assert env[1][2] == texts.CONSENT
    assert env[-1][2] == texts.JOINED


def test_declining_consent_deletes_everything(env):
    post(msg(location={"latitude": 18.9622, "longitude": 72.8368}))
    post(tap("consent|no"))
    assert store.get_household(ME) is None


def test_redelivered_update_is_ignored(env):
    post({"update_id": 7, **msg(text="hello")})
    post({"update_id": 7, **msg(text="hello")})
    assert len(env) == 1


def test_model_reads_voice_note_and_resident_gets_hindi_receipt(env, monkeypatch):
    join()
    monkeypatch.setattr(voice, "read_transcript", lambda name: ("पानी पीला है और बदबू आ रही है तीन दिन से", "k"))
    monkeypatch.setattr(extract, "extract", lambda t: {"colour": "yellow", "smell": True, "since_days": 3, "illness": [], "vulnerable": []})
    handler.main({"source": "aws.transcribe", "detail": {"TranscriptionJobName": f"vn_{ME}_77", "TranscriptionJobStatus": "COMPLETED"}}, None)
    rpt = store.table().get_item(Key={"PK": f"RPT#{ME}-77", "SK": "META"})["Item"]
    assert rpt["colour"] == "yellow" and rpt["source"] == "nova" and rpt["GSI1PK"].startswith("GH6#te7")
    assert env[-2][2] == texts.receipt({"colour": "yellow", "smell": True, "since_days": 3}) and env[-1][0] == "voice"


def test_model_failure_falls_back_to_buttons_and_never_counts_as_clean(env, monkeypatch):
    join()
    monkeypatch.setattr(voice, "read_transcript", lambda name: ("", "k"))
    handler.main({"source": "aws.transcribe", "detail": {"TranscriptionJobName": f"vn_{ME}_78", "TranscriptionJobStatus": "COMPLETED"}}, None)
    assert env[-1][2] == texts.FALLBACK_COLOUR
    assert "Item" not in store.table().get_item(Key={"PK": f"RPT#{ME}-78", "SK": "META"})
    for data in (f"fb|{ME}-78|c|brown", f"fb|{ME}-78|s|1", f"fb|{ME}-78|d|3"):
        post(tap(data))
    rpt = store.table().get_item(Key={"PK": f"RPT#{ME}-78", "SK": "META"})["Item"]
    assert (rpt["colour"], rpt["smell"], rpt["since_days"], rpt["source"]) == ("brown", True, 3, "buttons")
    post(tap(f"fb|{ME}-78|d|3"))  # double tap: no second receipt
    assert sum(1 for e in env if e[0] == "voice") == 1


def test_voice_before_joining_gets_welcome(env, monkeypatch):
    monkeypatch.setattr(telegram, "download_file", lambda fid: pytest.fail("must not download"))
    post(msg(voice={"file_id": "f", "duration": 3}))
    assert env[-1][2] == texts.WELCOME


def test_heard_but_no_details_asks_without_apologising(env, monkeypatch):
    join()
    monkeypatch.setattr(voice, "read_transcript", lambda name: ("पानी गंदा है ।", "k"))
    monkeypatch.setattr(extract, "extract", lambda t: None)  # model unavailable or nothing classifiable
    handler.main({"source": "aws.transcribe", "detail": {"TranscriptionJobName": f"vn_{ME}_79", "TranscriptionJobStatus": "COMPLETED"}}, None)
    assert env[-1][2] == texts.ASK_COLOUR


def test_stop_deletes_the_home(env):
    join()
    post(msg(text="बंद"))
    assert store.get_household(ME) is None and env[-1][2] == texts.LEFT


def test_a_telegram_hiccup_tidying_buttons_does_not_lose_the_answer(env, monkeypatch):
    def boom(*a):
        raise RuntimeError("telegram editMessageReplyMarkup failed: message is not modified")
    monkeypatch.setattr(telegram, "clear_buttons", boom)
    join()
    assert store.is_enrolled(store.get_household(ME))
