"""Agent mode: a Strands agent per goal. It chooses words and tools; code holds the facts, and every tool call
asks Cedar first (policy.check) and is logged on the Safety tab. A DENY comes back to the agent as the tool result,
so it can recover (redraft without phone numbers, ask residents instead of closing).

Limits (spec §5): temperature 0, at most 6 tool calls per goal. Any failure -> the caller falls back to templates.
"""
import json
import os
import re

from strands import Agent, tool
from strands.models import BedrockModel

from teesri import channel, mail, policy, store

MAX_TOOL_CALLS = 6
_PHONE = re.compile(r"(?:\+?91[\s-]?)?\d{5}[\s-]?\d{5}")


def model():
    return BedrockModel(model_id=os.environ.get("MODEL_ID", "global.amazon.nova-2-lite-v1:0"),
                        region_name=os.environ.get("BEDROCK_REGION", "ap-south-1"), temperature=0, max_tokens=800)


class _Budget:
    def __init__(self):
        self.calls = 0

    def spend(self) -> str | None:
        self.calls += 1
        return "STOP: tool-call limit reached." if self.calls > MAX_TOOL_CALLS else None


def _run(agent: Agent, prompt: str) -> None:
    agent(prompt)


def pii_fields(text: str, contacts: list[str]) -> list[str]:
    """What personal data a draft actually contains (checked by code, not declared by the model)."""
    found, digits = [], re.sub(r"\D", "", text)
    if _PHONE.search(text) or any(len(d) >= 8 and d in digits for d in (re.sub(r"\D", "", c) for c in contacts)):
        found.append("phone")
    if re.search(r"\b(?:tg|sim-)[\w-]+", text):
        found.append("chat_id")
    return found


# --- goal 1: brief the volunteer (read-only) -----------------------------------------------------------

def prepare_case(inc_id: str, f: dict, llm=None) -> dict:
    budget, out = _Budget(), {}
    res = f'Incident::"{inc_id}"'

    def gate(action: str) -> str | None:
        return budget.spend() or (None if policy.check("case_agent", action, res, inc_id, phase="prepare_case")
                                  else f"DENIED by policy: {action} is not allowed while preparing a case.")

    @tool
    def get_reports() -> str:
        """The reports in this incident (colour, smell, days, illness, who is vulnerable, transcript)."""
        return gate("get_reports") or json.dumps([{"id": f"R{i}", **r} for i, r in enumerate(f["reports"], 1)],
                                                  ensure_ascii=False, default=str)

    @tool
    def get_ring_stats() -> str:
        """How many homes reported, how far apart, over how many hours, and how many people live in the ring."""
        return gate("get_ring_stats") or json.dumps({k: f[k] for k in ("homes", "spread_m", "span_h", "ring_pop")}, default=str)

    @tool
    def get_nearby_clinic() -> str:
        """The nearest public hospital to the ring."""
        return gate("get_nearby_clinic") or json.dumps(f["clinic"], ensure_ascii=False)

    @tool
    def submit_brief(summary_hi: str, cited_report_ids: list[str]) -> str:
        """Submit the Hindi brief for the volunteer (1-2 short sentences, no numbers) and the report ids it uses."""
        if (deny := gate("submit_brief")):
            return deny
        out.update(summary_hi=summary_hi.strip(), cited=cited_report_ids)
        return "Brief submitted."

    agent = Agent(model=llm or model(), callback_handler=None,
                  tools=[get_reports, get_ring_stats, get_nearby_clinic, submit_brief],
                  system_prompt=("You brief a local volunteer in Mumbai about a cluster of dirty-water complaints. "
                                 "Read the reports, then call submit_brief once with 1-2 short, plain Hindi sentences: "
                                 "what residents describe and whether anyone is ill. Do not write numbers; code adds them."))
    _run(agent, "Prepare the brief for this case.")
    ids = {f"R{i}" for i in range(1, len(f["reports"]) + 1)}
    if not out.get("summary_hi") or not set(out.get("cited") or []) <= ids or re.search(r"\d", out["summary_hi"]):
        raise ValueError("brief failed the code checks")  # caller falls back to the template brief
    return {"summary_hi": out["summary_hi"], "mode": "agent"}


