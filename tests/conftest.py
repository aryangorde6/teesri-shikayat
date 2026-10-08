"""Shared fixture: a moto DynamoDB table shaped like the real one (with GSI1), and fake outbound messages."""
import boto3
import pytest
from moto import mock_aws

from teesri import channel, store, voice


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("TABLE", "t")
    with mock_aws():
        s = "S"
        boto3.resource("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": a, "AttributeType": s} for a in ("PK", "SK", "GSI1PK", "GSI1SK")],
            GlobalSecondaryIndexes=[{
                "IndexName": "GSI1", "Projection": {"ProjectionType": "ALL"},
                "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}, {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
            }],
        )
        monkeypatch.setattr(store, "_table", None)
        sent = []
        monkeypatch.setattr(channel, "send_text", lambda hh, text, **kw: sent.append((hh, text)))
        monkeypatch.setattr(channel, "send_voice", lambda hh, mp3, **kw: None)
        monkeypatch.setattr(voice, "speak", lambda text: b"mp3")
        yield sent
