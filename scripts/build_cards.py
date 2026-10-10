"""The video's motion cards (shots 2, 3, 4, 13, 14) as 1920x1080 mp4s, every number read from video/slides-data.json.

Each card is one html page whose animation is a function of time: window.seek(t) sets every element, and each frame is
a Chromium screenshot piped into ffmpeg. Frame-exact and repeatable, no screen recording. The cue times in the
timelines are the narration's (video/out/voice.srt, shot-relative), so the numbers land on the spoken word.
A still of each card goes next to its mp4 (<name>.png) for checking.

Usage: .venv/bin/python scripts/build_cards.py [--mode agent|template] [--out video/cards] [--only 02-indore]
  --mode template: the architecture card says what template mode runs (no Gemma, no Strands agent on screen)
"""
import base64
import html
import json
import math
import pathlib
import subprocess
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARGS = sys.argv[1:]
MODE = ARGS[ARGS.index("--mode") + 1] if "--mode" in ARGS else "agent"
OUT = ROOT / (ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else "video/cards")
ONLY = ARGS[ARGS.index("--only") + 1] if "--only" in ARGS else None
AT = [float(x) for x in ARGS[ARGS.index("--at") + 1].split(",")] if "--at" in ARGS else None
D = json.loads((ROOT / "video/slides-data.json").read_text())
E = html.escape
FPS = 30
# the ring as the map shows it at the cut into shot 3 (web tour crop [14, 250, 1062, 597] scaled to 1920x1080)
RING = {"cx": 958, "cy": 555, "r": 402, "dots": [(788, 582, 13), (1127, 582, 13), (1028, 540, 16)]}

CSS = """
:root { --ink:#0a0f14; --ink2:#111922; --line:rgba(255,255,255,.11); --paper:#f3efe7; --mute:#8d98a5; --dim:#5b6672;
        --signal:#ffb020; --danger:#ef4444; --water:#5cc8dc; --ok:#34d399;
        --sans:"Ubuntu Sans","Noto Sans","Noto Sans Devanagari",sans-serif; --mono:"Ubuntu Sans Mono","DejaVu Sans Mono",monospace;
        --deva:"Noto Serif Devanagari",serif; }
* { box-sizing:border-box; margin:0; }
body { width:1920px; height:1080px; overflow:hidden; background:var(--ink); color:var(--paper); font-family:var(--sans);
       position:relative; }
.abs { position:absolute; }
.bgfx { position:absolute; inset:0; background:radial-gradient(1300px 900px at 15% 8%, #18232e 0%, rgba(10,15,20,0) 62%),
        radial-gradient(1000px 800px at 92% 105%, #131c25 0%, rgba(10,15,20,0) 60%); }
.grid { position:absolute; inset:-60px; background-image:radial-gradient(rgba(255,255,255,.075) 1.3px, transparent 1.6px);
        background-size:30px 30px; }
.vig { position:absolute; inset:0; background:radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 58%, rgba(0,0,0,.5) 100%); }
.kick { font-family:var(--mono); font-size:24px; letter-spacing:.2em; text-transform:uppercase; color:var(--mute); }
.kick i { display:inline-block; width:11px; height:11px; border-radius:50%; background:var(--signal); margin-right:16px; vertical-align:3px; }
.cond { font-stretch:75%; font-weight:800; letter-spacing:-.005em; }
.ln { display:block; overflow:hidden; padding-bottom:.06em; }
.ln > span { display:inline-block; transform:translateY(calc((1 - var(--o, 0)) * 112%)); }
.a { opacity:var(--o, 0); transform:translateY(calc((1 - var(--o, 0)) * 26px)); }
.src { position:absolute; left:140px; bottom:150px; font-family:var(--mono); font-size:19px; color:var(--dim); max-width:1640px;
       line-height:1.55; }
"""

# the animation engine: K(selector, css variable, [[t, value], ...]) tracks, eased between keys; hooks for the rest
ENGINE = """
const EZ = {out: p => 1 - Math.pow(1 - p, 4), io: p => p < .5 ? 8 * p ** 4 : 1 - Math.pow(-2 * p + 2, 4) / 2, lin: p => p,
            back: p => { const c = 1.6; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); }};
const TR = [], HK = [];
function K(sel, v, keys, ez = 'out') {
  document.querySelectorAll(sel).forEach((el, i) => TR.push({el, v, keys: typeof keys === 'function' ? keys(i, el) : keys, ez}));
}
function val(keys, t, ez) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1] = keys[i];
    if (t <= t1) { const [t0, v0] = keys[i - 1]; return v0 + (v1 - v0) * EZ[ez]((t - t0) / (t1 - t0)); }
  }
  return keys[keys.length - 1][1];
}
const IN = (a, d = .7) => [[a, 0], [a + d, 1]];
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
window.seek = t => { for (const r of TR) r.el.style.setProperty(r.v, val(r.keys, t, r.ez)); for (const h of HK) h(t); };
"""


