import json

from teesri import api, scenario, store, tripwire


def test_public_state_hides_telegram_ids_and_rounds_real_locations(env, monkeypatch):
    store.upsert_household("tg5366659078", lat=18.962234, lon=72.836811, ward="B", channel="telegram", consent_ts="x")
    scenario.seed()
    store.put_report("tg5366659078-9", store.get_household("tg5366659078"),
                     {"colour": "brown", "smell": True, "since_days": 1}, "nova")
    for r in sorted(store.scan_prefix("RPT#"), key=lambda r: r["ts"]):
        tripwire.evaluate(store.get_report(r["PK"][4:]))
    s = api.state()
    text = json.dumps(s, default=str)
    assert "5366659078" not in text
    me = next(h for h in s["homes"] if h["id"] == "phone-1")
    assert (me["lat"], me["lon"]) == (18.962, 72.837) and me["member"]
    assert s["incident"]["fired"]["homes"] == 3 and len(s["homes"]) >= 23


def test_demo_controls_need_the_token_and_only_answer_for_simulated_homes(env, monkeypatch):
    monkeypatch.setattr(api, "console_token", lambda: "t0ken")
    assert api.action({}, json.dumps({"action": "seed"}))[0] == 401
    assert api.action({"x-console-token": "nope"}, json.dumps({"action": "seed"}))[0] == 401
    assert api.action({"x-console-token": "t0ken"}, json.dumps({"action": "drop_table"}))[0] == 400
    assert api.action({"x-console-token": "t0ken"}, json.dumps({"action": "answer", "home": "tg5366659078", "clean": True}))[0] == 400
    assert api.action({"x-console-token": "t0ken"}, json.dumps({"action": "seed"}))[0] == 200
