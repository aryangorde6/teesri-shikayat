"""The self-hosted model path: SQS request -> (fake) worker -> table answer, used by extraction and by Strands."""
import base64
import json
import time
import zlib

import pytest
from strands import Agent

from teesri import extract, selfhost, store


class FakeWorker:
    """Stands in for model/worker.py: answers every request at once by writing MODELRESP#<id>."""

    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def send_message(self, QueueUrl, MessageBody):
        req = json.loads(MessageBody)
        self.requests.append(req)
        status, ctype, text = self.reply(req)
        store.table().put_item(Item={"PK": f"MODELRESP#{req['id']}", "SK": "META", "status": status, "type": ctype,
                                     "body_z": base64.b64encode(zlib.compress(text.encode())).decode()})


@pytest.fixture
def model_up(env, monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "selfhost")
    monkeypatch.setenv("MODEL_QUEUE_URL", "q")
    monkeypatch.setattr(selfhost, "_deadline", None)
    store.table().put_item(Item={"PK": "MODEL#heartbeat", "SK": "META", "ts": int(time.time()), "model": "m"})

    def use(reply):
        w = FakeWorker(reply)
        monkeypatch.setattr(selfhost, "_sqs", w)
        return w
    return use


def test_available_needs_a_fresh_heartbeat(model_up):
    assert selfhost.available()
    store.table().put_item(Item={"PK": "MODEL#heartbeat", "SK": "META", "ts": int(time.time()) - 300, "model": "m"})
    assert not selfhost.available()


def test_extraction_uses_the_schema_and_still_validates(model_up):
    w = model_up(lambda req: (200, "application/json", json.dumps({"choices": [{"message": {"content": json.dumps(
        {"colour": "brown", "smell": "yes", "since_days": 2, "illness": ["diarrhoea", "fever", "made_up"], "vulnerable": []})}}]})))
    f = extract.extract("नल से भूरा पानी आ रहा है, बदबू है, दो दिन से, दस्त")
    assert (f["colour"], f["smell"], f["since_days"], f["illness"]) == ("brown", True, 2, ["diarrhoea"])  # fever not said
    assert w.requests[0]["body"]["response_format"]["json_schema"]["schema"]["required"]
    assert not store.table().scan()["Items"][1:]  # the answer item is cleaned up (only the heartbeat is left)


def test_instance_off_means_no_request_at_all(model_up):
    w = model_up(lambda req: pytest.fail("must not send"))
    store.table().delete_item(Key={"PK": "MODEL#heartbeat", "SK": "META"})
    assert extract.extract("पानी पीला है") is None


def test_goal_budget_stops_calls(model_up):
    model_up(lambda req: (200, "application/json", "{}"))
    selfhost.start_budget(-1)
    with pytest.raises(TimeoutError):
        selfhost.call("/v1/chat/completions", {})


def test_strands_agent_talks_to_the_model_through_the_queue(model_up):
    chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": "ठीक है"}, "finish_reason": None}]},
              {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}]
    sse = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    w = model_up(lambda req: (200, "text/event-stream", sse))
    result = Agent(model=selfhost.strands_model(), callback_handler=None)("नमस्ते")
    assert str(result).strip() == "ठीक है"
    assert w.requests[0]["path"] == "/v1/chat/completions" and w.requests[0]["body"]["stream"] is True
