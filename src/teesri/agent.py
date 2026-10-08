"""The case agent's three goals (spec §5): prepare_case, notify_water_board, handle_authority_reply.

AGENT_MODE=agent: a Strands agent per goal (case_agent.py); every tool call goes through Cedar.
AGENT_MODE=template, or any agent failure: fixed wording from code, same Cedar checks. Numbers always come from code.
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from teesri import channel, extract, mail, policy, store, texts

MODE = os.environ.get("AGENT_MODE", "template")
GOAL_BUDGET_S = 200  # the case Lambda times out at 300 s
log = logging.getLogger()


def _agent(goal: str, inc_id: str, run):
    """Runs the agent version of a goal; on any failure logs it and returns None (caller uses the template)."""
    if MODE != "agent":
        return None
    from teesri import selfhost
    selfhost.start_budget(GOAL_BUDGET_S)  # leaves the case Lambda time to fall back to the template
    try:
        return run()
    except Exception as e:
        log.exception("agent %s failed", goal)
        store.log_evt(inc_id, actor="case_agent", action=goal, decision="FALLBACK", reason=f"template used: {type(e).__name__}")
        return None
AREA = os.environ.get("AREA_NAME", "Dongri, B ward, Mumbai")
_IST = timezone(timedelta(hours=5, minutes=30))


def _ist(ts: str) -> str:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_IST).strftime("%d %b %H:%M")


# --- goal 1: brief the volunteer ---------------------------------------------------------------------

def prepare_case(inc_id: str, f: dict) -> dict:
    from teesri import case_agent
    if (out := _agent("prepare_case", inc_id, lambda: case_agent.prepare_case(inc_id, f))):
        store.log_evt(inc_id, actor="case_agent", action="prepare_case", decision="DONE", mode="agent", reason="")
        return out
    summary = template_summary(f)
    store.log_evt(inc_id, actor="case_agent", action="prepare_case", decision="DONE", mode="template",
                  reason="Hindi brief from the reports (template wording)")
    return {"summary_hi": summary, "mode": "template"}


def template_summary(f: dict) -> str:
    colours = sorted({texts.COLOUR_HI[r["colour"]] for r in f["reports"] if r.get("colour") in extract.DIRTY_COLOURS})
    what = ", ".join(colours) + " पानी" if colours else "गंदा पानी"
    if any(r.get("smell") for r in f["reports"]):
        what += ", बदबू"
    lines = [f"{f['homes']} पड़ोसी घरों से गंदे पानी की शिकायत: {what}।"]
    for r in f["reports"]:
        if r.get("illness"):
            who = texts.VULNERABLE_OBL.get((r.get("vulnerable") or [""])[0], "किसी")
            lines.append(f"एक घर में {who} को {', '.join(texts.ILLNESS_HI[i] for i in r['illness'])}।")
    return " ".join(lines)


# --- goal 2: tell the ward office (no names or numbers) -----------------------------------------------

def case_file(inc_id: str, f: dict) -> dict:
    """The facts plus how to reach the reporters, as a real case file holds them. Only the agent sees this;
    Cedar keeps contacts out of anything sent to the authority."""
    inc = store.get_incident(inc_id)
    reps = sorted((store.get_report(r) for r in inc["report_ids"]), key=lambda r: r["ts"])
    def contact(hh_id: str) -> str:
        if hh_id.startswith("tg"):
            return f"Telegram chat {hh_id[2:]}"
        return f"+91 00000 {int(hashlib.sha1(hh_id.encode()).hexdigest(), 16) % 100000:05d}"  # simulated: invalid on purpose
    return {**f, "reporters": [{"report": f"R{i}", "contact": contact(r["hh_id"])} for i, r in enumerate(reps, 1)]}


def notify_water_board(inc_id: str, f: dict) -> str | None:
    from teesri import case_agent
    if MODE == "agent":
        sent = _agent("notify_water_board", inc_id, lambda: case_agent.notify_water_board(inc_id, f, case_file(inc_id, f)))
        if sent:
            return sent
    subject, body, fields = compose_email(f)
    to = mail.ward_inbox()
    if not policy.check("workflow", "send_evidence_email", f'Incident::"{inc_id}"', inc_id,
                        fields=fields, recipient_allowlisted=mail.allowlisted(to)):
        return None
    return mail.send(inc_id, to, subject, body)


def compose_email(f: dict) -> tuple[str, str, list[str]]:
    def describe(r: dict) -> str:
        bits = [f"{r['colour']} water" if r.get("colour") in extract.DIRTY_COLOURS else "dirty water"]
        if r.get("smell"):
            bits.append("foul smell")
        if r.get("since_days", -1) >= 0:
            bits.append(f"for {r['since_days']} day{'s' if r['since_days'] != 1 else ''}")
        for i in r.get("illness") or []:
            who = (r.get("vulnerable") or ["a resident"])[0].replace("child", "a child").replace("elderly", "an elderly person")
            bits.append(f"{who} with {i.replace('_', ' ')}")
        return ", ".join(bits)

    pop = f["ring_pop"] if isinstance(f["ring_pop"], str) else f"about {round(f['ring_pop'], -2):,}"
    lat, lon = f["lat"], f["lon"]
    subject = f"Possible tap-water contamination near {AREA} (case {f['inc_id']})"
    body = "\n".join([
        "To the Ward Officer,",
        "",
        f"{f['homes']} households within {f['spread_m']} m of each other reported dirty tap water within "
        f"{round(f['span_h'])} hours ({_ist(f['first_ts'])} to {_ist(f['last_ts'])} IST).",
        "",
        "Reports (anonymised):",
        *[f"- R{i}: {describe(r)}" for i, r in enumerate(f["reports"], 1)],
        "",
        f"Residents within 250 m: {pop} (GHS-POP 2025 estimate).",
        f"Area: 250 m around {lat:.5f}, {lon:.5f} (https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=17/{lat:.5f}/{lon:.5f}).",
        "",
        "Residents of this area have been advised to boil drinking water. We request an inspection of the supply "
        "line and water-quality testing.",
        "",
        "No names or phone numbers are included. The case closes only when residents confirm at the tap that the "
        "water is clean.",
        "",
        "Teesri Shikayat (resident alert system; not affiliated with BMC)",
    ])
    return subject, body, ["case_id", "area", "counts", "reports", "population", "timeline"]


# --- goal 3: the ward office says "resolved" ------------------------------------------------------------

def handle_authority_reply(inc_id: str, f: dict, reply: dict) -> None:
    from teesri import case_agent
    if _agent("handle_authority_reply", inc_id, lambda: case_agent.handle_authority_reply(inc_id, f, reply)):
        return  # the agent tried what it tried (Cedar decided), and asked residents
    res = f'Incident::"{inc_id}"'
    claim = (reply or {}).get("text", "resolved")
    # "Resolved" from the ward office is a request to close the case. Only residents can close it.
    policy.check("ward_office", "close_case", res, inc_id)
    policy.check("workflow", "schedule_checkins", res, inc_id)
    vol_id = store.get_config("volunteer").get("hh_id")
    vol = store.get_household(vol_id) if vol_id else None
    if vol and policy.check("workflow", "notify_volunteer", f'Household::"{vol_id}"', inc_id,
                            recipient_allowlisted=store.is_enrolled(vol)):
        channel.send_text(vol_id, texts.WARD_CLAIM_VOLUNTEER.format(claim=claim))