def img(path: pathlib.Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def map_still(name: str, beat: str, offset: float) -> pathlib.Path:
    """One frame of the web tour, cropped like the edl's map zoom, so a card can cut on the map's own geometry."""
    out = OUT / f"_{name}.jpg"
    beats = {b["beat"]: b["t"] for b in json.loads((ROOT / "video/web-tour/beats.json").read_text())}
    t = next(v for k, v in beats.items() if beat in k) + offset
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(ROOT / "video/web-tour/web-tour.webm"),
                    "-frames:v", "1", "-vf", "crop=1062:597:14:250,scale=1920:1080", "-q:v", "2", str(out)], check=True)
    return out


def indore() -> tuple:
    deaths = D["indore_deaths"]["card"].split(" · ")[-1].split(" ")[0]
    # an illustrative street grid: a pipe draws in, the leak shows, then complaints appear one at a time, never joined
    streets = "".join(f'<path d="{d}" class="st"/>' for d in [
        "M-20 140 L920 210", "M-20 420 L920 380", "M-20 650 L920 690", "M150 -20 L210 780", "M430 -20 L400 780",
        "M690 -20 L720 780", "M-20 300 L300 260 L560 290", "M520 520 L920 540"])
    dots = [(250, 330), (540, 210), (330, 560), (640, 470), (150, 520), (480, 650), (760, 300)]
    cps = "".join(f'<g class="cp" style="--x:{x}px;--y:{y}px"><circle class="pl" r="16"/><circle class="dt" r="11"/></g>'
                  for x, y in dots)
    body = f"""
<style>
.map {{ left:960px; top:170px; width:880px; height:740px; overflow:visible;
        opacity:calc(1 - .55 * var(--dim, 0)); }}
.st {{ fill:none; stroke:rgba(255,255,255,.09); stroke-width:14; stroke-linecap:round; }}
.pipe {{ fill:none; stroke:var(--water); stroke-width:6; stroke-linecap:round; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--d, 0));
         opacity:.85; }}
.leak {{ fill:#9a6a35; opacity:var(--o, 0); }}
.leakr {{ fill:none; stroke:#b98146; stroke-width:3; }}
.cp {{ transform:translate(var(--x), var(--y)) scale(var(--o, 0)); }}
.cp .dt {{ fill:var(--paper); }}
.cp .pl {{ fill:none; stroke:var(--paper); stroke-width:2; transform:scale(calc(1 + 1.6 * var(--p, 0))); opacity:calc(.7 * (1 - var(--p, 0))); }}
.maplab {{ right:80px; top:128px; font-family:var(--mono); font-size:18px; letter-spacing:.14em; color:var(--dim); }}
.col {{ left:140px; top:220px; width:780px; }}
.h1 {{ font-size:172px; line-height:.98; margin-top:34px; opacity:calc(1 - var(--x, 0)); transform:translateY(calc(var(--x, 0) * -30px)); }}
.sub {{ font-size:44px; color:var(--mute); margin-top:34px; }}
.subw {{ opacity:calc(1 - var(--x, 0)); }}
.death {{ left:140px; top:330px; display:flex; align-items:baseline; gap:30px; opacity:var(--o, 0);
          transform:scale(calc(1.07 - .07 * var(--o, 0))); transform-origin:0 70%; }}
.death .n {{ font-size:400px; line-height:.9; color:var(--danger); }}
.death .w {{ font-size:96px; font-weight:700; }}
</style>
<div class="bgfx"></div><div class="grid"></div>
<svg class="abs map" viewBox="0 0 880 740">{streets}
  <path class="pipe" pathLength="1" d="M-20 420 L400 382 L410 120 L700 90"/>
  <circle class="leakr" cx="404" cy="300" r="14"/><circle class="leak" cx="404" cy="300" r="12"/>
  {cps}</svg>
<div class="abs maplab a ml">ILLUSTRATIVE · EACH DOT A COMPLAINT, FILED ALONE</div>
<div class="abs col">
  <div class="kick a k"><i></i>Indore · Bhagirathpura · Dec 2025</div>
  <div class="h1 cond"><span class="ln"><span class="l">Sewage</span></span><span class="ln"><span class="l">in the taps.</span></span></div>
  <div class="subw"><div class="sub a s">People complained one by one.</div></div>
</div>
<div class="abs death"><span class="n cond">{E(deaths)}</span><span class="w">deaths</span></div>
<div class="src a srcl">{E(D["indore_deaths"]["value"])}: judicial commission, Sep 2026, as reported by ETV Bharat (report not public).</div>
<div class="vig"></div>"""
    js = """
K('.k', '--o', IN(.3)); K('.l', '--o', (i) => IN(.65 + i * .18, .9));
K('.pipe', '--d', [[1.0, 0], [3.3, 1]], 'io'); K('.leak', '--o', IN(3.2, .4));
K('.s', '--o', IN(4.85)); K('.ml', '--o', IN(5.0));
K('.cp', '--o', (i) => IN(4.95 + i * .2, .45), 'back'); K('.cp .pl', '--p', (i) => [[4.95 + i * .2, 0], [5.95 + i * .2, 1]], 'out');
K('.h1, .subw', '--x', [[6.55, 0], [6.9, 1]], 'io'); K('.map', '--dim', [[6.6, 0], [7.1, 1]]);
K('.death', '--o', IN(6.72, .45)); K('.srcl', '--o', IN(7.0));
const lr = document.querySelector('.leakr'), grid = document.querySelector('.grid'), map = document.querySelector('.map');
HK.push(t => {
  const p = t < 3.2 ? 0 : ((t - 3.2) % 1.3) / 1.3;
  lr.setAttribute('r', 12 + 34 * p); lr.style.opacity = t < 3.2 ? 0 : .8 * (1 - p);
  grid.style.transform = `translate(${-t * 3}px, ${-t * 1.5}px)`;
  map.style.transform = `scale(${1 + t * .006})`;
});"""
    return body, js


