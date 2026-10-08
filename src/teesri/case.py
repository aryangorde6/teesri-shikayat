"""The case, one Step Functions task at a time. A single Lambda serves every task state (event["step"]).

prepare → ask_volunteer [waits for हाँ, भेजें] → ring → warn_home (Map: every enrolled home in the ring) → warned
→ notify_ward → await_reply [waits for the ward office] → handle_reply → checkins [waits: a नहीं ends the round]
→ evaluate → REOPENED (back to await_reply) | CLOSED_AT_TAP | another round | STILL_OPEN.
Every message and close attempt asks Cedar first (policy.check), and the decision lands on the Safety tab.
"""
import json
import logging
import os
import pathlib
from functools import cache

import boto3

from teesri import agent, channel, geo, policy, store, texts, tripwire, voice

log = logging.getLogger()
log.setLevel(logging.INFO)
MIN_CLEAN = 3  # CLOSED_AT_TAP needs at least 3 "clean" answers and no "dirty" one
MAX_ROUNDS = 3


def main(event, context):
    log.info("case step %s %s", event.get("step"), event.get("inc_id"))
    return STEPS[event["step"]](event) or {}


# --- facts the agent and messages are built from (numbers come from code) ---------------------------

def facts(inc: dict) -> dict:
    reports = sorted((store.get_report(r) for r in inc["report_ids"]), key=lambda r: r["ts"])
    fired = inc["fired"]
    return {
        "inc_id": inc["inc_id"], "lat": float(inc["lat"]), "lon": float(inc["lon"]),
        "homes": len(inc["homes"]), "spread_m": int(fired["spread_m"]), "span_h": float(fired["span_h"]),
        "ring_pop": inc["ring_pop"] if isinstance(inc["ring_pop"], str) else int(inc["ring_pop"]),
        "first_ts": reports[0]["ts"], "last_ts": reports[-1]["ts"],
        "reports": [{k: r.get(k) for k in ("colour", "smell", "since_days", "illness", "vulnerable", "transcript")}
                    for r in reports],
        "clinic": nearest_clinic(float(inc["lat"]), float(inc["lon"])),
    }


@cache
def _clinics() -> list[dict]:
    return json.loads((pathlib.Path(__file__).parent / "data" / "clinics_dongri.json").read_text())["clinics"]


def nearest_clinic(lat: float, lon: float) -> dict:
    return min(_clinics(), key=lambda c: geo.distance_m(lat, lon, c["lat"], c["lon"]))


def _inc(e: dict) -> dict:
    return store.get_incident(e["inc_id"])


def _res(inc_id: str) -> str:
    return f'Incident::"{inc_id}"'


# --- steps ----------------------------------------------------------------------------------------

def prepare(e):
    inc = _inc(e)
    brief = agent.prepare_case(inc["inc_id"], facts(inc))
    store.update_incident(inc["inc_id"], brief_hi=brief["summary_hi"], brief_mode=brief["mode"], status="PREPARED")


def ask_volunteer(e):
    inc = _inc(e)
    vol_id = store.get_config("volunteer").get("hh_id", "")
    vol = store.get_household(vol_id) if vol_id else None
    short = store.put_token(e["token"], inc["inc_id"], "approve", hh_id=vol_id)
    store.update_incident(inc["inc_id"], status="AWAITING_APPROVAL", approve_tok=short, volunteer=vol_id)
    if vol and policy.check("workflow", "notify_volunteer", f'Household::"{vol_id}"', inc["inc_id"],
                            recipient_allowlisted=store.is_enrolled(vol)):
        fired = inc["fired"]
        text = texts.VOLUNTEER_CARD.format(summary=inc["brief_hi"], homes=len(inc["homes"]),
                                           spread_m=fired["spread_m"], hours=round(float(fired["span_h"])))
        channel.send_text(vol_id, text, buttons=[[(texts.APPROVE_YES, f"ap|{short}|y"),
                                                  (texts.APPROVE_NO, f"ap|{short}|n")]])
    # No volunteer reachable -> nobody can approve -> the step times out -> UNAPPROVED. Never a silent send.


