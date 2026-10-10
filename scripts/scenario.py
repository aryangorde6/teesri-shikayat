"""Runs the demo scenario against the deployed table (the console's scenario button calls the same functions).

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py <command>
  reset     stop running cases; remove simulated homes, their reports, all incidents, the feed (real homes stay)
            --mine also removes your phone's reports, for a clean recording
  seed      enrol simulated homes A–V + one building; A and B file their reports (demo clock: ~71 h, 20 h ago)
  building  three flats in one building report -> tank advice, no alarm
  stand-in  a simulated stand-in next to your phone files the third report (testing without the phone)
  status    homes in the ring, reports, incidents, feed
  volunteer phone|sim     who gets the volunteer card (seed picks your phone if it is enrolled)
  approve [no]            the simulated volunteer taps हाँ, भेजें (or अभी नहीं)
  ward-reply [text]       the ward office replies (default "Resolved")
  answer <home> yes|no    a simulated home answers the check-in, e.g. answer C yes
  anchor dongri|phone     where the demo is: the Dongri pin, or your phone's home (default)
  quiet on|off            rehearsal mode: hold back messages to real phones (turn OFF before recording)
  model on|off|status     the self-hosted model instance ($0.43/h while on; it stops itself after an idle hour)
"""
import json
import os
import pathlib
import sys
import time

import boto3

REGION = "ap-south-1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in {"reset", "seed", "building", "stand-in", "status", "volunteer", "approve",
                                   "ward-reply", "answer", "quiet", "anchor", "model"}:
        sys.exit(__doc__)
    outputs = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]
    out = {o["OutputKey"]: o["OutputValue"] for o in outputs}
    os.environ["TABLE"] = out["TableName"]
    os.environ["STATE_MACHINE_ARN"] = out.get("CaseMachineArn", "")
    os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
    os.environ.setdefault("TG_TOKEN_PARAM", "/teesri/telegram/bot-token")  # only used if a real home is messaged
    from teesri import scenario

    cmd = args[0]
    if cmd == "model":
        return print(json.dumps(model(out["ModelInstanceId"], args[1] if len(args) > 1 else "status"), indent=2))
    result = {
        "reset": lambda: scenario.reset(mine="--mine" in args),
        "seed": scenario.seed,
        "building": scenario.building,
        "stand-in": scenario.third_stand_in,
        "status": scenario.status,
        "volunteer": lambda: scenario.set_volunteer(args[1] if len(args) > 1 else "phone"),
        "approve": lambda: scenario.approve("no" not in args[1:]),
        "ward-reply": lambda: scenario.ward_reply(" ".join(args[1:]) or "Resolved"),
        "answer": lambda: scenario.answer(args[1], args[2] == "yes"),
        "quiet": lambda: scenario.set_quiet(args[1] == "on"),
        "anchor": lambda: scenario.set_anchor(args[1] if len(args) > 1 else "phone"),
    }[cmd]()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def model(instance_id: str, action: str) -> dict:
    """Start or stop the model instance; "on" waits until the model answers its heartbeat."""
    from teesri import store
    ec2 = boto3.client("ec2", region_name=REGION)
    if action == "on":
        ec2.start_instances(InstanceIds=[instance_id])
    elif action == "off":
        ec2.stop_instances(InstanceIds=[instance_id])
    started = time.time()
    while True:
        state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
        hb = store.table().get_item(Key={"PK": "MODEL#heartbeat", "SK": "META"}).get("Item") or {}
        up = state == "running" and time.time() - int(hb.get("ts", 0)) < 60
        if action != "on" or up or time.time() - started > 300:
            return {"instance": state, "model": hb.get("model") if up else None, "answering": up}
        time.sleep(10)


if __name__ == "__main__":
    main()
