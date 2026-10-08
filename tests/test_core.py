from teesri import extract, geo, texts


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


def test_is_dirty():
    assert extract.is_dirty({"colour": "black"})
    assert extract.is_dirty({"colour": "clear", "smell": True})
    assert not extract.is_dirty({"colour": "clear", "smell": False, "illness": []})


def test_receipt_text():
    assert texts.receipt({"colour": "yellow", "smell": True, "since_days": 3}) == \
        "आपकी शिकायत मिल गई: पीला, बदबूदार पानी, 3 दिन से। हम आस-पास की शिकायतें देख रहे हैं।"
    assert texts.receipt({"colour": None, "smell": True, "since_days": None}).startswith("आपकी शिकायत मिल गई: बदबूदार पानी।")