def ring(e):
    inc = _inc(e)
    homes = [h["PK"].removeprefix("HH#") for h in store.households_near(float(inc["lat"]), float(inc["lon"]), tripwire.RING_M)]
    store.update_incident(inc["inc_id"], ring_hh=homes, status="WARNING")
    make_audio(inc["inc_id"], "ring_warning_v1", warning_text(inc))
    return {"homes": homes}


def warn_home(e):
    inc, hh_id = _inc(e), e["hh_id"]
    hh = store.get_household(hh_id)
    enrolled = store.is_enrolled(hh)
    if not policy.check("workflow", "broadcast_warning", f'Household::"{hh_id}"', inc["inc_id"],
                        volunteer_approved=bool(inc.get("approved_by")), template_id="ring_warning_v1",
                        consent=enrolled, recipient_allowlisted=enrolled):
        return {"hh_id": hh_id, "sent": False}
    _say(hh_id, inc["inc_id"], "ring_warning_v1", warning_text(inc))
    return {"hh_id": hh_id, "sent": True}


def warning_text(inc: dict) -> str:
    clinic = nearest_clinic(float(inc["lat"]), float(inc["lon"]))
    return texts.RING_WARNING.format(homes=len(inc["homes"]), clinic=clinic["name_hi"])


def warned(e):
    inc = _inc(e)
    ring_hh = inc.get("ring_hh", [])
    never = [h for h in ring_hh if h not in inc["homes"]]
    store.update_incident(inc["inc_id"], status="WARNED", warned_ts=store.now_iso(), warned_count=len(ring_hh))
    store.log_event("case", decision="warned", inc_id=inc["inc_id"], homes=len(ring_hh), never_complained=len(never))
    return {"warned": len(ring_hh), "never_complained": len(never)}


def notify_ward(e):
    inc = _inc(e)
    via = agent.notify_water_board(inc["inc_id"], facts(inc))
    store.update_incident(inc["inc_id"], status="WARD_NOTIFIED" if via else "WARD_NOT_NOTIFIED")


def await_reply(e):
    short = store.put_token(e["token"], e["inc_id"], "ward_reply")
    store.update_incident(e["inc_id"], status="AWAITING_WARD", ward_tok=short)


def handle_reply(e):
    inc = _inc(e)
    reply = e.get("reply") or {}
    agent.handle_authority_reply(inc["inc_id"], facts(inc), reply)
    store.update_incident(inc["inc_id"], status="CLAIMED_RESOLVED", claim=reply.get("text", ""), claim_ts=store.now_iso())
    store.log_event("case", decision="ward_says_resolved", inc_id=inc["inc_id"], claim=reply.get("text", ""))


def checkins(e):
    inc = _inc(e)
    rnd = int(inc.get("checkin_round", 0)) + 1
    short = store.put_token(e["token"], inc["inc_id"], "checkin", round=rnd)
    store.update_incident(inc["inc_id"], checkin_round=rnd, checkin_tok=short, status="CHECKING")
    for hh_id in inc.get("ring_hh", []):
        hh = store.get_household(hh_id)
        enrolled = store.is_enrolled(hh)
        if policy.check("workflow", "message_household", f'Household::"{hh_id}"', inc["inc_id"],
                        consent=enrolled, recipient_allowlisted=enrolled):
            channel.send_text(hh_id, texts.CHECKIN, buttons=[[(texts.CHECKIN_YES, f"ck|{short}|y"),
                                                             (texts.CHECKIN_NO, f"ck|{short}|n")]])


def closure_outcome(answers: list[dict]) -> str:
    """Only residents close a case. Any "dirty" answer reopens it; silence never closes it."""
    clean = sum(1 for a in answers if a["clean"])
    if clean < len(answers):
        return "REOPENED"
    return "CLOSED_AT_TAP" if clean >= MIN_CLEAN else "STILL_OPEN"


