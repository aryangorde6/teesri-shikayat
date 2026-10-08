"""What one real incident cost, measured from its own Step Functions history and Lambda logs and priced with the
AWS Pricing API (ap-south-1, on-demand, no free tier). Upper bounds where a count isn't recorded.

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/cost_per_incident.py [--inr 88.0]
"""
import json
import sys
import time

import pathlib

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from teesri import texts  # noqa: E402

REGION = "ap-south-1"
MEM_GB = 0.25  # every Lambda here has 256 MB


def price(code: str, usagetype: str) -> float:
    pr = boto3.client("pricing", region_name="us-east-1")
    f = [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": REGION},
         {"Type": "TERM_MATCH", "Field": "usagetype", "Value": usagetype}]
    for page in pr.get_paginator("get_products").paginate(ServiceCode=code, Filters=f):
        for raw in page["PriceList"]:
            for term in json.loads(raw)["terms"]["OnDemand"].values():
                for dim in term["priceDimensions"].values():
                    if dim.get("beginRange", "0") == "0" and float(dim["pricePerUnit"]["USD"]) > 0:
                        return float(dim["pricePerUnit"]["USD"])
    raise LookupError(usagetype)


def lambda_usage(groups: list[str], start: int, end: int) -> tuple[int, float]:
    logs = boto3.client("logs", region_name=REGION)
    q = logs.start_query(logGroupNames=groups, startTime=start, endTime=end,
                         queryString='filter @type = "REPORT" | stats count(*) as n, sum(@billedDuration) as ms')
    while True:
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)
    row = {f["field"]: f["value"] for f in (r["results"] or [[]])[0]}
    return int(float(row.get("n", 0))), float(row.get("ms", 0)) / 1000


def main() -> None:
    inr = float(sys.argv[sys.argv.index("--inr") + 1]) if "--inr" in sys.argv else 88.0
    out = {o["OutputKey"]: o["OutputValue"] for o in boto3.client("cloudformation", region_name=REGION)
           .describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]}
    sfn = boto3.client("stepfunctions", region_name=REGION)
    ex = sfn.list_executions(stateMachineArn=out["CaseMachineArn"], maxResults=1)["executions"][0]
    events = [e for page in sfn.get_paginator("get_execution_history").paginate(executionArn=ex["executionArn"])
              for e in page["events"]]
    transitions = sum(1 for e in events if e["type"].endswith("StateEntered"))
    start = int(ex["startDate"].timestamp()) - 300
    end = int((ex.get("stopDate") or events[-1]["timestamp"]).timestamp()) + 60

    lam = boto3.client("lambda", region_name=REGION)
    names = {f["FunctionName"] for f in lam.list_functions()["Functions"] if f["FunctionName"].startswith("Teesri-")}
    case_fn = next(n for n in names if n.startswith("Teesri-Case"))
    trip_fn = next(n for n in names if n.startswith("Teesri-Tripwire"))
    case_n, case_s = lambda_usage([f"/aws/lambda/{case_fn}"], start, end)
    trip_n, trip_s = lambda_usage([f"/aws/lambda/{trip_fn}"], start, end)

    ddb = boto3.resource("dynamodb", region_name=REGION).Table(out["TableName"])
    inc_id = ex["name"]
    inc_items = ddb.query(KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(f"INC#{inc_id}"))["Items"]
    inc = next(i for i in inc_items if i["SK"] == "META")
    ring = len(inc.get("ring_hh", []))
    real_reports = sum(1 for r in inc["report_ids"] if r.startswith("tg"))
    # Polly runs once per incident and message template (made before the fan-out, reused from S3).
    reopens = int(inc.get("reopen_count", 0))
    polly_chars = (len(texts.RING_WARNING.format(homes=len(inc["homes"]), clinic="जे. जे. अस्पताल"))
                   + (len(texts.REOPENED) if reopens else 0)
                   + max(real_reports, 1) * len(texts.receipt({"colour": "brown", "smell": True, "since_days": 3})))

    p = {
        "sfn": price("AmazonStates", "APS3-StateTransition"),
        "req": price("AWSLambda", "APS3-Request-ARM"),
        "gbs": price("AWSLambda", "APS3-Lambda-GB-Second-ARM"),
        "polly": price("AmazonPolly", "APS3-SynthesizeSpeechNeural-Characters"),
        "transcribe": price("transcribe", "APS3-TranscribeAudio"),
        "wru": price("AmazonDynamoDB", "APS3-WriteRequestUnits"),
        "rru": price("AmazonDynamoDB", "APS3-ReadRequestUnits"),
    }
    writes = (len(inc_items) + ring * 4 + 50) * 2   # case items + wall/messages per home + reports, x2 for the GSI
    lines = [
        ("Step Functions", f"{transitions} state transitions", transitions * p["sfn"]),
        ("Lambda: case", f"{case_n} invocations, {case_s:.1f} s", case_n * p["req"] + case_s * MEM_GB * p["gbs"]),
        ("Lambda: tripwire", f"{trip_n} invocations, {trip_s:.1f} s", trip_n * p["req"] + trip_s * MEM_GB * p["gbs"]),
        ("Lambda: API (voice note + taps, est.)", "8 invocations, 8 s", 8 * p["req"] + 8 * MEM_GB * p["gbs"]),
        ("Polly neural", f"{polly_chars} characters", polly_chars * p["polly"]),
        ("Transcribe hi-IN", f"{max(real_reports, 1)} voice note(s) x 15 s min", max(real_reports, 1) * 15 * p["transcribe"]),
        ("DynamoDB on-demand (generous)", f"~{writes} writes, ~{writes * 5} reads", writes * p["wru"] + writes * 5 * p["rru"]),
    ]
    total = sum(c for _, _, c in lines)
    print(f"Incident {inc_id}: {ring} homes warned, reopened x{int(inc.get('reopen_count', 0))}, status {inc.get('status')}")
    for name, usage, cost in lines:
        print(f"  {name:<40} {usage:<36} ${cost:.5f}")
    print(f"  {'TOTAL':<40} {'':<36} ${total:.4f}  = Rs {total * inr:.2f} at Rs {inr}/USD")
    print("Prices: AWS Pricing API, ap-south-1 on-demand, first tier, no free tier. Telegram messages are free.")


if __name__ == "__main__":
    main()
