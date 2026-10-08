# Teesri Shikayat — the third complaint

**A tripwire for dirty tap water.** When three homes close together report dirty water, everyone around them is warned, and only the residents can close the case.

Built for the WeMakeDevs × AWS **Environmental Hacks** (Heat and Water track), Oct 8–11, 2026.

> Work in progress. This README grows with the build.

## Data

- Population in a warning ring: **GHS-POP R2023A, epoch 2025, 100 m** (European Commission, Joint Research Centre; CC BY 4.0), read from the Registry of Open Data on AWS (`s3://jrc-ghsl/ghs-pop/`) by `scripts/precompute_population.py`. Shown as "~N people"; when the grid doesn't cover a ring it says "NO DATA", never 0.
- Place coordinates: © OpenStreetMap contributors (ODbL).

## AI tools used
This project was built with help from AI coding agents (Claude).