def title() -> tuple:
    still = map_still("ring", "ring snaps", 0.5)
    c = RING
    dots = "".join(f'<g class="d"><circle class="dp" cx="{x}" cy="{y}" r="{r + 8}"/><circle cx="{x}" cy="{y}" r="{r}" class="dd"/>'
                   f'</g>' for x, y, r in c["dots"])
    (x1, y1, _), (x2, y2, _), (x3, y3, _) = c["dots"]
    body = f"""
<style>
.still {{ inset:0; width:1920px; height:1080px; opacity:var(--o, 0); }}
.motif {{ left:0; top:0; width:1920px; height:1080px; overflow:visible; }}
.ring {{ fill:rgba(239,68,68,.07); stroke:var(--danger); stroke-width:5; }}
.dd {{ fill:var(--danger); }}
.d:last-child .dd {{ stroke:#61b8ff; stroke-width:4; }}
.d {{ opacity:var(--o, 0); }}
.dp {{ fill:none; stroke:var(--danger); stroke-width:2; opacity:0; }}
.tie {{ fill:none; stroke:var(--paper); stroke-width:2; stroke-dasharray:6 8; opacity:calc(.55 * var(--o, 0)); }}
.word {{ left:0; width:1920px; top:640px; text-align:center; opacity:calc(1 - var(--x, 0));
         transform:scale(calc(1 + .05 * var(--x, 0))); filter:blur(calc(var(--x, 0) * 6px)); }}
.word .nm {{ font-size:200px; line-height:.95; }}
.word .row {{ display:flex; justify-content:center; align-items:baseline; gap:34px; margin-top:22px; }}
.word .hi {{ font-family:var(--deva); font-size:62px; color:var(--paper); }}
.word .bar {{ width:2px; height:44px; background:var(--line); }}
.word .en {{ font-family:var(--mono); font-size:26px; letter-spacing:.24em; color:var(--signal); text-transform:uppercase; }}
.bgw {{ opacity:calc(1 - var(--x, 0)); }}
</style>
<div class="bgw"><div class="bgfx"></div><div class="grid"></div></div>
<img class="abs still" src="{img(still)}">
<svg class="abs motif" viewBox="0 0 1920 1080"><g class="mg">
  <circle class="ring" cx="{c['cx']}" cy="{c['cy']}" r="0"/>
  <path class="tie" d="M{x1} {y1} L{x3} {y3} L{x2} {y2} Z"/>{dots}</g></svg>
<div class="abs word">
  <div class="nm cond"><span class="ln"><span class="l">Teesri Shikayat</span></span></div>
  <div class="row"><span class="hi a h">तीसरी शिकायत</span><span class="bar a b"></span><span class="en a e">the third complaint</span></div>
</div>"""
    js = f"""
K('.d', '--o', (i) => IN(.15 + i * .32, .3)); K('.tie', '--o', [[1.05, 0], [1.55, 1], [3.9, 1], [4.4, 0]]);
K('.l', '--o', IN(.6, 1.0)); K('.h', '--o', IN(1.35)); K('.b', '--o', IN(1.6)); K('.e', '--o', IN(2.55));
K('.word, .bgw', '--x', [[3.95, 0], [4.55, 1]], 'io'); K('.still', '--o', [[4.25, 0], [4.95, 1]], 'io');
const ring = document.querySelector('.ring'), mg = document.querySelector('.mg'), pulses = document.querySelectorAll('.dp');
const CX = {c['cx']}, CY = {c['cy']}, R = {c['r']}, S0 = .5, Y0 = 300;
HK.push(t => {{
  // the motif sits small above the name, then grows onto the map's own ring for the cut (t = 5)
  const m = EZ.io(clamp((t - 3.85) / 1.1)), s = S0 + (1 - S0) * m, cy = Y0 + (CY - Y0) * m;
  mg.setAttribute('transform', `translate(${{960 + (CX - 960) * m}} ${{cy}}) scale(${{s}}) translate(${{-CX}} ${{-CY}})`);
  ring.setAttribute('r', R * EZ.out(clamp((t - 1.1) / 1.0)));
  ring.style.strokeWidth = 5 / s;
  pulses.forEach((p, i) => {{ const q = clamp((t - .15 - i * .32) / .9); p.setAttribute('r', ({c['dots'][0][2]} + 8) * (1 + 1.4 * q));
    p.style.opacity = q > 0 && q < 1 ? .8 * (1 - q) : 0; }});
}});"""
    return body, js


