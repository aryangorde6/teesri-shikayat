"""The self-hosted model path: SQS request -> (fake) worker -> table answer, used by extraction and by Strands."""
import base64
import json
import time
import zlib

import pytest
from strands import Agent, tool

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


def completion(content="", tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content, **({"tool_calls": tool_calls} if tool_calls else {})}
    return 200, "application/json", json.dumps({"choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                                                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}})


def test_strands_agent_talks_to_the_model_through_the_queue(model_up):
    w = model_up(lambda req: completion("ठीक है"))
    result = Agent(model=selfhost.strands_model(), callback_handler=None)("नमस्ते")
    assert str(result).strip() == "ठीक है"
    body = w.requests[0]["body"]
    assert w.requests[0]["path"] == "/v1/chat/completions" and "stream" not in body  # asked for whole, replayed


def test_strands_agent_runs_tools_through_the_queue(model_up):
    seen = []

    @tool
    def get_case_facts() -> str:
        """Everything known about this case."""
        seen.append("facts")
        return '{"homes": 3}'

    replies = iter([completion(tool_calls=[{"id": "c1", "type": "function",
                                            "function": {"name": "get_case_facts", "arguments": "{}"}}], finish="tool_calls"),
                    completion("3 घर")])
    w = model_up(lambda req: next(replies))
    result = Agent(model=selfhost.strands_model(), callback_handler=None, tools=[get_case_facts])("facts?")
    assert seen == ["facts"] and str(result).strip() == "3 घर"
    assert w.requests[1]["body"]["messages"][-1]["role"] == "tool"


def test_a_tool_call_written_as_text_is_asked_again_with_the_grammar(model_up):
    seen = []

    @tool
    def get_case_facts() -> str:
        """Everything known about this case."""
        seen.append("facts")
        return '{"homes": 3}'

    def reply(req):
        if req["body"].get("tool_choice") == "required":
            return completion(tool_calls=[{"id": "c1", "type": "function",
                                           "function": {"name": "get_case_facts", "arguments": "{}"}}], finish="tool_calls")
        if req["body"]["messages"][-1]["role"] == "tool":
            return completion("3 घर")
        return completion("get_case_facts{}")  # what Gemma sometimes writes
    w = model_up(reply)
    result = Agent(model=selfhost.strands_model(), callback_handler=None, tools=[get_case_facts])("facts?")
    assert seen == ["facts"] and str(result).strip() == "3 घर"
    assert [r["body"].get("tool_choice") for r in w.requests] == [None, "required", None]


def test_after_a_deny_a_text_answer_is_asked_again_as_a_tool_call(model_up):
    sent = []

    @tool
    def send_evidence_email(subject: str, body: str) -> str:
        """Send the complaint email to the ward office."""
        sent.append(body)
        return ("DENIED by policy no-pii-to-authority: names and phone numbers never leave the lane."
                if "+91" in body else "Sent.")

    def call_with(body):
        return completion(tool_calls=[{"id": f"c{len(sent)}", "type": "function", "function": {
            "name": "send_evidence_email", "arguments": json.dumps({"subject": "s", "body": body})}}], finish="tool_calls")

    def reply(req):
        last = req["body"]["messages"][-1]
        if last["role"] == "user":
            return call_with("call +91 00000 12345")         # first draft leaks a phone number
        if "DENIED" in json.dumps(last, ensure_ascii=False):
            if req["body"].get("tool_choice") == "required":
                return call_with("3 homes, 212 m")           # forced to act: the redraft goes through the tool
            return completion("Here is the corrected email: 3 homes, 212 m")  # what Gemma does unforced
        return completion("Done.")
    w = model_up(reply)
    Agent(model=selfhost.strands_model(), callback_handler=None, tools=[send_evidence_email])("send it")
    assert sent == ["call +91 00000 12345", "3 homes, 212 m"]
    assert [r["body"].get("tool_choice") for r in w.requests] == [None, None, "required", None]
