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


# --- keywords(): the same fields from plain words, when the model is unavailable ---------------------------------
# Reads Devanagari (voice transcripts, typed Hindi) and Roman-script Hinglish as people type it ("paani peela hai").
# Spellings are compared lowercased, without nukta and with ँ as ं, so फ़/फ and पाँच/पांच both match.
COLOUR_WORDS = {
    "yellow": {"पीला", "पीले", "पीली", "पिला", "पिले", "peela", "pila", "peeli", "pili", "peele", "yellow"},
    "brown": {"भूरा", "भूरे", "भूरी", "भुरा", "मटमैला", "मटमैले", "मटमैली", "मटियाला", "मिट्टी",
              "bhura", "bhoora", "bhure", "bhoore", "matmaila", "matmela", "mitti", "brown", "muddy"},
    "black": {"काला", "काले", "काली", "kala", "kaala", "kale", "kaale", "kali", "kaali", "black"},
}
SMELL_WORDS = {"बदबू", "बदबु", "बदबूदार", "बास", "दुर्गंध", "गंध",
               "badbu", "badboo", "badbudar", "badbudaar", "durgandh", "smell", "smells", "smelly", "stink", "stinks", "stinking"}
ILLNESS_WORDS = {
    "diarrhoea": {"दस्त", "डायरिया", "लूज", "dast", "loose", "diarrhoea", "diarrhea"},
    "vomiting": {"उल्टी", "उलटी", "उल्टियां", "ulti", "ultee", "vomit", "vomiting"},
    "fever": {"बुखार", "bukhar", "bukhaar", "fever"},
    "jaundice": {"पीलिया", "piliya", "peeliya", "jaundice"},
    "skin_rash": {"खुजली", "दाने", "रैश", "khujli", "rash"},
}
VULNERABLE_WORDS = {
    "child": {"बच्चे", "बच्चा", "बच्ची", "बच्चों", "बेटा", "बेटे", "बेटी",
              "bacche", "baccha", "bachche", "bachcha", "bacchi", "beta", "beti", "child", "children", "kid", "kids", "baby"},
    "elderly": {"बुजुर्ग", "बूढे", "बूढी", "दादा", "दादी", "नाना", "नानी", "buzurg", "bujurg", "dada", "dadi", "nana", "nani", "elderly"},
    "pregnant": {"गर्भवती", "प्रेग्नेंट", "pregnant"},
}
NUMBERS = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
           "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "saat": 7, "aath": 8, "das": 10,
           "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
UNITS = {"दिन": 1, "दिनों": 1, "हफ्ता": 7, "हफ्ते": 7, "हफ्तों": 7, "सप्ताह": 7, "महीना": 30, "महीने": 30, "महीनों": 30,
         "din": 1, "dino": 1, "dinon": 1, "day": 1, "days": 1, "hafta": 7, "hafte": 7, "week": 7, "weeks": 7,
         "mahina": 30, "mahine": 30, "month": 30, "months": 30}
SINCE_WORDS = {"आज": 0, "सुबह": 0, "कल": 1, "परसों": 2, "aaj": 0, "aj": 0, "today": 0, "subah": 0, "morning": 0,
               "kal": 1, "yesterday": 1, "parso": 2, "parson": 2}
NEGATION = {"नहीं", "नही", "nahi", "nahin", "nahee"}  # after the word; not "ना": "है ना?" is a question tag
NEGATION_BEFORE = {"no", "not", "without"}             # English puts it first: "no smell"
CLAUSE = re.compile(r"[।,.!?;]|\s(?:और|लेकिन|मगर|पर|aur|lekin|magar|par|and|but)\s")
DIRTY_WORDS = {"गंदा", "गंदे", "गंदी", "गन्दा", "गन्दे", "खराब", "ganda", "gande", "gandi", "kharab", "dirty"}


def _norm(text: str) -> str:
    return text.replace("\u093c", "").replace("\u0901", "\u0902").lower()


def _clauses(text: str) -> list[list[str]]:
    return [re.findall(r"[^\s\-–]+", c) for c in CLAUSE.split(_norm(f" {text} "))]


def _said(clauses: list[list[str]], words: set[str]) -> bool | None:
    """True if a word from `words` is said; False if only ever with a नहीं after it in the same clause; None if never."""
    found = None
    for c in clauses:
        for i, t in enumerate(c):
            if t in words:
                if not NEGATION & set(c[i + 1:]) and (i == 0 or c[i - 1] not in NEGATION_BEFORE):
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
    """Plain-code reading of a Hindi transcript (or typed message) into the same fields as the model, then the same validate().
    Only words that are actually said count; "पानी गंदा है" alone names no colour or smell, so it returns None."""
    clauses = _clauses(transcript)
    tokens = [t for c in clauses for t in c]
    colour = next((name for name, words in COLOUR_WORDS.items() if _said(clauses, words)), "not_said")
    illness = [name for name, words in ILLNESS_WORDS.items() if _said(clauses, words)]
    if any(({"पेट", "pet", "stomach"} & set(c)) and ({"दर्द", "dard", "pain", "ache"} & set(c)) and not NEGATION & set(c)
           for c in clauses):
        illness.append("stomach_pain")
    vulnerable = [name for name, words in VULNERABLE_WORDS.items() if illness and words & set(tokens)]
    return validate({"colour": colour, "smell": {True: "yes", False: "no", None: "not_said"}[_said(clauses, SMELL_WORDS)],
                     "since_days": _since(tokens), "illness": illness, "vulnerable": vulnerable})


def sounds_like_complaint(text: str) -> bool:
    """A typed message that says the water is dirty ("पानी गंदा है") but names no colour or smell: worth asking."""
    return _said(_clauses(text), DIRTY_WORDS) is True


def is_dirty(f: dict) -> bool:
    return f.get("colour") in DIRTY_COLOURS or f.get("smell") is True or bool(f.get("illness"))