def mumbai() -> tuple:
    n = int(D["mumbai_complaints"]["value"].split(" ")[0].replace(",", ""))
    unfit = D["b_ward_unfit"]["value"]
    body = f"""
<style>
.col {{ left:140px; top:200px; width:860px; }}
.num {{ font-size:300px; line-height:.92; color:var(--signal); margin-top:30px; font-variant-numeric:tabular-nums; }}
.lab {{ font-size:58px; font-weight:700; margin-top:6px; }}
.q {{ margin-top:64px; padding-left:34px; position:relative; }}
.q::before {{ content:""; position:absolute; left:0; top:4px; width:6px; height:calc(var(--h, 0) * 100%); background:var(--signal);
             border-radius:3px; }}
.q .t {{ font-size:54px; font-weight:600; line-height:1.15; }}
.q .by {{ font-family:var(--mono); font-size:22px; letter-spacing:.16em; color:var(--mute); margin-top:16px; text-transform:uppercase; }}
canvas {{ left:1060px; top:226px; }}
.cap {{ left:1060px; top:810px; font-family:var(--mono); font-size:19px; letter-spacing:.12em; color:var(--mute); line-height:1.7;
        text-transform:uppercase; }}
.cap b {{ color:var(--paper); font-weight:500; }}
</style>
<div class="bgfx"></div><div class="grid"></div>
<div class="abs col">
  <div class="kick a k"><i></i>Mumbai · Jan–Aug 2026</div>
  <div class="num cond ct">0</div>
  <div class="lab a lb">dirty-water complaints</div>
  <div class="q qq"><div class="t a qt">“Immediate alerts to residents.”</div><div class="by a qb">BMC standard operating procedure · 30 Sep 2026</div></div>
</div>
<canvas class="abs" width="740" height="560"></canvas>
<div class="abs cap a cp">Each dot is one complaint<br><b>B ward (Dongri)</b>: {E(unfit.split("%")[0])}% of water samples unfit,<br>against {E(unfit.split(" vs ")[1].split(" (")[0])}</div>
<div class="src a srcl">Free Press Journal, 1 Oct 2026</div>
<div class="vig"></div>"""
    js = f"""
const N = {n}, COLS = 46, ROWS = Math.ceil(N / COLS), P = 16;
K('.k', '--o', IN(.3)); K('.lb', '--o', IN(.9)); K('.qq', '--h', [[4.3, 0], [4.8, 1]], 'io'); K('.qt', '--o', IN(4.4));
K('.qb', '--o', IN(4.9)); K('.cp', '--o', IN(3.0)); K('.srcl', '--o', IN(1.2));
const ct = document.querySelector('.ct'), cv = document.querySelector('canvas'), g = cv.getContext('2d');
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const order = [...Array(COLS * ROWS).keys()].map(i => [rnd(), i]).sort((a, b) => a[0] - b[0]).map(x => x[1]).slice(0, N);
const lit = new Float32Array(COLS * ROWS).fill(-1); order.forEach((c, k) => lit[c] = k);
HK.push(t => {{
  const p = EZ.out(clamp((t - .6) / 2.4)), k = Math.round(N * p);
  ct.textContent = k.toLocaleString('en-IN');
  g.clearRect(0, 0, cv.width, cv.height);
  for (let i = 0; i < COLS * ROWS; i++) {{
    const x = (i % COLS) * P + 6, y = Math.floor(i / COLS) * P + 6;
    const on = lit[i] >= 0 && lit[i] < k;
    g.fillStyle = on ? 'rgba(255,176,32,.9)' : 'rgba(255,255,255,.07)';
    g.beginPath(); g.arc(x, y, on ? 4.6 : 3.2, 0, 7); g.fill();
  }}
  document.querySelector('.grid').style.transform = `translate(${{-t * 3}}px, ${{-t * 1.5}}px)`;
}});"""
    return body, js


