"""Points the Telegram bot at the deployed Function URL. Reads secrets from SSM; never prints them.

Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/set_webhook.py
"""
import json
import urllib.request

import boto3

REGION = "ap-south-1"


def main() -> None:
    ssm = boto3.client("ssm", region_name=REGION)
    token, secret = (
        ssm.get_parameter(Name=n, WithDecryption=True)["Parameter"]["Value"]
        for n in ("/teesri/telegram/bot-token", "/teesri/telegram/webhook-secret")
    )
    outputs = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]
    url = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "FunctionUrl").rstrip("/") + "/tg"

    payload = {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print("setWebhook:", json.load(r).get("description"))
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10) as r:
        info = json.load(r)["result"]
    print("webhook url:", info.get("url"), "| pending:", info.get("pending_update_count"), "| last error:", info.get("last_error_message"))


if __name__ == "__main__":
    main()
