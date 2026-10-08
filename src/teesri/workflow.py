"""Step Functions glue: start a case (the execution is named by its incident id, so a retried stream record
can't start a second case) and complete its waiting steps: volunteer approval, ward office reply, check-ins."""
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from teesri import store, texts

log = logging.getLogger()

# Seconds. The demo clock is labelled on screen ("+2 days (demo clock)").
DEMO_CLOCK = {"approve_s": 1800, "ward_s": 7 * 86400, "checkin_s": 300, "round_gap_s": 60}
REAL_CLOCK = {"approve_s": 6 * 3600, "ward_s": 14 * 86400, "checkin_s": 86400, "round_gap_s": 12 * 3600}
_GONE = {"TaskTimedOut", "InvalidToken", "TaskDoesNotExist"}


def _sfn():
    return boto3.client("stepfunctions")


def start_case(inc_id: str) -> str | None:
    arn = os.environ.get("STATE_MACHINE_ARN")
    if not arn:
        return None
    clock = DEMO_CLOCK if os.environ.get("DEMO_CLOCK") == "1" else REAL_CLOCK
    try:
        out = _sfn().start_execution(stateMachineArn=arn, name=inc_id,
                                     input=json.dumps({"inc_id": inc_id, "clock": clock}))
        store.update_incident(inc_id, execution_arn=out["executionArn"])
        return out["executionArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ExecutionAlreadyExists":
            return None
        raise


def _complete(task_token: str, output: dict) -> bool:
    try:
        _sfn().send_task_success(taskToken=task_token, output=json.dumps(output))
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in _GONE:
            return False
        raise


def approve(hh_id: str, short: str, yes: bool) -> str:
    """The volunteer tapped हाँ, भेजें / अभी नहीं. Only the volunteer the card was sent to can answer."""
    tok = store.get_token(short)
    if not tok or tok["step"] != "approve" or tok.get("hh_id") != hh_id:
        return texts.EXPIRED
    if yes:  # recorded before the workflow moves on, so the broadcast's Cedar check can see it
        store.update_incident(tok["inc_id"], approved_by=hh_id, approved_ts=store.now_iso())
    if not _complete(tok["task_token"], {"approved": yes}):
        return texts.EXPIRED
    return texts.APPROVED_ACK if yes else texts.HELD_ACK


def answer_checkin(hh_id: str, short: str, clean: bool) -> str:
    """A home in the ring answered "पानी साफ़ है?". One answer per home per round; a नहीं ends the round at once."""
    tok = store.get_token(short)
    if not tok or tok["step"] != "checkin":
        return texts.EXPIRED
    inc = store.get_incident(tok["inc_id"])
    rnd = int(tok["round"])
    if not inc or hh_id not in inc.get("ring_hh", []) or int(inc.get("checkin_round", 0)) != rnd:
        return texts.EXPIRED
    if store.put_checkin(inc["inc_id"], rnd, hh_id, clean):
        if not clean or len(store.checkins(inc["inc_id"], rnd)) >= len(inc["ring_hh"]):
            _complete(tok["task_token"], {"ended": "not_clean" if not clean else "all_answered"})
    return texts.CHECKIN_THANKS


def ward_reply(inc_id: str, text: str) -> bool:
    """The ward office's reply (demo: console button / scenario CLI)."""
    inc = store.get_incident(inc_id) or {}
    tok = store.get_token(inc.get("ward_tok", "")) if inc.get("ward_tok") else None
    return bool(tok) and _complete(tok["task_token"], {"text": text})


def stop_all_cases() -> int:
    """Demo reset only: stop every running case so a fresh scenario starts clean."""
    arn = os.environ.get("STATE_MACHINE_ARN")
    if not arn:
        return 0
    running = _sfn().list_executions(stateMachineArn=arn, statusFilter="RUNNING", maxResults=100)["executions"]
    for ex in running:
        _sfn().stop_execution(executionArn=ex["executionArn"], cause="demo reset")
    return len(running)
