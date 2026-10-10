"""The console's API (served by the same Function URL).

GET  /api/state   read-only snapshot for the map, phone wall, Safety tab, inbox and timeline. Public, so it never
                  shows Telegram ids (real homes become "phone-1", "phone-2", … in the order they joined), and shows a
                  real home's location (rounded to ~100 m) only while it is in the current incident (a reporter, or
                  inside the ring, whose area is public anyway); otherwise lat/lon are null and the map leaves it out.
GET  /api/audio   ?key=audio/<inc>/<template>.mp3 -> short-lived S3 link (the phone wall plays warnings)
POST /api/action  demo controls; needs the x-console-token header (SSM /teesri/console-token)
"""
import hmac
import json
import os
import re

import boto3

from teesri import scenario, store, telegram

_AUDIO_KEY = re.compile(r"^audio/inc-[0-9a-f-]+/[a-z0-9_]+\.mp3$")


def console_token() -> str:
    return telegram._param(os.environ["CONSOLE_TOKEN_PARAM"])


# --- state ---------------------------------------------------------------------------------------

def state() -> dict:
    items = store.scan_prefix("")
    profiles = {i["PK"][3:]: i for i in items if i["PK"].startswith("HH#") and i["SK"] == "PROFILE"}
    real_ids = sorted((h for h in profiles if not h.startswith("sim-")), key=lambda h: (str(profiles[h].get("consent_ts") or "~"), h))
    alias = {h: f"phone-{n}" for n, h in enumerate(real_ids, 1)}

    def public(hh_id: str) -> str:
        return alias.get(hh_id, hh_id)

    def mask(text: str) -> str:
        for real, a in alias.items():
            text = text.replace(real, a)
        return text

    incs = sorted((i for i in items if i["PK"].startswith("INC#") and i["SK"] == "META"), key=lambda i: i["created_ts"])
    inc = incs[-1] if incs else None
    inc_pk = inc["PK"] if inc else None
    reported = {r["hh_id"] for r in items if r["PK"].startswith("RPT#") and r.get("colour") != "clear"}
    ring_hh, members = set(inc.get("ring_hh", [])) if inc else set(), set(inc["homes"]) if inc else set()
    chk = {}
    if inc:
        rnd = int(inc.get("checkin_round", 0))
        chk = {i["hh_id"]: bool(i["clean"]) for i in items if i["PK"] == inc_pk and i["SK"].startswith(f"CHK#{rnd:02d}#")}
    msgs: dict[str, list] = {}
    for i in items:
        if i["PK"].startswith("HH#sim-") and i["SK"].startswith("MSG#"):
            msgs.setdefault(i["PK"][3:], []).append(i)

    homes = []
    for hh_id, h in profiles.items():
        if "lat" not in h or not store.is_enrolled(h):
            continue
        sim = hh_id.startswith("sim-")
        lat, lon = float(h["lat"]), float(h["lon"])
        shown = sim or hh_id in ring_hh or hh_id in members
        last = sorted(msgs.get(hh_id, []), key=lambda m: m["SK"])[-4:]
        homes.append({
            "id": public(hh_id), "sim": sim,
            "label": h.get("label") or ("My phone (real)" if public(hh_id) == "phone-1" else f"Real phone {public(hh_id)[6:]}"),
            "lat": (lat if sim else round(lat, 3)) if shown else None, "lon": (lon if sim else round(lon, 3)) if shown else None,
            "reported": hh_id in reported, "member": hh_id in members, "in_ring": hh_id in ring_hh,
            "warned": bool(inc) and hh_id in ring_hh and inc.get("warned_ts") is not None,
            "checkin": chk.get(hh_id),
            "messages": [{"kind": m.get("kind"), "text": m.get("text", ""), "audio_key": m.get("audio_key", ""),
                          "buttons": [[{"label": b[0], "data": b[1]} for b in row] for row in m.get("buttons", [])],
                          "ts": m["SK"][4:24]} for m in last],
        })

    out = {"homes": sorted(homes, key=lambda h: (not h["sim"], h["id"])), "incident": None, "events": [], "mail": None,
           "feed": [{k: (mask(v) if isinstance(v, str) else v) for k, v in f.items() if k not in ("PK", "SK")}
                    for f in sorted((i for i in items if i["PK"] == "FEED"), key=lambda f: f["SK"])[-30:]],
           "volunteer": public(store.get_config("volunteer").get("hh_id", "")),
           "quiet": bool(store.get_config("demo").get("quiet"))}
    if inc:
        out["incident"] = {
            "inc_id": inc["inc_id"], "status": inc.get("status"), "lat": float(inc["lat"]), "lon": float(inc["lon"]),
            "ring_m": int(inc["ring_m"]), "fired": inc["fired"], "ring_pop": inc["ring_pop"],
            "homes": len(members), "ring_homes": len(ring_hh), "brief_hi": inc.get("brief_hi", ""),
            "brief_mode": inc.get("brief_mode", ""), "claim": inc.get("claim", ""),
            "model": "Gemma 4 on our EC2 instance" if os.environ.get("MODEL_BACKEND") == "selfhost" else "Amazon Nova",
            "reopen_count": int(inc.get("reopen_count", 0)), "checkin_round": int(inc.get("checkin_round", 0)),
            "created_ts": inc["created_ts"],
        }
        out["events"] = [{"ts": e["ts"], "actor": e.get("actor"), "action": e.get("action"), "decision": e.get("decision"),
                          "policy": e.get("policy", ""), "reason": e.get("reason", ""), "resource": mask(e.get("resource", ""))}
                         for e in sorted((i for i in items if i["PK"] == inc_pk and i["SK"].startswith("EVT#")),
                                         key=lambda e: e["SK"])]
        mails = sorted((i for i in items if i["PK"] == inc_pk and i["SK"].startswith("MAIL#")), key=lambda m: m["SK"])
        if mails:
            out["mail"] = {k: mails[-1][k] for k in ("to", "subject", "body", "via", "ts")}
    return out