def arch() -> tuple:
    agent = MODE == "agent"
    # (row, col, name, sub, kind): a serpentine, listen left to right, detect right to left, act left to right
    nodes = [
        (0, 0, "Telegram", "WhatsApp-ready adapter", "code"), (0, 1, "Lambda", "Function URL", "code"),
        (0, 2, "S3 · Transcribe", "Hindi voice note", "ai"),
        (0, 3, *(("Gemma 4 · our EC2", "open model, code-checked", "ai") if agent else
                 ("Keyword reader", "Hindi words → same fields", "code"))),
        (1, 3, "DynamoDB", "Streams", "code"), (1, 2, "EventBridge Pipes", "new reports only", "code"),
        (1, 1, "Tripwire", "3 homes · 250 m · 72 h", "code"), (1, 0, "Step Functions", "one case, held for days", "code"),
        (2, 0, *(("Strands agent", "brief · email · reply", "ai") if agent else ("Case steps", "fixed templates", "code"))),
        (2, 1, "Cedar", "every action checked", "guard"), (2, 2, "Polly · SES", "Hindi voice · ward email", "ai"),
    ]
    X0, NW, GAP, NH, YS = 160, 355, 60, 124, [250, 490, 730]
    pos = [(X0 + c * (NW + GAP), YS[r]) for r, c, *_ in nodes]
    boxes = "".join(f'<div class="node {k}" style="left:{x}px;top:{y}px"><b><i></i>{E(nm)}</b><small>{E(sb)}</small></div>'
                    for (x, y), (_, _, nm, sb, k) in zip(pos, nodes))
    links = []
    for i in range(len(nodes) - 1):
        (xa, ya), (xb, yb) = pos[i], pos[i + 1]
        if ya == yb:  # same row: edge to edge
            y = ya + NH / 2
            a, b = (xa + NW + 10, xb - 10) if xb > xa else (xa - 10, xb + NW + 10)
            links.append(f"M{a} {y} L{b} {y}")
        else:  # down to the next row
            x = xa + NW / 2
            links.append(f"M{x} {ya + NH + 10} L{x} {yb - 10}")
    paths = "".join(f'<path class="ln{i}" pathLength="1" d="{d}"/>' for i, d in enumerate(links))
    lanes = "".join(f'<div class="abs lane a" style="left:{X0}px;top:{y - 40}px">{n}</div>'
                    for y, n in zip(YS, ["01 · Listen", "02 · Detect", "03 · Act"]))
    note = ("Bedrock quota on this account is 0, so the model is ours: Gemma 4 E4B in llama.cpp on one EC2 Graviton4 "
            "instance, no inbound ports (requests over SQS). Nova plugs into the same code." if agent else
            "Template mode: the case steps use fixed wording when the model instance is off.")
    body = f"""
<style>
.node {{ position:absolute; width:{NW}px; height:{NH}px; border-radius:20px; background:#111922; border:1.5px solid var(--line);
         padding:22px 26px; --hl:0;
         opacity:calc(var(--o, 0) * (1 - .7 * var(--gd, 0) * (1 - var(--hl))));
         transform:translateY(calc((1 - var(--o, 0)) * 22px)) scale(calc(1 + .035 * var(--hl)));
         box-shadow:0 0 0 calc(var(--hl) * 2px) var(--signal), 0 0 calc(var(--hl) * 60px) rgba(255,176,32,calc(var(--hl) * .35)),
                    0 18px 40px rgba(0,0,0,.35); }}
.node b {{ display:block; font-size:30px; font-weight:700; white-space:nowrap; }}
.node small {{ display:block; font-size:21px; color:var(--mute); margin-top:8px; white-space:nowrap; }}
.node i {{ display:inline-block; width:12px; height:12px; border-radius:50%; background:#c9d1d9; margin-right:12px; vertical-align:4px; }}
.node.ai i {{ background:var(--water); }} .node.guard i {{ background:var(--danger); }}
svg.links {{ left:0; top:0; width:1920px; height:1080px; }}
.links path {{ fill:none; stroke:rgba(255,255,255,.28); stroke-width:2.5; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--d, 0));
 }}
.links path.done {{ marker-end:url(#ah); }}
.links path.hot {{ stroke:var(--signal); }}
.pulse {{ fill:var(--signal); }}
.lane {{ font-family:var(--mono); font-size:19px; letter-spacing:.2em; text-transform:uppercase; color:var(--dim); }}
.legend {{ right:160px; top:126px; display:flex; gap:34px; font-size:21px; color:var(--mute); }}
.legend span::before {{ content:""; display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:12px;
                       vertical-align:1px; background:#c9d1d9; }}
.legend .ai::before {{ background:var(--water); }} .legend .guard::before {{ background:var(--danger); }}
.note {{ left:{X0 + 3 * (NW + GAP)}px; top:{YS[2] - 4}px; width:{NW}px; font-family:var(--mono); font-size:17px; line-height:1.55;
         color:var(--dim); }}
</style>
<div class="bgfx"></div><div class="grid"></div>
<div class="abs kick a k" style="left:{X0}px;top:122px"><i></i>On AWS · one CDK stack · ap-south-1</div>
<div class="abs legend a lg"><span>plain code, tested</span><span class="ai">AI or speech</span><span class="guard">policy guard, fails closed</span></div>
{lanes}
<svg class="abs links" viewBox="0 0 1920 1080"><defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7"
  markerHeight="7" orient="auto-start-reverse"><path d="M0 1 L9 5 L0 9 z" fill="rgba(255,255,255,.45)" stroke="none"/></marker></defs>
  {paths}<circle class="pulse" r="7" cx="-50" cy="-50"/></svg>
{boxes}
<div class="abs note a nt">{E(note)}</div>
<div class="vig"></div>"""
    # cues (shot-relative): "Step Functions holds each case for days" 3.57, "DynamoDB streams feed the tripwire" ~5.9,
    # "and Polly speaks Hindi" ~8.2; the same moments the old spotlights used
    js = """
const nodes = document.querySelectorAll('.node');
K('.k', '--o', IN(.2)); K('.lg', '--o', IN(.5)); K('.lane', '--o', (i) => IN(.4 + i * .8)); K('.nt', '--o', IN(2.8));
K('.node', '--o', (i) => IN(.45 + i * .21, .55));
K('.links path', '--d', (i) => [[.62 + i * .21, 0], [.95 + i * .21, 1]], 'io');
document.body.style.setProperty('--gd', 0);
K('body', '--gd', [[3.3, 0], [3.75, 1]]);
const HL = {7: [[3.35, 0], [3.8, 1], [5.7, 1], [6.05, 0]], 4: [[5.8, 0], [6.2, 1], [8.0, 1], [8.3, 0]],
            5: [[6.05, 0], [6.45, 1], [8.0, 1], [8.3, 0]], 6: [[6.3, 0], [6.7, 1], [8.0, 1], [8.3, 0]], 10: [[8.05, 0], [8.5, 1]]};
for (const [i, keys] of Object.entries(HL)) TR.push({el: nodes[i], v: '--hl', keys, ez: 'out'});
const hot = [document.querySelector('.ln4'), document.querySelector('.ln5')], pulse = document.querySelector('.pulse');
HK.push(t => {
  hot.forEach(p => p.classList.toggle('hot', t > 6.0 && t < 8.2));
  document.querySelectorAll('.links path').forEach(p => p.classList.toggle('done', parseFloat(p.style.getPropertyValue('--d')) > .97));
  // a report travelling DynamoDB -> Pipes -> Tripwire
  const q = clamp((t - 6.1) / 1.8);
  if (q > 0 && q < 1) { const seg = q < .5 ? hot[0] : hot[1], f = (q % .5) * 2, L = seg.getTotalLength(), pt = seg.getPointAtLength(f * L);
    pulse.setAttribute('cx', pt.x); pulse.setAttribute('cy', pt.y); } else pulse.setAttribute('cx', -50);
  document.querySelector('.grid').style.transform = `translate(${-t * 3}px, ${-t * 1.5}px)`;
});"""
    return body, js


