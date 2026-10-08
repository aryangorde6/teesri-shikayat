"""The ward office email. Always stored (the console's test inbox shows it); also sent with SES when an
inbox is configured in SSM (/teesri/ward-inbox and /teesri/mail-from, both SES-verified)."""
import logging
import os

import boto3

from teesri import store

log = logging.getLogger()
CONSOLE_INBOX = "console-test-inbox"


def _param(name: str) -> str | None:
    try:
        return boto3.client("ssm").get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return None


def ward_inbox() -> str:
    return (os.environ.get("WARD_INBOX_PARAM") and _param(os.environ["WARD_INBOX_PARAM"])) or CONSOLE_INBOX


def allowlisted(recipient: str) -> bool:
    return recipient in {CONSOLE_INBOX, ward_inbox()}


def send(inc_id: str, to: str, subject: str, body: str) -> str:
    """Stores the email on the incident; sends it with SES when `to` is a real (configured) inbox."""
    via = "stored"
    sender = os.environ.get("MAIL_FROM_PARAM") and _param(os.environ["MAIL_FROM_PARAM"])
    if to != CONSOLE_INBOX and sender:
        boto3.client("sesv2").send_email(
            FromEmailAddress=sender, Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}})
        via = "ses"
    ts = store.now_iso()
    store.table().put_item(Item={"PK": f"INC#{inc_id}", "SK": f"MAIL#{ts}", "to": to, "subject": subject,
                                 "body": body, "via": via, "ts": ts})
    return via
