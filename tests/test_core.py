import math

from teesri import extract, geo, population, texts


def test_geohash_known_value():
    assert geo.geohash(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_cells_around_cover_250m_in_every_direction():
    lat, lon = 18.9622, 72.8368  # Dongri, B ward, Mumbai (OpenStreetMap)
    cells = geo.cells_around(lat, lon)
    assert len(cells) == 9
    for dlat, dlon in [(0.00225, 0), (-0.00225, 0), (0, 0.0024), (0, -0.0024)]:  # ~250 m
        assert geo.geohash(lat + dlat, lon + dlon) in cells


def test_distance_m():
    assert 240 < geo.distance_m(18.9622, 72.8368, 18.96445, 72.8368) < 260


def test_validate_keeps_only_allowed_values():
    f = extract.validate({"colour": "brown", "smell": "yes", "since_days": 3,
                          "illness": ["diarrhoea", "made_up"], "vulnerable": ["child"]})
    assert f == {"colour": "brown", "smell": True, "since_days": 3, "illness": ["diarrhoea"], "vulnerable": ["child"]}


def test_validate_rejects_unclassifiable():
    assert extract.validate({"colour": "not_said", "smell": "not_said", "since_days": -1}) is None


def test_validate_drops_bad_numbers():
    f = extract.validate({"colour": "yellow", "smell": "not_said", "since_days": -1})
    assert f["since_days"] is None and f["smell"] is None


def test_keywords_read_the_common_hindi_complaint():
    f = extract.keywords("पानी पीला है और बदबू आ रही है, दो दिन से ।")
    assert (f["colour"], f["smell"], f["since_days"], f["illness"]) == ("yellow", True, 2, [])
    f = extract.keywords("मटमैला पानी आ रहा है, बच्चे को दस्त और उल्टी हो रही है, कल से")
    assert (f["colour"], f["smell"], f["since_days"]) == ("brown", None, 1)
    assert f["illness"] == ["diarrhoea", "vomiting"] and f["vulnerable"] == ["child"]
    f = extract.keywords("बदबू आ रही है एक हफ़्ते से, पेट में दर्द है")  # nukta spelling, no colour said
    assert (f["colour"], f["smell"], f["since_days"], f["illness"]) == (None, True, 7, ["stomach_pain"])
    assert extract.keywords("काला पानी, 2-3 दिन से")["since_days"] == 3


def test_keywords_never_guess():
    assert extract.keywords("पानी गंदा है ।") is None          # "dirty" names no colour or smell: ask with buttons
    assert extract.keywords("") is None
    f = extract.keywords("पानी भूरा है लेकिन बदबू नहीं है")
    assert (f["colour"], f["smell"], f["since_days"]) == ("brown", False, None)
    assert extract.keywords("पानी काला नहीं है") is None        # a denied colour is not a colour
    assert extract.keywords("घर में किसी को पीलिया है, पानी पीला है")["illness"] == ["jaundice"]  # पीलिया is not पीला
    assert extract.keywords("बदबू है, बच्चे ठीक हैं")["vulnerable"] == []  # a child named without illness is not marked


def test_keywords_read_typed_hinglish_and_english():
    f = extract.keywords("paani peela hai aur badbu aa rahi hai, 2 din se")
    assert (f["colour"], f["smell"], f["since_days"]) == ("yellow", True, 2)
    f = extract.keywords("Brown water, no smell, since 3 days")
    assert (f["colour"], f["smell"], f["since_days"]) == ("brown", False, 3)
    f = extract.keywords("kala paani aa raha hai, bacche ko dast hai")
    assert (f["colour"], f["illness"], f["vulnerable"]) == ("black", ["diarrhoea"], ["child"])
    assert extract.keywords("hello") is None


def test_health_claims_must_be_in_the_words():
    model = {"colour": "yellow", "smell": True, "since_days": 2, "illness": ["diarrhoea", "vomiting"], "vulnerable": ["child", "elderly"]}
    f = extract.ground(dict(model), "पानी पीला है, बदबू आ रही है, 2 दिन से ।")  # a model that invents illness
    assert (f["colour"], f["illness"], f["vulnerable"]) == ("yellow", [], [])
    f = extract.ground(dict(model), "पानी पीला है, बच्चे को उल्टी हो रही है")
    assert (f["illness"], f["vulnerable"]) == (["vomiting"], ["child"])
    assert extract.ground({**model, "illness": ["stomach_pain"]}, "पीने के बाद पेट खराब है")["illness"] == ["stomach_pain"]


def test_sounds_like_complaint():
    assert extract.sounds_like_complaint("पानी गंदा है")
    assert extract.sounds_like_complaint("paani bahut ganda aa raha hai")
    assert not extract.sounds_like_complaint("पानी गंदा नहीं है")
    assert not extract.sounds_like_complaint("hello")


def test_is_dirty():
    assert extract.is_dirty({"colour": "black"})
    assert extract.is_dirty({"colour": "clear", "smell": True})
    assert not extract.is_dirty({"colour": "clear", "smell": False, "illness": []})


def test_receipt_text():
    assert texts.receipt({"colour": "yellow", "smell": True, "since_days": 3}) == \
        "आपकी शिकायत मिल गई: पीला, बदबूदार पानी, 3 दिन से। हम आस-पास की शिकायतें देख रहे हैं।"
    assert texts.receipt({"colour": None, "smell": True, "since_days": None}).startswith("आपकी शिकायत मिल गई: बदबूदार पानी।")


def _uniform_grid(lat, lon, people_per_cell=100.0, half_cells=15):
    m = 6_371_000 * math.pi / 180
    cells = [[lat + r * 100 / m, lon + c * 100 / (m * math.cos(math.radians(lat))), people_per_cell]
             for r in range(-half_cells, half_cells + 1) for c in range(-half_cells, half_cells + 1)]
    lats, lons = [x[0] for x in cells], [x[1] for x in cells]
    return {"cell_m": 100, "covered": [min(lats), min(lons), max(lats), max(lons)], "cells": cells}


def test_ring_population_counts_the_part_of_each_cell_inside_the_ring():
    grid = _uniform_grid(18.9622, 72.8368)
    expected = math.pi * 250**2 / 100**2 * 100  # ~1,963 people
    assert abs(population.ring_population(18.9622, 72.8368, 250, grid) - expected) / expected < 0.03


def test_missing_population_data_is_no_data_never_zero():
    grid = _uniform_grid(18.9622, 72.8368)
    assert population.ring_population(19.10, 72.85, 250, grid) is None   # ring outside the grid
    assert population.ring_population(18.9622, 72.8368, 250, {}) is None  # no grid at all
    assert population.label(None) == "NO DATA" and population.label(0) == "~0"
    assert population.label(12_345) == "~12,300"


def test_real_dongri_grid_gives_a_ring_count():
    people = population.ring_population(18.9622, 72.8368, 250)
    assert people is not None and people > 1000
