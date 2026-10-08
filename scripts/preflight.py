"""One command before recording: is everything live and in the right mode? Prints secrets nowhere.

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/preflight.py
"""
import json
import os
import sys
import urllib.request

import boto3
from botocore.config import Config

REGION = "ap-south-1"
ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= passed
    print(f"{'✅' if passed else '❌'} {name}{' — ' + detail if detail else ''}")


def warn(name: str, detail: str) -> None:
    """Not a blocker, but it decides how to record."""
    print(f"⚠️  {name} — {detail}")


def main() -> None:
    out = {o["OutputKey"]: o["OutputValue"] for o in boto3.client("cloudformation", region_name=REGION)
           .describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]}
    base = out["FunctionUrl"].rstrip("/")

    ssm = boto3.client("ssm", region_name=REGION)
    token = ssm.get_parameter(Name="/teesri/telegram/bot-token", WithDecryption=True)["Parameter"]["Value"]
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15) as r:
        info = json.load(r)["result"]
    check("Telegram webhook points at this stack", info.get("url") == base + "/tg",
          f"pending updates {info.get('pending_update_count', 0)}" + (f", last error: {info['last_error_message']}" if info.get("last_error_message") else ""))

    pipes = boto3.client("pipes", region_name=REGION).list_pipes()["Pipes"]
    check("Pipe (stream -> tripwire) running", any(p["CurrentState"] == "RUNNING" for p in pipes))

    sfn = boto3.client("stepfunctions", region_name=REGION)
    running = sfn.list_executions(stateMachineArn=out["CaseMachineArn"], statusFilter="RUNNING")["executions"]
    check("No case left running from a rehearsal", not running, f"{len(running)} running" if running else "")

    with urllib.request.urlopen(f"{base}/api/state", timeout=15) as r:
        s = json.load(r)
    check("Console API answers", True, f"{len(s['homes'])} enrolled homes, incident: {s['incident'] and s['incident']['status']}")
    check("Quiet mode is OFF (real phones get messages)", not s.get("quiet"))
    real = [h for h in s["homes"] if not h["sim"]]
    check("Your phone is enrolled", bool(real), f"{len(real)} real home(s)")
    check("Your phone has no old reports showing", not any(h["reported"] for h in real),
          "run: scenario.py reset --mine" if any(h["reported"] for h in real) else "")

    fn = boto3.client("lambda", region_name=REGION)
    case = next(f for f in fn.list_functions()["Functions"] if f["FunctionName"].startswith("Teesri-Case"))
    mode = case.get("Environment", {}).get("Variables", {}).get("AGENT_MODE", "template")
    res = fn.invoke(FunctionName=case["FunctionName"], Payload=json.dumps({"step": "selftest"}).encode())
    body = json.loads(res["Payload"].read() or b"{}")
    check("Case Lambda: Strands + Cedar load", "FunctionError" not in res, f"strands {body.get('strands')}, cedarpy {body.get('cedarpy')}")
    rt = boto3.client("bedrock-runtime", region_name=REGION, config=Config(retries={"max_attempts": 1}))
    try:
        rt.converse(modelId=os.environ.get("MODEL_ID", "global.amazon.nova-2-lite-v1:0"),
                    messages=[{"role": "user", "content": [{"text": "Reply OK."}]}], inferenceConfig={"maxTokens": 5})
        nova = True
    except Exception as e:
        nova, err = False, type(e).__name__
    if nova or mode == "agent":  # agent mode without Nova would quietly fall back to templates: a blocker
        check("Nova answers (voice notes read by the model)", nova, "" if nova else f"{err}, but AGENT_MODE=agent")
    else:
        warn("Nova unavailable", f"{err}. Template mode: voice notes are read by the keyword reader (say a colour or बदबू). "
             "Record with voiceover-template.md, build_cards.py --mode template, build_video.py --mode template")
    check("Case agent mode", mode == "agent" or not nova,
          f"AGENT_MODE={mode}" + (" — Nova works now: switch to agent in infra/stack.py and deploy" if nova and mode != "agent" else ""))
    print("\nREADY" if ok else "\nNOT READY: fix the ❌ lines above")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
