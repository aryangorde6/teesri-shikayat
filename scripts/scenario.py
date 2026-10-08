"""Runs the demo scenario against the deployed table (the console's scenario button calls the same functions).

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py reset [--mine] | seed | building | stand-in | status
  reset     remove simulated homes, their reports, all incidents and the feed (real homes stay enrolled)
            --mine also removes your phone's reports, for a clean recording
  seed      enrol simulated homes A–V + one building; A and B file their reports (demo clock: ~71 h, 20 h ago)
  building  three flats in one building report -> tank advice, no alarm
  stand-in  a simulated stand-in next to your phone files the third report (testing without the phone)
  status    homes in the ring, reports, incidents, feed
"""
import json
import os
import pathlib
import sys

import boto3

REGION = "ap-south-1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in {"reset", "seed", "building", "stand-in", "status"}:
        sys.exit(__doc__)
    outputs = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]
    os.environ["TABLE"] = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "TableName")
    os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
    os.environ.setdefault("TG_TOKEN_PARAM", "/teesri/telegram/bot-token")  # only used if a real home is messaged
    from teesri import scenario

    cmd = args[0]
    result = {
        "reset": lambda: scenario.reset(mine="--mine" in args),
        "seed": scenario.seed,
        "building": scenario.building,
        "stand-in": scenario.third_stand_in,
        "status": scenario.status,
    }[cmd]()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