# --- goal 2: tell the ward office ------------------------------------------------------------------

def notify_water_board(inc_id: str, f: dict, case_file: dict, llm=None) -> str | None:
    """case_file = the facts plus reporter contacts, as a real case file would hold them."""
    budget, sent = _Budget(), {}
    to = mail.ward_inbox()
    contacts = [c["contact"] for c in case_file.get("reporters", [])]

    @tool
    def get_case_facts() -> str:
        """Everything known about this case, including how to reach the residents who reported."""
        return budget.spend() or json.dumps(case_file, ensure_ascii=False, default=str)

    @tool
    def send_evidence_email(subject: str, body: str) -> str:
        """Send the complaint email to the ward office."""
        if (stop := budget.spend()):
            return stop
        fields = ["case_id", "area", "counts", "reports", "timeline", *pii_fields(subject + "\n" + body, contacts)]
        if not policy.check("case_agent", "send_evidence_email", f'Incident::"{inc_id}"', inc_id,
                            fields=fields, recipient_allowlisted=mail.allowlisted(to)):
            return ("DENIED by policy no-pii-to-authority: names and phone numbers never leave the lane. "
                    "Remove all contact details and send again.")
        sent["via"] = mail.send(inc_id, to, subject, body)
        return "Sent."

    agent = Agent(model=llm or model(), callback_handler=None, tools=[get_case_facts, send_evidence_email],
                  system_prompt=("You write a short, formal English complaint email from residents to the Ward Officer, "
                                 "B Ward, Mumbai, about possible tap-water contamination, asking for an inspection and "
                                 "water testing. Use get_case_facts, then send_evidence_email. Include what helps the "
                                 "office act. Sign as 'Teesri Shikayat (resident alert system; not affiliated with BMC)'."))
    _run(agent, "Write and send the complaint for this case.")
    return sent.get("via")


# --- goal 3: the ward office replied -------------------------------------------------------------------

def handle_authority_reply(inc_id: str, f: dict, reply: dict, llm=None) -> bool:
    budget, did = _Budget(), set()
    res = f'Incident::"{inc_id}"'
    vol_id = store.get_config("volunteer").get("hh_id", "")

    @tool
    def close_case(reason: str) -> str:
        """Close this case."""
        if (stop := budget.spend()):
            return stop
        if not policy.check("case_agent", "close_case", res, inc_id):
            return "DENIED by policy only-residents-close: only residents can close a case."
        did.add("close_case")
        return "Closed."

    @tool
    def schedule_checkins() -> str:
        """Ask every enrolled home in the ring whether their tap water is clean now."""
        if (stop := budget.spend()):
            return stop
        if not policy.check("case_agent", "schedule_checkins", res, inc_id):
            return "DENIED by policy."
        did.add("schedule_checkins")
        return "Check-ins scheduled: every home in the ring will be asked."

    @tool
    def notify_volunteer(message_hi: str) -> str:
        """Send a short Hindi update to the local volunteer."""
        if (stop := budget.spend()):
            return stop
        vol = store.get_household(vol_id) if vol_id else None
        if not vol or not policy.check("case_agent", "notify_volunteer", f'Household::"{vol_id}"', inc_id,
                                       recipient_allowlisted=store.is_enrolled(vol)):
            return "DENIED by policy."
        channel.send_text(vol_id, message_hi[:500])
        return "Sent."

    agent = Agent(model=llm or model(), callback_handler=None, tools=[close_case, schedule_checkins, notify_volunteer],
                  system_prompt=("You manage a dirty-water case in Mumbai. The ward office has replied. "
                                 "Act on their reply with the tools you have, then stop."))
    _run(agent, f"The ward office replied: \"{(reply or {}).get('text', 'Resolved')}\"")
    return "schedule_checkins" in did
