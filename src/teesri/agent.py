"""The case agent's three goals (spec §5): prepare_case, notify_water_board, handle_authority_reply.

Mode "template" (now): wording comes from fixed code templates; the same Cedar checks guard every action.
Mode "agent" (when Bedrock quota arrives): a Strands agent writes the words and picks tools; every tool call
still goes through policy.check. Numbers always come from code, never from a model.
"""
import os
from datetime import datetime, timedelta, timezone

from teesri import channel, extract, mail, policy, store, texts

MODE = os.environ.get("AGENT_MODE", "template")
AREA = os.environ.get("AREA_NAME", "Dongri, B ward, Mumbai")
_IST = timezone(timedelta(hours=5, minutes=30))


def _ist(ts: str) -> str:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_IST).strftime("%d %b %H:%M")


# --- goal 1: brief the volunteer ---------------------------------------------------------------------

def prepare_case(inc_id: str, f: dict) -> dict:
    summary = template_summary(f)
    store.log_evt(inc_id, actor="case_agent", action="prepare_case", decision="DONE", mode=MODE,
                  reason="Hindi brief from the reports (template wording)" if MODE == "template" else "")
    return {"summary_hi": summary, "mode": MODE}


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

def notify_water_board(inc_id: str, f: dict) -> str | None:
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
