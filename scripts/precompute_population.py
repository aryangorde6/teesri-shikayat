"""One-off: read the demo area from GHS-POP 2025 (100 m) on the Registry of Open Data on AWS and save a small grid.

The Lambda only sums this grid (teesri/population.py), so no raster library ships with it.
Run (dev only, needs rasterio + pyproj):  .venv/bin/python scripts/precompute_population.py
"""
import json
import pathlib

import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

SRC = "s3://jrc-ghsl/ghs-pop/r2023a/54009/100m/2025/GHS_POP_E2025_GLOBE_R2023A_54009_100_V1_0.tif"
CENTRE = (18.9622, 72.8368)  # Dongri, B ward, Mumbai (OpenStreetMap)
HALF_M = 1500                # 3 km x 3 km: room for any demo ring
OUT = pathlib.Path(__file__).resolve().parent.parent / "src/teesri/data/ghs_pop_dongri.json"


def main() -> None:
    to_moll = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    to_wgs = Transformer.from_crs("ESRI:54009", "EPSG:4326", always_xy=True)
    x0, y0 = to_moll.transform(CENTRE[1], CENTRE[0])
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(SRC) as ds:
            win = from_bounds(x0 - HALF_M, y0 - HALF_M, x0 + HALF_M, y0 + HALF_M, ds.transform)
            win = win.round_offsets().round_lengths()
            data = ds.read(1, window=win)
            tr, nodata, cell_m = ds.window_transform(win), ds.nodata, abs(ds.res[0])

    cells = []
    for r in range(data.shape[0]):
        for c in range(data.shape[1]):
            v = float(data[r, c])
            lon, lat = to_wgs.transform(*(tr * (c + 0.5, r + 0.5)))
            # GHS-POP marks open sea as nodata: nobody lives there, so it counts as 0 people.
            cells.append([round(lat, 6), round(lon, 6), 0.0 if v == nodata or v < 0 else round(v, 1)])

    lats, lons = [c[0] for c in cells], [c[1] for c in cells]
    out = {
        "source": SRC,
        "dataset": "GHS-POP R2023A, epoch 2025, 100 m, Mollweide (ESRI:54009)",
        "licence": "CC BY 4.0, European Commission Joint Research Centre (JRC)",
        "cell_m": cell_m,
        # Area safely covered by cell centres (half a cell in from the edge).
        "covered": [min(lats), min(lons), max(lats), max(lons)],
        "cells": cells,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    total = sum(c[2] for c in cells)
    print(f"{len(cells)} cells, {total:,.0f} people in {2 * HALF_M / 1000:.0f} km x {2 * HALF_M / 1000:.0f} km -> {OUT}")


if __name__ == "__main__":
    main()
