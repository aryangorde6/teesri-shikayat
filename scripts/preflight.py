"""One command before recording: is everything live and in the right mode? Prints secrets nowhere.
Then security and recovery: is the stack still what README → Security says? Read-only.

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/preflight.py [--security]   (--security: only those checks)
"""
import json
import os
import sys
import time
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


def security(out: dict) -> None:
    print("\nSecurity and recovery")
    ddb, kms = boto3.client("dynamodb", region_name=REGION), boto3.client("kms", region_name=REGION)
    table = ddb.describe_table(TableName=out["TableName"])["Table"]
    key = kms.describe_key(KeyId="alias/teesri-data")["KeyMetadata"]
    sse = table.get("SSEDescription", {})
    check("Table encrypted with our own KMS key", sse.get("Status") == "ENABLED" and sse.get("KMSMasterKeyArn") == key["Arn"])
    check("Key rotation on", kms.get_key_rotation_status(KeyId=key["KeyId"])["KeyRotationEnabled"])
    pitr = ddb.describe_continuous_backups(TableName=out["TableName"])["ContinuousBackupsDescription"].get(
        "PointInTimeRecoveryDescription", {})
    check("Point-in-time recovery on", pitr.get("PointInTimeRecoveryStatus") == "ENABLED",
          f"can restore back to {pitr['EarliestRestorableDateTime']:%d %b %H:%M}" if "EarliestRestorableDateTime" in pitr else "")
    check("Deletion protection on", table.get("DeletionProtectionEnabled", False))

    ct = boto3.client("cloudtrail", region_name=REGION)
    trails = [t for t in ct.describe_trails()["trailList"] if t["Name"].startswith("Teesri-")]
    check("CloudTrail logging, with log-file validation",
          bool(trails) and all(t["LogFileValidationEnabled"] and ct.get_trail_status(Name=t["TrailARN"])["IsLogging"] for t in trails))
    gd = boto3.client("guardduty", region_name=REGION)
    detectors = gd.list_detectors()["DetectorIds"]
    check("GuardDuty on", bool(detectors) and gd.get_detector(DetectorId=detectors[0])["Status"] == "ENABLED")

    aa = boto3.client("accessanalyzer", region_name=REGION)
    analyzer = next((a for a in aa.list_analyzers(type="ACCOUNT")["analyzers"] if a["name"] == "teesri-external-access"), None)
    open_to_outside = sorted(f["resource"].rsplit(":", 1)[-1] for f in aa.list_findings_v2(
        analyzerArn=analyzer["arn"], filter={"status": {"eq": ["ACTIVE"]}})["findings"]
        if ":Teesri-" in f["resource"] or ":::teesri-" in f["resource"]) if analyzer else None
    check("Only the Function URL is reachable from outside (Access Analyzer)",
          open_to_outside is not None and len(open_to_outside) == 1 and open_to_outside[0].startswith("Teesri-Api"),
          f"open: {open_to_outside}")

    alarms = boto3.client("cloudwatch", region_name=REGION).describe_alarms(AlarmNamePrefix="Teesri-")["MetricAlarms"]
    firing = [a["AlarmName"].split("Alarm")[0].removeprefix("Teesri-") for a in alarms if a["StateValue"] == "ALARM"]
    check("Five failure alarms wired to the alert topic, none firing",
          len(alarms) == 5 and all(out["AlertsTopicArn"] in a["AlarmActions"] for a in alarms) and not firing,
          f"firing: {', '.join(firing)}" if firing else "")
    subs = boto3.client("sns", region_name=REGION).list_subscriptions_by_topic(TopicArn=out["AlertsTopicArn"])["Subscriptions"]
    confirmed = [x for x in subs if x["SubscriptionArn"].startswith("arn:")]  # pending ones say "PendingConfirmation"
    check("Someone gets the alert emails (subscription confirmed)", bool(confirmed), f"{len(confirmed)} confirmed")

    s3 = boto3.client("s3", region_name=REGION)
    block = s3.get_public_access_block(Bucket=out["BucketName"])["PublicAccessBlockConfiguration"]
    rules = {r["ID"]: r.get("Expiration", {}).get("Days") for r in
             s3.get_bucket_lifecycle_configuration(Bucket=out["BucketName"])["Rules"]}
    check("Media bucket private; voice notes and transcripts expire after 30 days",
          all(block.values()) and rules.get("expire-voice") == 30 and rules.get("expire-transcripts") == 30)


def main() -> None:
    out = {o["OutputKey"]: o["OutputValue"] for o in boto3.client("cloudformation", region_name=REGION)
           .describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]}
    if "--security" in sys.argv:
        security(out)
        print("\nSECURE" if ok else "\nNOT AS DOCUMENTED: fix the ❌ lines above")
        sys.exit(0 if ok else 1)
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
    security(out)
    print()
    backend = case.get("Environment", {}).get("Variables", {}).get("MODEL_BACKEND", "bedrock")
    if backend == "selfhost":  # the open model on our instance: does it answer through the queue right now?
        os.environ.update(TABLE=out["TableName"], MODEL_BACKEND="selfhost", AWS_DEFAULT_REGION=REGION,
                          MODEL_QUEUE_URL=case["Environment"]["Variables"]["MODEL_QUEUE_URL"])
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from teesri import selfhost
        try:
            t0 = time.time()
            status, _, text = selfhost.call("/v1/chat/completions", {"messages": [{"role": "user", "content": "Reply OK."}],
                                                                     "max_tokens": 5}, timeout=30) if selfhost.available() else (0, "", "")
            nova, err = status == 200, ("instance off: run scenario.py model on" if not status else f"HTTP {status}")
            took = f"{time.time() - t0:.1f}s"
        except Exception as e:
            nova, err, took = False, type(e).__name__, ""
        check("Self-hosted model answers (instance on, via the queue)", nova or mode != "agent",
              f"answered in {took}" if nova else f"{err}; agent steps would fall back to templates")
        print("\nREADY" if ok else "\nNOT READY: fix the ❌ lines above")
        sys.exit(0 if ok else 1)
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
