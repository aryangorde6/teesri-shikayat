"""Geohash cells and distances (pure Python, no deps)."""
import math

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"
# Size of one precision-6 cell (15 lat bits, 15 lon bits): ~610 m x ~1.1 km near Mumbai.
_DLAT, _DLON = 180 / 2**15, 360 / 2**15


def geohash(lat: float, lon: float, precision: int = 6) -> str:
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    out, ch, bits, even = [], 0, 0, True
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch, rng[0] = ch << 1 | 1, mid
        else:
            ch, rng[1] = ch << 1, mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_B32[ch])
            ch, bits = 0, 0
    return "".join(out)


def cells_around(lat: float, lon: float) -> set[str]:
    """The precision-6 cell containing the point plus its 8 neighbours (covers any 250 m ring)."""
    return {geohash(lat + dy * _DLAT, lon + dx * _DLON) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))
