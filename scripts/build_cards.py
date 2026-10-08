"""The video's slide cards (shots 2, 3, 4, 13, 14) as 1920x1080 PNGs, every number read from video/slides-data.json.

Usage: .venv/bin/python scripts/build_cards.py [--mode agent|template] [--out video/cards]
  --mode template: the architecture card says what template mode runs (no Nova, no Strands agent on screen)
"""
import base64
import html
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARGS = sys.argv[1:]
MODE = ARGS[ARGS.index("--mode") + 1] if "--mode" in ARGS else "agent"
OUT = ROOT / (ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else "video/cards")
D = json.loads((ROOT / "video/slides-data.json").read_text())
E = html.escape

CSS = """
:root { --bg:#0f1419; --panel:#161d24; --line:#2a3540; --text:#e7edf2; --muted:#8a99a8; --red:#ef4444; --amber:#f59e0b;
        --green:#22c55e; --blue:#38bdf8; }
* { box-sizing:border-box; margin:0; }
body { width:1920px; height:1080px; background:var(--bg); color:var(--text); font-family:"Noto Sans","Noto Sans Devanagari",sans-serif;
       display:flex; flex-direction:column; justify-content:center; padding:0 160px; position:relative; overflow:hidden; }
.kicker { font-size:34px; color:var(--muted); letter-spacing:.5px; margin-bottom:28px; }
.big { font-size:118px; font-weight:700; line-height:1.05; }
.big .red { color:var(--red); }
.line { font-size:48px; line-height:1.35; margin-top:36px; max-width:1500px; }
.line b { color:var(--blue); }
.src { position:absolute; left:160px; bottom:70px; font-size:24px; color:var(--muted); max-width:1600px; }
.label { position:absolute; right:60px; top:50px; font-size:22px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:6px 16px; }
.hi { font-family:"Noto Sans Devanagari",sans-serif; }
.flow { display:flex; flex-wrap:wrap; align-items:center; gap:18px 14px; margin-top:20px; }
.box { background:var(--panel); border:2px solid var(--line); border-radius:16px; padding:18px 24px; font-size:34px; font-weight:600; }
.box small { display:block; font-size:22px; font-weight:400; color:var(--muted); margin-top:4px; }
.box.code { border-color:var(--green); } .box.ai { border-color:var(--blue); } .box.guard { border-color:var(--red); }
.arrow { font-size:40px; color:var(--muted); }
.legend { margin-top:40px; font-size:26px; color:var(--muted); display:flex; gap:40px; }
.legend span::before { content:""; display:inline-block; width:18px; height:18px; border-radius:5px; border:3px solid; margin-right:10px; vertical-align:-2px; }
.legend .c::before { border-color:var(--green); } .legend .a::before { border-color:var(--blue); } .legend .g::before { border-color:var(--red); }
.cost { font-size:220px; font-weight:700; color:var(--green); line-height:1; }
.bg { position:absolute; inset:0; background-size:cover; background-position:center; opacity:.22; }
.over { position:relative; }
.url { font-family:"JetBrains Mono",monospace; font-size:34px; color:var(--blue); margin-top:14px; }
.small { font-size:24px; color:var(--muted); margin-top:60px; line-height:1.6; }
"""


def arch() -> str:
    agent = MODE == "agent"
    boxes = [
        ("Telegram", "WhatsApp-ready adapter", ""), ("Lambda", "Function URL", "code"),
        ("S3 · Transcribe", "Hindi voice note", "ai"),
        *([("Nova 2 Lite", "fixed schema, code-checked", "ai")] if agent else [("3 buttons", "colour · smell · since when", "code")]),
        ("DynamoDB", "Streams", "code"), ("EventBridge Pipes", "new reports only", "code"),
        ("Tripwire", "3 homes · 250 m · 72 h", "code"), ("Step Functions", "one case, held for days", "code"),
        ("Strands agent" if agent else "Case steps", "brief · email · reply" if agent else "fixed templates", "ai" if agent else "code"),
        ("Cedar", "every action checked", "guard"), ("Polly · SES", "Hindi voice · ward email", "ai"),
    ]
    parts = []
    for i, (name, sub, cls) in enumerate(boxes):
        if i:
            parts.append('<span class="arrow">→</span>')
        parts.append(f'<div class="box {cls}">{E(name)}<small>{E(sub)}</small></div>')
    return (f'<div class="kicker">Serverless on AWS · one CDK stack · ap-south-1</div><div class="flow">{"".join(parts)}</div>'
            '<div class="legend"><span class="c">plain code, tested</span><span class="a">AI or speech</span>'
            '<span class="g">policy guard (fails closed)</span></div>'
            + ("" if agent else '<div class="src">Agent mode (Nova + Strands) is built and tested offline; this account\'s Bedrock quota is 0.</div>'))


CARDS = {
    "02-indore": f'''<div class="kicker">Indore · Bhagirathpura · Dec 2025</div>
        <div class="big">{E(D["indore_deaths"]["card"].split(" · ")[-1])}</div>
        <div class="line">A leaking pipe pulled sewage into the taps. People complained one by one.</div>
        <div class="src">{E(D["indore_deaths"]["value"])}: judicial commission, Sep 2026, as reported by ETV Bharat (report not public)</div>''',
    "03-title": '''<div class="big">Teesri Shikayat</div><div class="line hi" style="margin-top:10px;color:var(--muted)">तीसरी शिकायत · the third complaint</div>
        <div class="line">When three homes close together report dirty water, <b>everyone around them is warned</b>, and only the residents can close the case.</div>''',
    "04-mumbai": f'''<div class="kicker">Mumbai · Jan–Aug 2026</div>
        <div class="big"><span class="red">{E(D["mumbai_complaints"]["value"].split(" ")[0])}</span> dirty-water complaints</div>
        <div class="line">30 Sep 2026: BMC's new SOP asks for <b>immediate alerts to residents</b>.</div>
        <div class="line" style="font-size:36px;color:var(--muted)">B ward (Dongri): {E(D["b_ward_unfit"]["value"].split("%")[0])}% of water samples unfit, against {E(D["b_ward_unfit"]["value"].split(" vs ")[1].split(" (")[0])}</div>
        <div class="src">Free Press Journal, 1 Oct 2026</div>''',
    "13a-architecture": arch(),
    "13b-cost": f'''<div class="kicker">One real incident, measured</div><div class="cost">{E(D["cost_per_incident"]["card"])}</div>
        <div class="line">per incident: {E(D["cost_per_incident"]["detail"])}</div>
        <div class="src">Step Functions history + Lambda logs of a live run, priced with the AWS Pricing API (ap-south-1, on-demand, no free tier). Telegram messages are free.</div>''',
    "14-close": f'''<div class="bg" style="background-image:url('data:image/jpeg;base64,{base64.b64encode((ROOT / "docs/img/console-warned.jpg").read_bytes()).decode()}')"></div><div class="over">
        <div class="big" style="font-size:96px">Closed at the tap,<br>not on paper.</div>
        <div class="url" style="margin-top:50px">github.com/aryangorde6/teesri-shikayat</div>
        <div class="url">{E(D["live_url"]["value"])}</div>
        <div class="small">Not affiliated with BMC or any water board. Demo homes are simulated, except mine.<br>Demo channel: Telegram; WhatsApp plugs into the same adapter.</div></div>''',
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, body in CARDS.items():
            page.set_content(f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{body}</body>")
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(OUT / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
