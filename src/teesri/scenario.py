"""The demo scenario. Simulated homes go through the same code as real residents: they are households whose id
starts with `sim-`, so the channel adapter puts their messages on the phone wall instead of Telegram.
On screen they are always labelled "Simulated home A–V".

Layout around the anchor (the real phone's home pin, or the Dongri point if no phone is enrolled):
- A and B: the two neighbours who already reported (demo clock: ~71 h and 20 h ago). A–B is 212 m.
- C–V: 20 more enrolled homes in the ring who never complain (they still get the warning).
- One building ~600 m north (flats 1–3): three reports there show the one-building rule (tank advice, no alarm).
The phone's own voice note is the third report: 3 homes · 212 m · 71 h.
"""
import math
from datetime import datetime, timedelta, timezone

from teesri import channel, geo, store, texts, tripwire, workflow

DONGRI = (18.9622, 72.8368)  # B ward, OpenStreetMap
M_PER_DEG = 6_371_000 * math.pi / 180
RING_HOMES = list("ABCDEFGHIJKLMNOPQRSTUV")  # 22 simulated homes; + the real phone = 23 enrolled
BUILDING = [("bldg-1", 0, 0), ("bldg-2", 8, 5), ("bldg-3", 4, 12)]  # metres from the building point
BUILDING_NORTH_M = 600

# home: (north_m, east_m from the anchor, hours before now, transcript, fields). Transcripts are written for the demo.
PRIOR = {
    "A": (-50, -106, 70.75, "नल से भूरा पानी आ रहा है और बहुत बदबू है, तीन दिन से।",
          {"colour": "brown", "smell": True, "since_days": 3, "illness": [], "vulnerable": []}),
    "B": (-50, 106, 20, "पानी पीला है, बदबू आती है। बच्चे को कल से दस्त हैं।",
          {"colour": "yellow", "smell": True, "since_days": 1, "illness": ["diarrhoea"], "vulnerable": ["child"]}),
}
DIRTY = {"colour": "brown", "smell": True, "since_days": 2, "illness": [], "vulnerable": []}


def _offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / M_PER_DEG, lon + east_m / (M_PER_DEG * math.cos(math.radians(lat)))


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def real_homes() -> list[dict]:
    return [h for h in store.scan_prefix("HH#tg") if h["SK"] == "PROFILE" and store.is_enrolled(h)]


def anchor() -> tuple[float, float]:
    homes = real_homes()
    if homes and store.get_config("anchor").get("at") != "dongri":
        return float(homes[0]["lat"]), float(homes[0]["lon"])
    return DONGRI


def set_anchor(at: str) -> str:
    """Runs without the phone: "dongri" puts the demo at the Dongri pin wherever the phone's home is ("phone" = default)."""
    at = "dongri" if at == "dongri" else "phone"
    store.set_config("anchor", at=at)
    return at


def ring_centre() -> tuple[float, float]:
    """Centre of the anchor, A and B: where the incident ring will be."""
    lat, lon = anchor()
    return _offset(lat, lon, sum(p[0] for p in PRIOR.values()) / 3, sum(p[1] for p in PRIOR.values()) / 3)


def reset(mine: bool = False) -> dict:
    """Stops running cases, then removes simulated homes (their messages and reports), all incidents, the feed.
    Real homes stay enrolled. mine=True also removes real homes' reports, for a clean recording."""
    prefixes = ("HH#sim-", "RPT#sim-", "DRAFT#sim-", "INC#", "ONCE#", "FEED", "TOK#", "CFG#volunteer") + (("RPT#tg", "DRAFT#tg") if mine else ())
    stopped = workflow.stop_all_cases()
    keys = [(i["PK"], i["SK"]) for p in prefixes for i in store.scan_prefix(p, keys_only=True)]
    with store.table().batch_writer() as b:
        for pk, sk in keys:
            b.delete_item(Key={"PK": pk, "SK": sk})
    return {"deleted": len(keys), "cases_stopped": stopped}


def seed() -> dict:
    """Enrols the 22 ring homes and the building, then files A's and B's reports on the demo clock."""
    lat0, lon0 = anchor()
    clat, clon = ring_centre()
    now = store.now_iso()

    def enrol(hh_id: str, lat: float, lon: float, label: str) -> None:
        store.upsert_household(hh_id, lat=lat, lon=lon, ward="B", channel="sim", consent_ts=now,
                               is_simulated=True, label=label)

    spiral = iter(range(len(RING_HOMES)))
    for letter in RING_HOMES:
        if letter in PRIOR:
            lat, lon = _offset(lat0, lon0, *PRIOR[letter][:2])
        else:  # golden-angle spiral, 30–200 m from the ring centre
            k = next(spiral)
            r, th = 30 + 170 * math.sqrt((k + 0.5) / (len(RING_HOMES) - len(PRIOR))), math.radians(k * 137.508)
            lat, lon = _offset(clat, clon, r * math.cos(th), r * math.sin(th))
        enrol(f"sim-{letter}", lat, lon, f"Simulated home {letter}")
    blat, blon = _offset(lat0, lon0, BUILDING_NORTH_M, 0)
    for name, n, e in BUILDING:
        enrol(f"sim-{name}", *_offset(blat, blon, n, e), f"Simulated building, flat {name[-1]}")

    set_volunteer("phone" if real_homes() else "sim")
    for letter, (_, _, hours, transcript, fields) in PRIOR.items():
        file_report(f"sim-{letter}", fields, transcript, ts=_ago(hours))
    return {"ring_homes": len(RING_HOMES), "building_homes": len(BUILDING), "prior_reports": list(PRIOR),
            "volunteer": store.get_config("volunteer").get("hh_id")}