def cost() -> tuple:
    c = D["cost_per_incident"]
    chips = "".join(f'<span class="chip a">{E(x)}</span>' for x in c["detail"].split(", "))
    # 23 warned homes, sunflower-packed in a ring: the same picture the map shows
    homes = int(D["enrolled_in_ring"]["value"].split(" ")[0])
    pts = []
    for i in range(homes):
        r, a = 225 * ((i + .5) / homes) ** .5, i * 2.39996
        pts.append(f'<circle class="h" cx="{1440 + r * math.cos(a):.1f}" cy="{520 + r * math.sin(a):.1f}" r="12"/>')
    body = f"""
<style>
.col {{ left:140px; top:220px; }}
.big {{ font-size:400px; line-height:.86; margin-top:26px; opacity:var(--o, 0); transform:scale(calc(1.06 - .06 * var(--o, 0)));
        transform-origin:0 80%; }}
.big .r {{ color:var(--signal); margin-right:8px; }}
.per {{ font-size:64px; font-weight:700; margin-top:18px; }}
.chips {{ margin-top:40px; display:flex; gap:16px; }}
.chip {{ font-family:var(--mono); font-size:24px; letter-spacing:.06em; border:1.5px solid var(--line); border-radius:999px;
         padding:10px 22px; color:var(--paper); background:rgba(255,255,255,.03); }}
svg.ring {{ left:0; top:0; width:1920px; height:1080px; }}
.rg {{ fill:rgba(239,68,68,.06); stroke:var(--danger); stroke-width:4; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--d, 0)); }}
.h {{ fill:var(--signal); opacity:var(--o, 0); }}
.rl {{ left:1180px; top:840px; width:520px; text-align:center; font-family:var(--mono); font-size:19px; letter-spacing:.14em;
       color:var(--mute); text-transform:uppercase; }}
</style>
<div class="bgfx"></div><div class="grid"></div>
<svg class="abs ring" viewBox="0 0 1920 1080"><circle class="rg" pathLength="1" cx="1440" cy="520" r="262"
  transform="rotate(-90 1440 520)"/>{"".join(pts)}</svg>
<div class="abs rl a rla">{homes} homes warned, one incident</div>
<div class="abs col">
  <div class="kick a k"><i></i>One real incident, measured</div>
  <div class="big cond bg"><span class="r">₹</span>{E(c["card"].lstrip("₹"))}</div>
  <div class="per a p">per incident</div>
  <div class="chips">{chips}</div>
</div>
<div class="src a srcl">Step Functions history + Lambda logs of a live run, priced with the AWS Pricing API (ap-south-1, on-demand,
no free tier). Telegram messages are free. The model instance is extra: $0.43/h while on; it stops itself when idle.</div>
<div class="vig"></div>"""
    js = """
K('.k', '--o', IN(.15)); K('.bg', '--o', IN(.42, .5)); K('.p', '--o', IN(.95)); K('.chip', '--o', (i) => IN(1.5 + i * .18));
K('.rg', '--d', [[.5, 0], [1.6, 1]], 'io'); K('.h', '--o', (i) => IN(1.0 + i * .05, .3)); K('.rla', '--o', IN(1.9));
K('.srcl', '--o', IN(1.4));
HK.push(t => { document.querySelector('.grid').style.transform = `translate(${-t * 3}px, ${-t * 1.5}px)`; });"""
    return body, js


