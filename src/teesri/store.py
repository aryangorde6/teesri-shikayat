"""DynamoDB single-table access. Keys: HH#<id>/PROFILE, DRAFT#<id>/META, RPT#<id>/META, UPD#<n>/META."""
import os
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
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


def put_report(rpt_id: str, hh: dict, fields: dict, source: str, transcript: str = "", transcript_key: str = "") -> bool:
    """Writes the final report once (the stream INSERT feeds the tripwire). False if it already exists."""
    lat, lon = float(hh["lat"]), float(hh["lon"])
    ts = now_iso()
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
