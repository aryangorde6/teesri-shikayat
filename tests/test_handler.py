import json

import pytest

from teesri import handler, telegram


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(telegram, "webhook_secret", lambda: "s3cret")
    monkeypatch.setattr(telegram, "send_message", lambda chat_id, text, **kw: out.append((chat_id, text)))
    return out


def tg_event(update, secret="s3cret"):
    return {
        "rawPath": "/tg",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-telegram-bot-api-secret-token": secret},
        "body": json.dumps(update),
    }


def test_wrong_secret_is_rejected(sent):
    r = handler.main(tg_event({"update_id": 1}, secret="nope"), None)
    assert r["statusCode"] == 401 and sent == []


def test_text_is_echoed(sent):
    r = handler.main(tg_event({"update_id": 2, "message": {"chat": {"id": 7}, "text": "paani ganda hai"}}), None)
    assert r["statusCode"] == 200 and sent == [(7, "echo: paani ganda hai")]


def test_failure_still_acks_telegram(sent, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(telegram, "send_message", boom)
    r = handler.main(tg_event({"update_id": 3, "message": {"chat": {"id": 7}, "text": "hi"}}), None)
    assert r["statusCode"] == 200
