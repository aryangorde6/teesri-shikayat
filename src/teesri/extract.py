"""Transcript -> fixed complaint fields. The model only fills a schema; code validates every field.

Any failure (no quota, bad JSON, nothing usable) returns None. The caller then tries keywords(), a plain-code
reader for the common Hindi words, and only if that finds nothing either asks the resident with buttons.
The loop never depends on the model.
"""
import logging
import os
import re

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


# --- keywords(): the same fields from plain Hindi words, when the model is unavailable --------------------------
# Spellings are compared without nukta and with ँ as ं, so फ़/फ and पाँच/पांच both match.
COLOUR_WORDS = {
    "yellow": {"पीला", "पीले", "पीली", "पिला", "पिले", "yellow"},
    "brown": {"भूरा", "भूरे", "भूरी", "भुरा", "मटमैला", "मटमैले", "मटमैली", "मटियाला", "मिट्टी", "brown"},
    "black": {"काला", "काले", "काली", "black"},
}
SMELL_WORDS = {"बदबू", "बदबु", "बदबूदार", "बास", "दुर्गंध", "गंध", "smell"}
ILLNESS_WORDS = {
    "diarrhoea": {"दस्त", "डायरिया", "लूज"}, "vomiting": {"उल्टी", "उलटी", "उल्टियां"}, "fever": {"बुखार", "fever"},
    "jaundice": {"पीलिया"}, "skin_rash": {"खुजली", "दाने", "रैश"},
}
VULNERABLE_WORDS = {
    "child": {"बच्चे", "बच्चा", "बच्ची", "बच्चों", "बेटा", "बेटे", "बेटी"},
    "elderly": {"बुजुर्ग", "बूढे", "बूढी", "दादा", "दादी", "नाना", "नानी"},
    "pregnant": {"गर्भवती", "प्रेग्नेंट"},
}
NUMBERS = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10}
UNITS = {"दिन": 1, "दिनों": 1, "हफ्ता": 7, "हफ्ते": 7, "हफ्तों": 7, "सप्ताह": 7, "महीना": 30, "महीने": 30, "महीनों": 30}
SINCE_WORDS = {"आज": 0, "सुबह": 0, "कल": 1, "परसों": 2}
NEGATION = {"नहीं", "नही"}  # not "ना": "है ना?" is a question tag
CLAUSE = re.compile(r"[।,.!?;]|\s(?:और|लेकिन|मगर|पर)\s")


def _norm(text: str) -> str:
    return text.replace("\u093c", "").replace("\u0901", "\u0902").lower()


def _said(clauses: list[list[str]], words: set[str]) -> bool | None:
    """True if a word from `words` is said; False if only ever with a नहीं after it in the same clause; None if never."""
    found = None
    for c in clauses:
        for i, t in enumerate(c):
            if t in words:
                if not NEGATION & set(c[i + 1:]):
                    return True
                found = False
    return found


def _since(tokens: list[str]) -> int:
    for i, t in enumerate(tokens):  # "दो दिन", "2-3 दिन" (the larger), "एक हफ़्ते"
        if t in UNITS:
            n = tokens[i - 1] if i else ""
            n = NUMBERS.get(n) or (int(n) if n.isdigit() and int(n) <= 365 else None)
            if n is None and UNITS[t] > 1:
                n = 1  # "हफ़्ते से" = a week
            if n is not None:
                return min(n * UNITS[t], 365)
    return next((SINCE_WORDS[t] for t in tokens if t in SINCE_WORDS), -1)


def keywords(transcript: str) -> dict | None:
    """Plain-code reading of a Hindi transcript into the same fields as the model, then the same validate().
    Only words that are actually said count; "पानी गंदा है" alone names no colour or smell, so it returns None."""
    clauses = [re.findall(r"[^\s\-–]+", c) for c in CLAUSE.split(_norm(f" {transcript} "))]
    tokens = [t for c in clauses for t in c]
    colour = next((name for name, words in COLOUR_WORDS.items() if _said(clauses, words)), "not_said")
    illness = [name for name, words in ILLNESS_WORDS.items() if _said(clauses, words)]
    if any("पेट" in c and "दर्द" in c and not NEGATION & set(c) for c in clauses):
        illness.append("stomach_pain")
    vulnerable = [name for name, words in VULNERABLE_WORDS.items() if illness and words & set(tokens)]
    return validate({"colour": colour, "smell": {True: "yes", False: "no", None: "not_said"}[_said(clauses, SMELL_WORDS)],
                     "since_days": _since(tokens), "illness": illness, "vulnerable": vulnerable})


def is_dirty(f: dict) -> bool:
    return f.get("colour") in DIRTY_COLOURS or f.get("smell") is True or bool(f.get("illness"))
