"""Agent mode, offline: a scripted model plays the LLM's turns; the tools, Cedar checks and logs are real."""
import json

from strands.models import Model

from teesri import case_agent, store, texts
from test_case import FakeSfn, incident  # noqa: F401  (same demo incident)
from teesri import case, workflow


class Scripted(Model):
    """Replays tool calls in order, then ends the turn. Records what each tool returned."""

    def __init__(self, calls):
        self.calls, self.results = list(calls), []

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, *a, **kw):
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        last = messages[-1]["content"] if messages else []
        self.results += [c["toolResult"]["content"][0]["text"] for c in last if "toolResult" in c]
        yield {"messageStart": {"role": "assistant"}}
        if self.calls:
            name, args = self.calls.pop(0)
            yield {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": f"t{len(self.calls)}"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args, ensure_ascii=False)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Done."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def evts(inc_id, action):
    return [(e["actor"], e["decision"], e.get("policy")) for e in store.events(inc_id) if e["action"] == action]


def test_agent_email_with_phone_numbers_is_denied_then_redrafted(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    inc_id = incident(env)
    from teesri import agent
    f = case.facts(store.get_incident(inc_id))
    cf = agent.case_file(inc_id, f)
    phone = cf["reporters"][0]["contact"]
    llm = Scripted([("get_case_facts", {}),
                    ("send_evidence_email", {"subject": "Dirty water", "body": f"Please call R1 on {phone.replace(' ', '')}."}),
                    ("send_evidence_email", {"subject": "Dirty water", "body": "Three households report dirty water."})])
    assert case_agent.notify_water_board(inc_id, f, cf, llm=llm) == "stored"
    assert evts(inc_id, "send_evidence_email") == [("case_agent", "DENY", "no-pii-to-authority"),
                                                   ("case_agent", "ALLOW", "baseline")]
    assert any(r.startswith("DENIED by policy no-pii-to-authority") for r in llm.results)
    [mail] = [i for i in store.table().scan()["Items"] if i["SK"].startswith("MAIL#")]
    assert "R1 on" not in mail["body"]


def test_agent_believes_the_ward_office_tries_to_close_and_is_denied(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    inc_id = incident(env)
    f = case.facts(store.get_incident(inc_id))
    llm = Scripted([("close_case", {"reason": "Ward office says resolved"}), ("schedule_checkins", {}),
                    ("notify_volunteer", {"message_hi": "वार्ड ऑफिस ने ठीक बताया; घरों से पूछ रहे हैं।"})])
    assert case_agent.handle_authority_reply(inc_id, f, {"text": "Resolved"}, llm=llm) is True
    assert evts(inc_id, "close_case") == [("case_agent", "DENY", "only-residents-close")]
    assert llm.results[0] == "DENIED by policy only-residents-close: only residents can close a case."
    assert env[-1] == ("tg42", "वार्ड ऑफिस ने ठीक बताया; घरों से पूछ रहे हैं।")


def test_agent_brief_is_checked_by_code(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    inc_id = incident(env)
    f = case.facts(store.get_incident(inc_id))
    good = Scripted([("get_reports", {}), ("submit_brief", {"summary_hi": "पड़ोस में भूरा, बदबूदार पानी; एक बच्चे को दस्त।",
                                                            "cited_report_ids": ["R1", "R2"]})])
    assert case_agent.prepare_case(inc_id, f, llm=good)["mode"] == "agent"
    made_up = Scripted([("submit_brief", {"summary_hi": "सात घरों से शिकायत, 7 लोग बीमार।", "cited_report_ids": ["R9"]})])
    try:
        case_agent.prepare_case(inc_id, f, llm=made_up)
        raise AssertionError("a brief citing a report that doesn't exist must be rejected")
    except ValueError:
        pass


def test_agent_stops_after_six_tool_calls(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    inc_id = incident(env)
    f = case.facts(store.get_incident(inc_id))
    llm = Scripted([("schedule_checkins", {})] * 7)
    case_agent.handle_authority_reply(inc_id, f, {"text": "Resolved"}, llm=llm)
    assert llm.results[-1] == "STOP: tool-call limit reached." and len(evts(inc_id, "schedule_checkins")) == 6


def test_agent_failure_falls_back_to_templates(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    from teesri import agent
    monkeypatch.setattr(agent, "MODE", "agent")
    monkeypatch.setattr(case_agent, "model", lambda: (_ for _ in ()).throw(RuntimeError("Too many tokens per day")))
    inc_id = incident(env)
    case.prepare({"inc_id": inc_id})
    inc = store.get_incident(inc_id)
    assert inc["brief_mode"] == "template" and ("case_agent", "FALLBACK", None) in evts(inc_id, "prepare_case")
    assert texts.VOLUNTEER_CARD  # the template path still produces the card