# --- audio ---------------------------------------------------------------------------------------

def audio_url(key: str) -> str | None:
    if not _AUDIO_KEY.match(key or ""):
        return None
    return boto3.client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": os.environ["BUCKET"], "Key": key}, ExpiresIn=300)


# --- demo controls -------------------------------------------------------------------------------

ACTIONS = {
    "reset": lambda a: scenario.reset(),
    "reset_all": lambda a: scenario.reset(mine=True),
    "seed": lambda a: scenario.seed(),
    "building": lambda a: scenario.building(),
    "stand_in": lambda a: scenario.third_stand_in(),
    "volunteer": lambda a: scenario.set_volunteer(a.get("who", "phone")),
    "approve": lambda a: scenario.approve(True),
    "hold": lambda a: scenario.approve(False),
    "ward_reply": lambda a: scenario.ward_reply(a.get("text") or "Resolved"),
    "answer": lambda a: scenario.answer(str(a["home"]), bool(a["clean"])),
    "quiet": lambda a: scenario.set_quiet(bool(a.get("on"))),
    "anchor": lambda a: scenario.set_anchor(str(a.get("at", "phone"))),
}


def action(headers: dict, body: str) -> tuple[int, dict]:
    if not hmac.compare_digest(headers.get("x-console-token", ""), console_token()):
        return 401, {"error": "console token required"}
    a = json.loads(body or "{}")
    if a.get("action") not in ACTIONS:
        return 400, {"error": "unknown action"}
    if a["action"] == "answer" and not re.fullmatch(r"[A-V]|bldg-[1-3]|me|vol", str(a.get("home", ""))):
        return 400, {"error": "simulated homes only"}
    return 200, {"result": ACTIONS[a["action"]](a)}

