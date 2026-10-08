"""Transcript -> fixed complaint fields. The model only fills a schema; code validates every field.

Any failure (no quota, bad JSON, nothing usable) returns None, and the caller asks the
resident with buttons instead. The loop never depends on the model.
"""
import logging
import os

import boto3

log = logging.getLogger()

COLOURS = {"clear", "yellow", "brown", "black"}
ILLNESS = {"diarrhoea", "vomiting", "fever", "stomach_pain", "jaundice", "skin_rash"}
VULNERABLE = {"child", "elderly", "pregnant"}
DIRTY_COLOURS = {"yellow", "brown", "black"}

SYSTEM = (
    "You read a resident's complaint about their tap water, transcribed from a Hindi voice note. "
    "Fill the record_complaint tool using only what the resident actually said. "
    "If something is not mentioned, use not_said, -1 or an empty list. Never guess."
)

TOOL = {"toolSpec": {
    "name": "record_complaint",
    "description": "Record the facts of one dirty-water complaint.",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {
            "colour": {"type": "string", "enum": sorted(COLOURS) + ["not_said"],
                       "description": "Water colour: clear, yellow (peela), brown (bhura/matmaila), black (kaala)."},
            "smell": {"type": "string", "enum": ["yes", "no", "not_said"], "description": "Does the water smell bad (badboo)?"},
            "since_days": {"type": "integer", "description": "How many days the problem has lasted. Today = 0. Not said = -1."},
            "illness": {"type": "array", "items": {"type": "string", "enum": sorted(ILLNESS)},
                        "description": "Symptoms anyone in the home has."},
            "vulnerable": {"type": "array", "items": {"type": "string", "enum": sorted(VULNERABLE)},
                           "description": "Who is affected, if said: child, elderly, pregnant."},
        },
        "required": ["colour", "smell", "since_days", "illness", "vulnerable"],
    }},
}}

_client = None


def extract(transcript: str) -> dict | None:
    global _client
    if not transcript.strip():
        return None
    try:
        _client = _client or boto3.client("bedrock-runtime", region_name=os.environ.get("BEDROCK_REGION", "ap-south-1"))
        resp = _client.converse(
            modelId=os.environ.get("MODEL_ID", "global.amazon.nova-2-lite-v1:0"),
            system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": [{"text": transcript}]}],
            toolConfig={"tools": [TOOL], "toolChoice": {"tool": {"name": "record_complaint"}}},
            inferenceConfig={"temperature": 0, "maxTokens": 400},
        )
    except Exception as e:  # quota, throttling, access: fall back to buttons
        log.warning("extraction unavailable: %s", e)
        return None
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return validate(block["toolUse"]["input"])
    return None


def validate(raw: dict) -> dict | None:
    """Keep only allowed values. None if neither colour nor smell is known (we can't classify it)."""
    colour = raw.get("colour") if raw.get("colour") in COLOURS else None
    smell = {"yes": True, "no": False}.get(raw.get("smell"))
    since = raw.get("since_days")
    since = int(since) if isinstance(since, (int, float)) and not isinstance(since, bool) and 0 <= since <= 365 and since == int(since) else None
    if colour is None and smell is None:
        return None
    return {
        "colour": colour,
        "smell": smell,
        "since_days": since,
        "illness": sorted({i for i in raw.get("illness") or [] if i in ILLNESS}),
        "vulnerable": sorted({v for v in raw.get("vulnerable") or [] if v in VULNERABLE}),
    }


def is_dirty(f: dict) -> bool:
    return f.get("colour") in DIRTY_COLOURS or f.get("smell") is True or bool(f.get("illness"))
