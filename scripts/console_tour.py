"""Records the WEB shots (video slots 3, 7, 9-12): drives the console at 1920x1080 through the demo and saves a
video plus a beat sheet (seconds into the video for each beat) for the editor.

Demo actions go straight to /api/action with the console token read from SSM; the token is never typed into the page.
Usage: AWS_PROFILE=hackathon .venv/bin/python scripts/console_tour.py [--third stand-in|phone] [--out video/web-tour]
  --third stand-in (default): a simulated stand-in files the third report and answers "not clean"; real phones muted
  --third phone: waits for your phone's voice note, approval tap and "नहीं" (real recording run; quiet mode off)
"""
import json
import pathlib
import shutil
import sys
import time
import urllib.request

import boto3
from playwright.sync_api import sync_playwright

REGION = "ap-south-1"
ARGS = sys.argv[1:]
THIRD = ARGS[ARGS.index("--third") + 1] if "--third" in ARGS else "stand-in"
OUT = pathlib.Path(ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else "video/web-tour")

outputs = {o["OutputKey"]: o["OutputValue"] for o in boto3.client("cloudformation", region_name=REGION)
           .describe_stacks(StackName="Teesri")["Stacks"][0]["Outputs"]}
BASE = outputs["FunctionUrl"].rstrip("/")
TOKEN = boto3.client("ssm", region_name=REGION).get_parameter(
    Name="/teesri/console-token", WithDecryption=True)["Parameter"]["Value"]


def act(action: str, **kw) -> dict:
    req = urllib.request.Request(f"{BASE}/api/action", data=json.dumps({"action": action, **kw}).encode(),
                                 headers={"content-type": "application/json", "x-console-token": TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def state() -> dict:
    with urllib.request.urlopen(f"{BASE}/api/state", timeout=15) as r:
        return json.load(r)


def wait_status(*wanted: str, timeout: int = 600) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        inc = state()["incident"]
        if inc and inc["status"] in wanted:
            return inc
        time.sleep(2)
    raise TimeoutError(f"incident never reached {wanted}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    act("quiet", on=THIRD != "phone")
    act("reset")
    act("seed")
    act("volunteer", who="phone" if THIRD == "phone" else "sim")
    time.sleep(15)  # A's and B's reports pass through the stream and the tripwire (no alarm: only two homes)
    beats, t0 = [], None

    def beat(name: str) -> None:
        beats.append({"t": round(time.time() - t0, 1), "beat": name})
        print(f"{beats[-1]['t']:>6}s  {name}", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                  record_video_dir=str(OUT / "raw"), record_video_size={"width": 1920, "height": 1080})
        page = ctx.new_page()
        t0 = time.time()
        page.goto(f"{BASE}/console")
        page.click("text=Phone wall")
        page.wait_for_timeout(4000)
        beat("map + wall: two neighbours already reported (A, B red)")

        act("building")
        page.wait_for_selector("#toast", state="visible", timeout=60000)
        beat("one building's tank: no alarm (toast)")
        page.wait_for_timeout(5000)

        if THIRD == "phone":
            beat("waiting for your voice note (the third report)")
        else:
            act("stand_in")
        page.wait_for_selector("#ringcard", state="visible", timeout=600000)
        beat("the third report: ring snaps, '3 homes · 212 m · 71 h', ~N people")
        page.wait_for_timeout(7000)

        wait_status("AWAITING_APPROVAL")
        page.click("text=Case")
        beat("case agent's Hindi brief; volunteer asked")
        page.wait_for_timeout(5000)
        if THIRD != "phone":
            act("approve")
        page.click("text=Phone wall")
        wait_status("WARNED", "WARD_NOTIFIED", "AWAITING_WARD")
        beat("everyone in the ring warned: '20 of 23 never complained'")
        page.wait_for_timeout(8000)

        wait_status("AWAITING_WARD")
        page.click("text=Test inbox")
        beat("ward office email: no names or numbers")
        page.wait_for_timeout(6000)
        page.click("text=Safety")
        beat("Safety tab: every action checked by Cedar")
        page.wait_for_timeout(4000)

        act("ward_reply", text="Resolved")
        page.wait_for_selector(".evt.DENY", timeout=120000)
        beat("+2 days: ward office says 'Resolved' -> close_case DENY (only residents can close)")
        page.wait_for_timeout(7000)

        wait_status("CHECKING")
        page.click("text=Phone wall")
        beat("residents asked: पानी साफ़ है?")
        page.wait_for_timeout(3000)
        act("answer", home="C", clean=True)
        if THIRD == "phone":
            beat("waiting for your नहीं")
        else:
            act("answer", home="me", clean=False)
        wait_status("REOPENED", "AWAITING_WARD")
        page.click("text=Case")
        beat("a tap says no -> REOPENED")
        page.wait_for_timeout(7000)

        page.click("text=Indore replay")
        beat("Indore replay (reconstruction): ~10 days of warning")
        page.wait_for_timeout(9000)
        video = page.video.path()
        ctx.close()
        browser.close()

    shutil.move(video, OUT / "web-tour.webm")
    shutil.rmtree(OUT / "raw", ignore_errors=True)
    (OUT / "beats.json").write_text(json.dumps(beats, ensure_ascii=False, indent=1))
    act("quiet", on=False)
    print(f"saved {OUT / 'web-tour.webm'} and beats.json; quiet mode is off again")


if __name__ == "__main__":
    main()
