import itertools
import math

from teesri import population, store, texts, tripwire

LAT, LON = 18.9622, 72.8368  # Dongri, B ward, Mumbai (OpenStreetMap)
M_PER_DEG = 6_371_000 * math.pi / 180
_n = itertools.count()


def report(home, north_m=0.0, east_m=0.0, h=0.0, dirty=True):
    """A report from simulated home `home`, `north_m`/`east_m` from the Dongri point, `h` hours after 10:00."""
    lat = LAT + north_m / M_PER_DEG
    lon = LON + east_m / (M_PER_DEG * math.cos(math.radians(LAT)))
    rid = f"sim-{home}-{next(_n)}"
    fields = {"colour": "brown", "smell": True} if dirty else {"colour": "clear", "smell": False}
    store.put_report(rid, {"PK": f"HH#sim-{home}", "lat": lat, "lon": lon}, fields, "buttons",
                     ts=tripwire._shift("2026-10-08T10:00:00Z", h))
    return store.get_report(rid)


def incidents():
    return [i for i in store.table().scan()["Items"] if i["PK"].startswith("INC#")]


def record(rpt):
    return {"eventName": "INSERT", "dynamodb": {"Keys": {"PK": {"S": rpt["PK"]}, "SK": {"S": "META"}}}}


def test_three_homes_212m_71h_fire_one_incident(env):
    a, b = report("A", 0, 0, h=0), report("B", 0, 212, h=30)
    assert tripwire.evaluate(a) == "none" and tripwire.evaluate(b) == "none"
    c = report("C", 100, 106, h=71)
    tripwire.main([record(c)], None)
    tripwire.main([record(c)], None)  # the stream re-delivers: still one incident
    [inc] = incidents()
    assert inc["fired"] == {"homes": 3, "spread_m": 212, "span_h": 71}
    assert inc["homes"] == {"sim-A", "sim-B", "sim-C"} and inc["status"] == "OPEN"
    assert inc["ring_pop"] > 1000  # GHS-POP residents inside the 250 m ring in Dongri
    assert all(store.get_report(r["PK"][4:])["inc_id"] == inc["inc_id"] for r in (a, b, c))


def test_one_home_300m_away_is_not_a_cluster(env):
    report("A", 0, 0)
    report("B", 0, 50)
    assert tripwire.evaluate(report("C", 300, 25, h=1)) == "none"
    assert incidents() == []


def test_reports_spanning_73h_do_not_fire(env):
    report("A", 0, 0, h=0)
    report("B", 50, 0, h=60)
    assert tripwire.evaluate(report("C", 0, 50, h=73)) == "none"


def test_same_home_three_times_does_not_fire(env):
    report("A", 0, 0, h=0)
    report("A", 0, 0, h=5)
    assert tripwire.evaluate(report("A", 0, 0, h=9)) == "none"


def test_clear_water_never_counts(env):
    report("A", 0, 0)
    report("B", 0, 40, dirty=False)
    assert tripwire.evaluate(report("C", 40, 0, h=1)) == "none"


def test_one_building_gets_tank_advice_not_an_alarm(env):
    report("A", 0, 0)
    report("B", 10, 5)
    assert tripwire.evaluate(report("C", 5, 15, h=2)) == "tank"
    assert incidents() == []
    advice = texts.TANK_ADVICE.format(n=3)
    assert sorted(hh for hh, text in env if text == advice) == ["sim-A", "sim-B", "sim-C"]
    env.clear()
    assert tripwire.evaluate(report("D", 12, 12, h=3)) == "tank"
    assert [hh for hh, _ in env] == ["sim-D"]  # the first three are not told twice


def test_fourth_report_inside_the_ring_joins_it(env):
    report("A", 0, 0)
    report("B", 0, 150)
    tripwire.evaluate(report("C", 120, 60, h=2))
    assert tripwire.evaluate(report("D", -80, 90, h=5)) == "join"
    [inc] = incidents()
    assert inc["homes"] == {"sim-A", "sim-B", "sim-C", "sim-D"}


def test_two_simultaneous_third_reports_make_exactly_one_incident(env, monkeypatch):
    report("A", 0, 0)
    report("B", 0, 150)
    c, d = report("C", 120, 60, h=10), report("D", -80, 90, h=11)
    stale = tripwire.decide(d)                  # D looked before C's incident was written...
    assert stale[0] == "incident" and tripwire.evaluate(c) == "incident"
    real, first = tripwire.decide, iter([stale])
    monkeypatch.setattr(tripwire, "decide", lambda r: next(first, None) or real(r))
    assert tripwire.evaluate(d) == "join"       # ...so its write is refused, and on the second look it joins
    [inc] = incidents()
    assert inc["homes"] == {"sim-A", "sim-B", "sim-C", "sim-D"}


def test_incident_without_population_data_says_no_data(env, monkeypatch):
    monkeypatch.setattr(population, "_grid", lambda: None)
    report("A", 0, 0)
    report("B", 0, 150)
    tripwire.evaluate(report("C", 120, 60, h=2))
    [inc] = incidents()
    assert inc["ring_pop"] == "NO DATA"