def set_volunteer(who: str) -> str:
    """"phone": your phone gets the volunteer card ("demo: my phone plays the volunteer").
    "sim": a simulated volunteer on the phone wall, 300 m away (outside the ring), approved from the console/CLI."""
    if who == "phone" and real_homes():
        hh_id = real_homes()[0]["PK"].removeprefix("HH#")
    else:
        hh_id = "sim-vol"
        store.upsert_household(hh_id, **dict(zip(("lat", "lon"), _offset(*anchor(), -300, 0))), ward="B", channel="sim",
                               consent_ts=store.now_iso(), is_simulated=True, label="Simulated volunteer")
    store.set_config("volunteer", hh_id=hh_id)
    return hh_id


def set_quiet(on: bool) -> bool:
    """Rehearsals: hold back messages to real phones (the Safety tab still shows every decision)."""
    store.set_config("demo", quiet=on)
    return on


def current_incident() -> dict | None:
    open_incs = [i for i in store.scan_prefix("INC#") if i["SK"] == "META" and i.get("status") != "CLOSED_AT_TAP"]
    return max(open_incs, key=lambda i: i["created_ts"], default=None)


def approve(yes: bool = True) -> str:
    """The simulated volunteer taps (only when the volunteer is simulated; a real volunteer taps on Telegram)."""
    inc, vol = current_incident(), store.get_config("volunteer").get("hh_id", "")
    if not inc or not vol.startswith("sim-"):
        return "no open incident, or the volunteer is a real phone"
    return workflow.approve(vol, inc.get("approve_tok", ""), yes)


def ward_reply(text: str = "Resolved") -> bool:
    inc = current_incident()
    return bool(inc) and workflow.ward_reply(inc["inc_id"], text)


def answer(home: str, clean: bool) -> str:
    """A simulated home answers "पानी साफ़ है?". Real homes answer on their own phones."""
    inc = current_incident()
    if not inc:
        return "no open incident"
    return workflow.answer_checkin(f"sim-{home}", inc.get("checkin_tok", ""), clean)


def file_report(hh_id: str, fields: dict, transcript: str, ts: str | None = None) -> str:
    """A simulated home's report: same table write as a real one (so the stream feeds the tripwire) + receipt."""
    hh = store.get_household(hh_id)
    rpt_id = f"{hh_id}-{store.new_id()}"
    store.put_report(rpt_id, hh, fields, "simulated", transcript, ts=ts)
    channel.send_text(hh_id, texts.receipt(fields))
    return rpt_id


def building() -> list[str]:
    """Three flats in one building report: the tripwire answers with tank advice, not an alarm."""
    return [file_report(f"sim-{name}", DIRTY, "टंकी का पानी गंदा आ रहा है।", ts=_ago(3 - i))
            for i, (name, _, _) in enumerate(BUILDING)]


def third_stand_in() -> str:
    """For testing without the phone: a simulated stand-in next to the anchor files the third report."""
    lat, lon = _offset(*anchor(), 5, 0)
    store.upsert_household("sim-me", lat=lat, lon=lon, ward="B", channel="sim", consent_ts=store.now_iso(),
                           is_simulated=True, label="Simulated stand-in for my phone")
    return file_report("sim-me", {**DIRTY, "since_days": 2}, "पानी गंदा है, बदबू आ रही है।")


def status() -> dict:
    clat, clon = ring_centre()
    incs = [i for i in store.scan_prefix("INC#") if i.get("SK") == "META"]  # not its events, check-ins or mail
    return {
        "enrolled_in_ring": len(store.households_near(clat, clon, tripwire.RING_M)),
        "reports": sorted(r["PK"][4:] for r in store.scan_prefix("RPT#")),
        "incidents": [{k: i.get(k) for k in ("inc_id", "status", "reopen_count", "fired", "ring_pop")} | {"homes": sorted(i["homes"])}
                      for i in incs],
        "feed": [f.get("decision") or f.get("kind") for f in store.scan_prefix("FEED")],
    }