def close() -> tuple:
    still = map_still("warned", "everyone in the ring warned", 9)
    repo = "github.com/aryangorde6/teesri-shikayat"
    body = f"""
<style>
.still {{ left:0; top:0; width:1920px; height:1080px; filter:saturate(.75) brightness(.55); transform-origin:{RING['cx']}px {RING['cy']}px; }}
.shade {{ inset:0; background:linear-gradient(90deg, rgba(10,15,20,.96) 0%, rgba(10,15,20,.88) 38%, rgba(10,15,20,.35) 75%,
          rgba(10,15,20,.25) 100%); opacity:calc(.35 + .65 * var(--o, 0)); }}
svg.w {{ left:0; top:0; width:1920px; height:1080px; }}
.wave {{ fill:none; stroke:var(--signal); stroke-width:3; }}
.col {{ left:140px; top:210px; width:1640px; }}
.h1 {{ font-size:156px; line-height:.98; margin-top:30px; }}
.h1 .ln:last-child span {{ color:var(--signal); }}
.links {{ margin-top:56px; display:grid; grid-template-columns:auto 1fr; gap:14px 26px; align-items:baseline; }}
.links .t {{ font-family:var(--mono); font-size:18px; letter-spacing:.2em; color:var(--mute); text-transform:uppercase; }}
.links .u {{ font-family:var(--mono); font-size:29px; color:var(--paper); }}
.fine {{ margin-top:40px; font-size:21px; color:var(--mute); line-height:1.6; }}
</style>
<img class="abs still" src="{img(still)}">
<div class="abs shade sh"></div>
<svg class="abs w" viewBox="0 0 1920 1080"><circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/>
  <circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/><circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/></svg>
<div class="abs col">
  <div class="kick a k"><i></i>Teesri Shikayat · <span style="font-family:var(--deva);letter-spacing:0;font-size:28px">तीसरी शिकायत</span></div>
  <div class="h1 cond"><span class="ln"><span class="l">Closed at the tap,</span></span><span class="ln"><span class="l">not on paper.</span></span></div>
  <div class="links"><span class="t a u1">Code</span><span class="u a u1">{E(repo)}</span>
    <span class="t a u2">Live</span><span class="u a u2">{E(D["live_url"]["value"])}</span></div>
  <div class="fine a f">Not affiliated with BMC or any water board. Demo homes are simulated, except mine.<br>
    Demo channel: Telegram; WhatsApp plugs into the same adapter.</div>
</div>
<div class="vig"></div>"""
    # cues: "Built for the monsoon..." 0.6-3.7, "Teesri Shikayat: closed at the tap, not on paper." 4.29-7.48
    js = f"""
K('.sh', '--o', [[3.6, 0], [4.4, 1]], 'io'); K('.k', '--o', IN(4.2)); K('.l', '--o', (i) => IN(5.0 + i * 1.15, 1.0));
K('.u1', '--o', IN(7.7)); K('.u2', '--o', IN(7.95)); K('.f', '--o', IN(8.3));
const still = document.querySelector('.still'), waves = document.querySelectorAll('.wave');
HK.push(t => {{
  still.style.transform = `scale(${{1.0 + t * .009}})`;
  // the warning going out: rings leave the cluster while the monsoon line is spoken
  waves.forEach((w, i) => {{ const q = clamp((t - .7 - i * 1.0) / 2.4);
    w.setAttribute('r', {RING['r']} * (.15 + 1.25 * EZ.out(q))); w.style.opacity = q > 0 && q < 1 ? .85 * (1 - q) : 0; }});
}});"""
    return body, js


