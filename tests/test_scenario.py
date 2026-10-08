from teesri import geo, scenario, store, tripwire

DIRTY = {"colour": "brown", "smell": True, "since_days": 2, "illness": [], "vulnerable": []}


def evaluate_new(before: set[str]) -> list[str]:
    """Moto has no streams: evaluate every report written since `before`, oldest first, like the Pipe would."""
    new = sorted((r for r in store.scan_prefix("RPT#") if r["PK"] not in before), key=lambda r: r["ts"])
    return [tripwire.evaluate(store.get_report(r["PK"][4:])) for r in new]


def test_demo_story_three_homes_212m_71h_and_all_23_warned(env):
    store.upsert_household("tg42", lat=18.9622, lon=72.8368, ward="B", channel="telegram", consent_ts="2026-10-08T00:00:00Z")
    scenario.seed()
    assert evaluate_new(set()) == ["none", "none"]  # A and B alone are not an alarm
    assert len(store.households_near(*scenario.ring_centre(), tripwire.RING_M)) == 23

    before = {r["PK"] for r in store.scan_prefix("RPT#")}
    store.put_report("tg42-1", store.get_household("tg42"), DIRTY, "nova")  # the phone's voice note
    assert evaluate_new(before) == ["incident"]
    [inc] = store.scan_prefix("INC#")
    assert inc["homes"] == {"tg42", "sim-A", "sim-B"}
    assert (inc["fired"]["homes"], inc["fired"]["spread_m"], round(inc["fired"]["span_h"])) == (3, 212, 71)
    assert geo.distance_m(float(inc["lat"]), float(inc["lon"]), *scenario.ring_centre()) < 1
    ring = {h["PK"][3:] for h in store.households_near(float(inc["lat"]), float(inc["lon"]), tripwire.RING_M)}
    assert len(ring) == 23 and len(ring - inc["homes"]) == 20  # "20 of 23 enrolled homes never complained"


def test_one_building_gives_tank_advice_and_reset_keeps_real_homes(env):
    store.upsert_household("tg42", lat=18.9622, lon=72.8368, ward="B", channel="telegram", consent_ts="2026-10-08T00:00:00Z")
    scenario.seed()
    before = {r["PK"] for r in store.scan_prefix("RPT#")}
    scenario.building()
    assert evaluate_new(before) == ["none", "none", "tank"]
    assert store.scan_prefix("INC#") == []
    scenario.reset()
    assert store.scan_prefix("HH#sim-") == [] and store.scan_prefix("RPT#") == [] and store.scan_prefix("FEED") == []
    assert store.is_enrolled(store.get_household("tg42"))
