"""The tripwire: a fixed rule in code, no model. It runs on every new report (DynamoDB Streams -> EventBridge Pipes).

Fire when >= 3 different homes report dirty water within 72 h and every pair of them is within 250 m.
If they are all within 30 m of each other (one building, one tank) there is no area alarm: those homes get
tank advice instead. A dirty report within 250 m of an open incident's centre joins that incident.
A report belongs to at most one incident (claimed in the same transaction that creates the incident).
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from teesri import channel, extract, geo, store, texts, voice

log = logging.getLogger()
log.setLevel(logging.INFO)

MIN_HOMES = 3
RING_M = 250
WINDOW_H = 72
BUILDING_M = 30
CLOSED = {"CLOSED_AT_TAP"}
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def main(event, context):
    """Pipes delivers a batch of stream records (a JSON list). Re-delivered records are harmless."""
    records = event if isinstance(event, list) else event.get("Records", [])
    for rec in records:
        rpt = store.get_report(rec["dynamodb"]["Keys"]["PK"]["S"].removeprefix("RPT#"))
        if rpt:
            log.info("tripwire %s: %s", rpt["PK"], evaluate(rpt))


def evaluate(rpt: dict, retry: bool = True) -> str:
    decision, d = decide(rpt)
    try:
        apply(rpt, decision, d)
    except store.Conflict:
        # Someone else claimed one of these reports first (two simultaneous third reports). Look again once:
        # this time the other incident exists, so this report joins it.
        if not retry:
            raise
        return evaluate(store.get_report(_rid(rpt)), retry=False)
    return decision


def decide(rpt: dict) -> tuple[str, dict]:
    """Reads only. One of: already, clean, join, none, tank, incident."""
    if rpt.get("inc_id"):
        return "already", {"inc_id": rpt["inc_id"]}
    if not extract.is_dirty(rpt):
        return "clean", {}
    lat, lon = float(rpt["lat"]), float(rpt["lon"])
    open_incs = [i for i in store.incidents_near(lat, lon) if i.get("status") not in CLOSED and _dist(i, rpt) <= RING_M]
    if open_incs:
        return "join", {"inc": min(open_incs, key=lambda i: _dist(i, rpt))}
    since = _shift(rpt["ts"], -WINDOW_H)
    others = [r for r in store.reports_near(lat, lon, since)
              if r["PK"] != rpt["PK"] and r["ts"] <= rpt["ts"] and not r.get("inc_id") and extract.is_dirty(r)]
    members = find_cluster(rpt, others)
    if len(members) < MIN_HOMES:
        return "none", {"homes": len(members)}
    s = stats(members)
    return ("tank" if s["spread_m"] <= BUILDING_M else "incident"), {"members": members, **s}


def apply(rpt: dict, decision: str, d: dict) -> None:
    if decision == "join":
        inc_id = d["inc"]["inc_id"]
        store.join_incident(inc_id, _rid(rpt), rpt["hh_id"])
        store.log_event("tripwire", decision="joined", inc_id=inc_id, rpt_id=_rid(rpt))
    elif decision == "incident":
        inc = new_incident(rpt, d)
        store.create_incident(inc, sorted(inc["report_ids"]))
        store.log_event("tripwire", decision="incident", inc_id=inc["inc_id"], **inc["fired"])
    elif decision == "tank":
        advise_tank(d["members"])
        store.log_event("tripwire", decision="one_building", rpt_id=_rid(rpt), homes=d["homes"], spread_m=d["spread_m"])


def find_cluster(trigger: dict, others: list[dict]) -> list[dict]:
    """The trigger plus one report per other home (its latest) within RING_M of it, then drop homes until every
    pair is within RING_M. Drop order: the home in the most too-far pairs, then the one farthest from the trigger."""
    latest: dict[str, dict] = {}
    for r in others:
        if r["hh_id"] != trigger["hh_id"] and _dist(r, trigger) <= RING_M:
            if r["hh_id"] not in latest or r["ts"] > latest[r["hh_id"]]["ts"]:
                latest[r["hh_id"]] = r
    members = [trigger, *sorted(latest.values(), key=lambda r: r["hh_id"])]
    while True:
        too_far = {r["hh_id"]: sum(_dist(r, o) > RING_M for o in members) for r in members[1:]}
        worst = max(members[1:], key=lambda r: (too_far[r["hh_id"]], _dist(r, trigger)), default=None)
        if worst is None or too_far[worst["hh_id"]] == 0:
            return members
        members.remove(worst)


def stats(members: list[dict]) -> dict:
    ts = sorted(r["ts"] for r in members)
    return {
        "lat": sum(float(r["lat"]) for r in members) / len(members),
        "lon": sum(float(r["lon"]) for r in members) / len(members),
        "homes": len(members),
        "spread_m": round(max(_dist(a, b) for a in members for b in members)),
        "span_h": round((_parse(ts[-1]) - _parse(ts[0])).total_seconds() / 3600, 1),
    }


def new_incident(trigger: dict, d: dict) -> dict:
    # Named after its earliest report, so the id is stable; it also names the Step Functions execution later.
    anchor = min(d["members"], key=lambda r: (r["ts"], r["PK"]))
    inc_id = f"inc-{anchor['ts'][:10].replace('-', '')}-{hashlib.sha1(anchor['PK'].encode()).hexdigest()[:6]}"
    now = store.now_iso()
    return {
        "inc_id": inc_id, "status": "OPEN", "created_ts": now, "updated_ts": now,
        "lat": d["lat"], "lon": d["lon"], "ring_m": RING_M,
        "homes": {r["hh_id"] for r in d["members"]},
        "report_ids": {_rid(r) for r in d["members"]},
        "trigger_rpt": _rid(trigger),
        "fired": {"homes": d["homes"], "spread_m": d["spread_m"], "span_h": d["span_h"]},  # "3 homes · 212 m · 71 h"
        "GSI1PK": f"IGH6#{geo.geohash(d['lat'], d['lon'])}", "GSI1SK": now,
    }


def advise_tank(members: list[dict]) -> None:
    text = texts.TANK_ADVICE.format(n=len(members))
    for r in members:
        if store.once_per(f"tank#{r['hh_id']}", WINDOW_H * 3600):
            _send(r["hh_id"], text)


def _send(hh_id: str, text: str) -> None:
    try:
        channel.send_text(hh_id, text)
        if hh_id.startswith("tg"):
            channel.send_voice(hh_id, voice.speak(text))
    except Exception:
        log.exception("could not message %s", hh_id)  # one unreachable phone must not stop the others


def _rid(rpt: dict) -> str:
    return rpt["PK"].removeprefix("RPT#")


def _dist(a: dict, b: dict) -> float:
    return geo.distance_m(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, _FMT).replace(tzinfo=timezone.utc)


def _shift(ts: str, hours: float) -> str:
    return (_parse(ts) + timedelta(hours=hours)).strftime(_FMT)