def thumbnail() -> str:
    """The YouTube thumbnail (video/thumbnail.png, 1280x720): the warned ring and the one-line story, readable small."""
    still = map_still("warned", "everyone in the ring warned", 9)
    homes = D["enrolled_in_ring"]["value"].split(" ")[0]
    return f"""
<style>
.still {{ left:0; top:0; width:1920px; height:1080px; transform:translate(440px, -10px) scale(1.12);
          transform-origin:{RING['cx']}px {RING['cy']}px; filter:saturate(.95) brightness(.85); }}
.shade {{ inset:0; background:linear-gradient(90deg, rgba(10,15,20,1) 0%, rgba(10,15,20,.95) 36%, rgba(10,15,20,.35) 58%,
          rgba(10,15,20,0) 70%); }}
.col {{ left:96px; top:190px; }}
.h {{ font-size:196px; line-height:.93; }}
.h span {{ display:block; }} .h .s {{ color:var(--signal); }}
.kick {{ font-size:34px; }}
.osm {{ right:18px; bottom:14px; font-size:20px; color:#e8e8e8; background:rgba(10,15,20,.7); padding:4px 12px; border-radius:8px; }}
</style>
<img class="abs still" src="{img(still)}"><div class="abs shade"></div>
<div class="abs col"><div class="kick"><i></i>Teesri Shikayat · <span style="font-family:var(--deva);letter-spacing:0;font-size:38px">तीसरी शिकायत</span></div>
  <div class="h cond" style="margin-top:34px"><span>3 complaints.</span><span class="s">{E(homes)} homes</span><span class="s">warned.</span></div></div>
<div class="abs osm">Map © OpenStreetMap contributors</div>"""


CARDS = {"02-indore": indore, "03-title": title, "04-mumbai": mumbai, "13a-architecture": arch, "13b-cost": cost, "14-close": close}
STILL_AT = {"03-title": 3.5}  # the title's last frame is the map; its still shows the name


def durations() -> dict:
    """Each card's length, from the edl part that plays it (dur, or the rest of its shot)."""
    out = {}
    for s in json.loads((ROOT / "video/edl.json").read_text())["shots"]:
        clock, total = 0.0, s["t"][1] - s["t"][0]
        for i, p in enumerate(s["parts"]):
            dur = p.get("dur", total - clock) if i < len(s["parts"]) - 1 else total - clock
            f = p.get(f"file@{MODE}", p.get("file", ""))
            if f.startswith("video/cards/"):
                out[pathlib.Path(f).stem] = dur
            clock += dur
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lengths = durations()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, make in CARDS.items():
            if ONLY and name != ONLY:
                continue
            dur = lengths.get(name)
            if not dur:
                print(f"{name}: not in edl.json, skipped")
                continue
            body, js = make()
            # each card's script in its own scope: set_content keeps the window, and a second top-level const would throw,
            # leaving the previous card's seek() in charge
            page.set_content(f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{body}"
                             f"<script>(() => {{{ENGINE}{js}}})();</script></body>")
            page.wait_for_timeout(400)
            if AT:
                for t in AT:
                    page.evaluate(f"seek({t})")
                    page.screenshot(path=str(OUT / f"_{name}@{t:g}.png"))
                continue
            out = OUT / f"{name}.mp4"
            ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
                                   "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                                   "-threads", "4", str(out)], stdin=subprocess.PIPE)
            for f in range(round(dur * FPS)):
                page.evaluate(f"seek({f / FPS})")
                ff.stdin.write(page.screenshot(type="jpeg", quality=93))
            ff.stdin.close()
            ff.wait()
            page.evaluate(f"seek({STILL_AT.get(name, dur - 0.04)})")
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(out, f"{dur:g} s")
        if not ONLY or ONLY == "thumbnail":
            page.set_content(f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{thumbnail()}</body>")
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "_thumbnail-1080.png"))
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(OUT / "_thumbnail-1080.png"), "-vf",
                            "scale=1280:720:flags=lanczos", str(ROOT / "video/thumbnail.png")], check=True)
            print(ROOT / "video/thumbnail.png")
        browser.close()


if __name__ == "__main__":
    main()