def evaluate(e):
    inc = _inc(e)
    rnd = int(inc["checkin_round"])
    answers = store.checkins(inc["inc_id"], rnd)
    outcome = closure_outcome(answers)
    clean = sum(1 for a in answers if a["clean"])
    if outcome == "CLOSED_AT_TAP":
        policy.check("quorum_evaluator", "close_case", _res(inc["inc_id"]), inc["inc_id"], quorum_met=True)
    store.log_event("case", decision=outcome.lower(), inc_id=inc["inc_id"], round=rnd, clean=clean,
                    not_clean=len(answers) - clean, asked=len(inc.get("ring_hh", [])))
    return {"outcome": outcome, "round": rnd, "clean": clean, "not_clean": len(answers) - clean}


def reopened(e):
    inc = _inc(e)
    store.update_incident(inc["inc_id"], status="REOPENED", reopen_count=int(inc.get("reopen_count", 0)) + 1)
    if inc.get("reopen_count", 0) == 0:
        make_audio(inc["inc_id"], "reopened_v1", texts.REOPENED)
    for hh_id in inc.get("ring_hh", []):
        hh = store.get_household(hh_id)
        enrolled = store.is_enrolled(hh)
        if policy.check("workflow", "broadcast_warning", f'Household::"{hh_id}"', inc["inc_id"],
                        volunteer_approved=bool(inc.get("approved_by")), template_id="reopened_v1",
                        consent=enrolled, recipient_allowlisted=enrolled):
            _say(hh_id, inc["inc_id"], "reopened_v1", texts.REOPENED)


def closed(e):
    inc = _inc(e)
    clean = sum(1 for a in store.checkins(inc["inc_id"], int(inc["checkin_round"])) if a["clean"])
    store.update_incident(inc["inc_id"], status="CLOSED_AT_TAP", closed_ts=store.now_iso())
    for hh_id in inc.get("ring_hh", []):
        if store.is_enrolled(store.get_household(hh_id)):
            channel.send_text(hh_id, texts.CLOSED.format(n=clean))


def still_open(e):
    inc = _inc(e)
    store.update_incident(inc["inc_id"], status="STILL_OPEN")
    vol_id = inc.get("volunteer")
    if vol_id and store.is_enrolled(store.get_household(vol_id)):
        channel.send_text(vol_id, texts.STILL_OPEN_VOLUNTEER)


def _status(status: str):
    def step(e):
        store.update_incident(e["inc_id"], status=status)
        store.log_event("case", decision=status.lower(), inc_id=e["inc_id"])
    return step


# --- voice: one Polly file per incident and template, reused for every home -----------------------

_audio: dict[str, bytes] = {}


def _audio_key(inc_id: str, template: str) -> str:
    return f"audio/{inc_id}/{template}.mp3"


def make_audio(inc_id: str, template: str, text: str) -> None:
    """One Polly call per incident and template, before the fan-out; every home then reuses the MP3 from S3."""
    key = _audio_key(inc_id, template)
    _audio[key] = voice.speak(text)
    if os.environ.get("BUCKET"):
        boto3.client("s3").put_object(Bucket=os.environ["BUCKET"], Key=key, Body=_audio[key], ContentType="audio/mpeg")


def _say(hh_id: str, inc_id: str, template: str, text: str) -> None:
    """Text + Polly voice (the phone wall plays the same MP3 from S3)."""
    channel.send_text(hh_id, text)
    key = _audio_key(inc_id, template)
    if key not in _audio and os.environ.get("BUCKET"):
        try:
            _audio[key] = boto3.client("s3").get_object(Bucket=os.environ["BUCKET"], Key=key)["Body"].read()
        except Exception:
            log.warning("no stored audio for %s, synthesising", key)
    if key not in _audio:
        make_audio(inc_id, template, text)
    channel.send_voice(hh_id, _audio[key], audio_key=key)


STEPS = {
    "prepare": prepare, "ask_volunteer": ask_volunteer, "ring": ring, "warn_home": warn_home, "warned": warned,
    "notify_ward": notify_ward, "await_reply": await_reply, "handle_reply": handle_reply, "checkins": checkins,
    "evaluate": evaluate, "reopened": reopened, "closed": closed, "still_open": still_open,
    "unapproved": _status("UNAPPROVED"), "held": _status("HELD"), "no_reply": _status("NO_WARD_REPLY"),
}
