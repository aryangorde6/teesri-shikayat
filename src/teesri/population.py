"""People living inside a ring, from the precomputed GHS-POP grid (Open Data on AWS, scripts/precompute_population.py).

Returns None when the grid doesn't cover the whole ring: that is shown as "NO DATA", never as 0.
"""
import json
import math
import pathlib
from functools import cache

from teesri import geo

GRID_FILE = pathlib.Path(__file__).parent / "data" / "ghs_pop_dongri.json"
M_PER_DEG = 6_371_000 * math.pi / 180
_SUB = 5  # each 100 m cell is sampled 5 x 5 times to count the part of it inside the ring


@cache
def _grid() -> dict | None:
    try:
        return json.loads(GRID_FILE.read_text())
    except FileNotFoundError:
        return None


def ring_population(lat: float, lon: float, radius_m: float, grid: dict | None = None) -> int | None:
    g = grid if grid is not None else _grid()
    if not g:
        return None
    south, west, north, east = g["covered"]
    dlat = radius_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(lat))
    if lat - dlat < south or lat + dlat > north or lon - dlon < west or lon + dlon > east:
        return None
    cell, total = g["cell_m"], 0.0
    step = cell / _SUB
    for clat, clon, people in g["cells"]:
        if people <= 0 or geo.distance_m(lat, lon, clat, clon) > radius_m + cell:
            continue
        cos_c = math.cos(math.radians(clat))
        inside = sum(
            geo.distance_m(lat, lon, clat + (-cell / 2 + (i + 0.5) * step) / M_PER_DEG,
                           clon + (-cell / 2 + (j + 0.5) * step) / (M_PER_DEG * cos_c)) <= radius_m
            for i in range(_SUB) for j in range(_SUB)
        )
        total += people * inside / _SUB**2
    return round(total)


def label(people: int | None) -> str:
    """"~12,300 लोग" style rounding for cards; None -> NO DATA."""
    if people is None:
        return "NO DATA"
    return f"~{round(people, -2 if people >= 1000 else -1):,}"
