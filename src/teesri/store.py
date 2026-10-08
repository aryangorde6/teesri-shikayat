"""DynamoDB single-table access. Keys: HH#<id>/PROFILE, DRAFT#<id>/META, RPT#<id>/META, INC#<id>/META,
UPD#<n>/META, ONCE#<key>/META, FEED/<ts>#<id> (what the console shows)."""
import os
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from teesri import geo

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
    return _table


def _dec(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Time-sortable id, e.g. 20261008T131500-a1b2c3."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


def first_time(update_id: int) -> bool:
    """True once per Telegram update_id; Telegram re-delivers on timeouts."""
    try:
        table().put_item(
            Item={"PK": f"UPD#{update_id}", "SK": "META", "ttl": int(time.time()) + 2 * 86400},
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def once_per(key: str, seconds: int) -> bool:
    """True at most once per `seconds` for this key (TTL deletion is lazy, so expiry is checked here too)."""
    now = int(time.time())
    try:
        table().put_item(
            Item={"PK": f"ONCE#{key}", "SK": "META", "ttl": now + seconds},
            ConditionExpression="attribute_not_exists(PK) OR #t < :now",
            ExpressionAttributeNames={"#t": "ttl"}, ExpressionAttributeValues={":now": now},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def log_event(kind: str, **data) -> None:
    """One feed for the console: tripwire decisions, warnings, closures."""
    ts = now_iso()
    table().put_item(Item=_dec({"PK": "FEED", "SK": f"{ts}#{new_id()}", "kind": kind, "ts": ts, **data}))


# --- households -------------------------------------------------------------

def get_household(hh_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"HH#{hh_id}", "SK": "PROFILE"}).get("Item")


def upsert_household(hh_id: str, **attrs) -> None:
    attrs = _dec(attrs)
    names = {f"#{k}": k for k in attrs}
    values = {f":{k}": v for k, v in attrs.items()}
    table().update_item(
        Key={"PK": f"HH#{hh_id}", "SK": "PROFILE"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in attrs),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def delete_household(hh_id: str) -> None:
    table().delete_item(Key={"PK": f"HH#{hh_id}", "SK": "PROFILE"})


def is_enrolled(hh: dict | None) -> bool:
    return bool(hh and hh.get("consent_ts") and "lat" in hh)


# --- reports ----------------------------------------------------------------

def put_draft(rpt_id: str, **attrs) -> None:
    table().put_item(Item=_dec({"PK": f"DRAFT#{rpt_id}", "SK": "META", "ttl": int(time.time()) + 86400, **attrs}))


def get_draft(rpt_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"DRAFT#{rpt_id}", "SK": "META"}).get("Item")


def update_draft(rpt_id: str, field: str, value) -> None:
    table().update_item(
        Key={"PK": f"DRAFT#{rpt_id}", "SK": "META"},
        UpdateExpression="SET #f = :v",
        ExpressionAttributeNames={"#f": field},
        ExpressionAttributeValues={":v": _dec(value)},
    )


def put_report(rpt_id: str, hh: dict, fields: dict, source: str, transcript: str = "", transcript_key: str = "",
               ts: str | None = None) -> bool:
    """Writes the final report once (the stream INSERT feeds the tripwire). False if it already exists.
    `ts` is only passed by the demo scenario and tests (demo clock)."""
    lat, lon = float(hh["lat"]), float(hh["lon"])
    ts = ts or now_iso()
    item = {
        "PK": f"RPT#{rpt_id}", "SK": "META",
        "hh_id": hh["PK"].removeprefix("HH#"), "ts": ts, "lat": lat, "lon": lon,
        "GSI1PK": f"GH6#{geo.geohash(lat, lon)}", "GSI1SK": ts,
        "source": source, "transcript": transcript, "transcript_key": transcript_key,
        "is_simulated": bool(hh.get("is_simulated")),
        **{k: v for k, v in fields.items() if v is not None},
    }
    try:
        table().put_item(Item=_dec(item), ConditionExpression="attribute_not_exists(PK)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    table().delete_item(Key={"PK": f"DRAFT#{rpt_id}", "SK": "META"})
    return True


def get_report(rpt_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"RPT#{rpt_id}", "SK": "META"}, ConsistentRead=True).get("Item")


def _query_cells(prefix: str, lat: float, lon: float, since: str = "") -> list[dict]:
    out = []
    for cell in sorted(geo.cells_around(lat, lon)):
        cond = Key("GSI1PK").eq(f"{prefix}#{cell}")
        if since:
            cond = cond & Key("GSI1SK").gte(since)
        kw = {"IndexName": "GSI1", "KeyConditionExpression": cond}
        while True:
            page = table().query(**kw)
            out += page["Items"]
            if "LastEvaluatedKey" not in page:
                break
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return out


def reports_near(lat: float, lon: float, since: str) -> list[dict]:
    """Reports in the 9 geohash cells around the point, newer than `since` (GSI1 is eventually consistent)."""
    return _query_cells("GH6", lat, lon, since)


def incidents_near(lat: float, lon: float) -> list[dict]:
    return _query_cells("IGH6", lat, lon)


# --- incidents ----------------------------------------------------------------

class Conflict(Exception):
    """Another writer got there first (a report already belongs to an incident, or the incident exists)."""


def _transact(items: list[dict], what: str) -> None:
    # The resource's client takes plain Python values (it adds the DynamoDB type tags itself).
    name = os.environ["TABLE"]
    try:
        table().meta.client.transact_write_items(TransactItems=[{op: {"TableName": name, **_dec(body)}}
                                                                for op, body in items])
    except ClientError as e:
        if e.response["Error"]["Code"] == "TransactionCanceledException":
            raise Conflict(what) from e
        raise


def create_incident(inc: dict, rpt_ids: list[str]) -> None:
    """One transaction: the incident appears and every member report is claimed, or nothing happens.
    A report belongs to at most one incident, so two simultaneous third reports can't make two incidents."""
    items = [("Put", {"Item": {"PK": f"INC#{inc['inc_id']}", "SK": "META", **inc},
                      "ConditionExpression": "attribute_not_exists(PK)"})]
    items += [("Update", _claim(r, inc["inc_id"])) for r in rpt_ids]
    _transact(items, inc["inc_id"])


def join_incident(inc_id: str, rpt_id: str, hh_id: str) -> None:
    """Claims the report for an open incident and adds the home to it, atomically."""
    _transact([
        ("Update", _claim(rpt_id, inc_id)),
        ("Update", {"Key": {"PK": f"INC#{inc_id}", "SK": "META"},
                    "UpdateExpression": "ADD homes :h, report_ids :r SET updated_ts = :now",
                    "ConditionExpression": "attribute_exists(PK) AND #s <> :closed",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {":h": {hh_id}, ":r": {rpt_id}, ":now": now_iso(),
                                                  ":closed": "CLOSED_AT_TAP"}}),
    ], inc_id)


def _claim(rpt_id: str, inc_id: str) -> dict:
    """Update that gives a report to an incident, only if it doesn't belong to one yet."""
    return {"Key": {"PK": f"RPT#{rpt_id}", "SK": "META"}, "UpdateExpression": "SET inc_id = :i",
            "ConditionExpression": "attribute_exists(PK) AND attribute_not_exists(inc_id)",
            "ExpressionAttributeValues": {":i": inc_id}}


def get_incident(inc_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"INC#{inc_id}", "SK": "META"}, ConsistentRead=True).get("Item")
