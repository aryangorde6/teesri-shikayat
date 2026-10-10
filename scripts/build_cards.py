"""The video's motion cards (shots 2, 3, 4, 13, 14) as 1920x1080 mp4s, every number read from video/slides-data.json.

The look is maximalist, from the paperwork the project is against and the street posters around it: newsprint and
turmeric paper, torn clippings, tape, rubber stamps, halftone, huge Devanagari, condensed caps with hard offset shadows,
a Palatino italic and a typewriter face. Each card is one html page whose animation is a function of time: window.seek(t)
sets every element, and each frame is a Chromium screenshot piped into ffmpeg (frame-exact, repeatable). The cue times
in the timelines are the narration's (video/out/voice.srt, shot-relative), so the numbers land on the spoken word.
A still of each card goes next to its mp4 (<name>.png) for checking, and the YouTube thumbnail is drawn the same way.

Usage: .venv/bin/python scripts/build_cards.py [--mode agent|template] [--out video/cards] [--only 02-indore] [--at 2,5.5]
  --mode template: the architecture card says what template mode runs (no Gemma, no Strands agent on screen)
  --at: stills at those seconds only (_<name>@<t>.png), no mp4
"""
import base64
import html
import json
import pathlib
import random
import re
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
RING = {"cx": 958, "cy": 555, "r": 402, "dots": [(789, 585, 13), (1129, 585, 13), (960, 496, 13)]}
TEX = {}  # grain and stamp-speckle textures, rendered once (data uris)

CSS = """
:root { --paper:#f2e8d0; --paper2:#eadcb9; --white:#fffcf3; --ink:#161311; --red:#e3362a; --yel:#f5b400; --blue:#1d3fae;
        --pink:#ff5d8f; --green:#0d8a5c;
        --sans:"Ubuntu Sans","Noto Sans","Noto Sans Devanagari",sans-serif; --serif:"P052","Palatino",serif;
        --type:"Courier 10 Pitch","Nimbus Mono PS",monospace; --deva:"Noto Serif Devanagari",serif; }
* { box-sizing:border-box; margin:0; }
body { width:1920px; height:1080px; overflow:hidden; background:var(--ink); color:var(--ink); font-family:var(--sans); position:relative; }
.abs { position:absolute; }
#stage { position:absolute; inset:0; overflow:hidden; }
#stage > .bg { inset:-30px !important; }
.grain { position:absolute; inset:-40px; background-size:420px 420px; mix-blend-mode:overlay; opacity:.55; pointer-events:none; }
.half { position:absolute; border-radius:50%; background-image:radial-gradient(var(--hc) 34%, transparent 37%);
        background-size:var(--hs, 16px) var(--hs, 16px); -webkit-mask-image:radial-gradient(closest-side, #000 30%, transparent 100%); }
.cond { font-stretch:75%; font-weight:800; text-transform:uppercase; letter-spacing:-.005em; line-height:.86; }
.deva { font-family:var(--deva); font-weight:700; }
.typed { font-family:var(--type); }
.serif { font-family:var(--serif); font-style:italic; font-weight:700; }
.ghost { color:transparent; -webkit-text-stroke:3px var(--gs, rgba(22,19,17,.14)); white-space:nowrap; }
.brut { border:5px solid var(--ink); box-shadow:12px 12px 0 var(--ink); }
.tag { font-family:var(--type); font-weight:700; font-size:25px; letter-spacing:.08em; text-transform:uppercase; padding:10px 20px;
       display:inline-block; }
.tape { position:absolute; width:170px; height:46px; background:rgba(255,249,228,.78); border:1px solid rgba(0,0,0,.06);
        box-shadow:0 2px 6px rgba(0,0,0,.12); }
.stamp { color:var(--red); border:9px double var(--red); padding:8px 26px; font-stretch:75%; font-weight:800; text-transform:uppercase;
         line-height:1; mix-blend-mode:multiply; -webkit-mask-size:380px 380px; }
.greek i { display:block; height:11px; background:rgba(22,19,17,.2); margin:0 0 11px; }
/* motion: --o 0..1 per element (eased by its track) */
.pop { opacity:min(1, calc(var(--o, 0) * 3)); transform:rotate(var(--r, 0deg)) scale(calc(1 + (1 - var(--o, 0)) * .3)); }
.slam { opacity:min(1, calc(var(--o, 0) * 4)); transform:rotate(var(--r, 0deg)) scale(calc(1 + (1 - var(--o, 0)) * 1.1)); }
.drop { opacity:min(1, calc(var(--o, 0) * 3));
        transform:translateY(calc((1 - var(--o, 0)) * -70px)) rotate(calc(var(--r, 0deg) + (1 - var(--o, 0)) * 12deg)); }
.wipe { clip-path:inset(-20px calc((1 - var(--o, 0)) * 100%) -20px -20px); }
.ln { display:block; overflow:hidden; padding-bottom:.04em; }
.ln > span { display:inline-block; transform:translateY(calc((1 - var(--o, 0)) * 112%)); }
.mark { background:linear-gradient(var(--yel), var(--yel)) no-repeat 0 88% / calc(var(--o, 0) * 100%) 46%; }
"""

# the animation engine: K(selector, css variable, [[t, value], ...]) tracks, eased between keys; hooks for the rest
ENGINE = """
const EZ = {out: p => 1 - Math.pow(1 - p, 4), io: p => p < .5 ? 8 * p ** 4 : 1 - Math.pow(-2 * p + 2, 4) / 2, lin: p => p,
            back: p => { const c = 1.7; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); },
            inq: p => p * p * p};
const TR = [], HK = [], SHAKE = [];
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
const SLAM = (a) => { SHAKE.push(a + .16); return [[a, 0], [a + .16, 1]]; };
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const stage = document.getElementById('stage'), grains = document.querySelectorAll('.grain');
window.seek = t => {
  for (const r of TR) r.el.style.setProperty(r.v, val(r.keys, t, r.ez));
  for (const h of HK) h(t);
  // a stamp landing shakes the frame for a quarter second
  let dx = 0, dy = 0;
  for (const s of SHAKE) { const q = (t - s) / .28; if (q > 0 && q < 1) { const a = 14 * (1 - q) ** 2; dx += a * Math.sin(t * 97); dy += a * Math.cos(t * 83); } }
  stage.style.transform = `translate(${dx}px, ${dy}px)`;
  // film grain: the texture jumps every frame
  const f = Math.round(t * 30);
  grains.forEach(g => g.style.backgroundPosition = `${(f * 137) % 420}px ${(f * 251) % 420}px`);
};
"""


def img(path: pathlib.Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def textures(page) -> None:
    """Grain (grey noise for overlay blending) and speckle (an alpha mask with holes, so stamps look inked)."""
    for name, matrix, bg in (("grain", "0 0 0 0 .5  0 0 0 0 .5  0 0 0 0 .5  1.6 0 0 0 -.3", "#808080"),
                             ("speckle", "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -14 0 0 0 9.2", "transparent")):
        freq = ".85" if name == "grain" else ".55"
        page.set_content(f'<body style="margin:0;background:{bg}"><svg width="420" height="420"><filter id="n">'
                         f'<feTurbulence type="fractalNoise" baseFrequency="{freq}" numOctaves="3" stitchTiles="stitch"/>'
                         f'<feColorMatrix type="matrix" values="{matrix}"/></filter>'
                         f'<rect width="420" height="420" filter="url(#n)" fill="#fff"/></svg></body>')
        png = page.screenshot(clip={"x": 0, "y": 0, "width": 420, "height": 420}, omit_background=(name == "speckle"))
        TEX[name] = "data:image/png;base64," + base64.b64encode(png).decode()


def grain() -> str:
    return f'<div class="grain" style="background-image:url({TEX["grain"]})"></div>'


def stamp_mask() -> str:
    return f'-webkit-mask-image:url({TEX["speckle"]});'


def torn(seed: int, edges: str = "b", n: int = 46, amp: float = 12) -> str:
    """A clip-path polygon with ragged edges (t, r, b, l), like paper torn by hand."""
    rnd = random.Random(seed)
    j = lambda e: rnd.uniform(0, amp) if e in edges else 0  # noqa: E731
    pts = [f"{i * 100 / n:.2f}% {j('t'):.1f}px" for i in range(n + 1)]
    pts += [f"calc(100% - {j('r'):.1f}px) {i * 100 / n:.2f}%" for i in range(1, n + 1)]
    pts += [f"{100 - i * 100 / n:.2f}% calc(100% - {j('b'):.1f}px)" for i in range(1, n + 1)]
    pts += [f"{j('l'):.1f}px {100 - i * 100 / n:.2f}%" for i in range(1, n)]
    return "clip-path:polygon(" + ", ".join(pts) + ");"


def greek(lines: int, seed: int) -> str:
    """Grey bars where a clipping's body text would be: the shape of a newspaper column, no invented words."""
    rnd = random.Random(seed)
    return '<div class="greek">' + "".join(f'<i style="width:{rnd.uniform(72, 100):.0f}%"></i>' for _ in range(lines)) + "</div>"


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
    slips = [(1130, 560, -8), (1500, 450, 6), (1330, 700, -3), (1660, 640, 9), (1050, 770, 5), (1560, 250, -6)]
    slip_html = "".join(
        f'<div class="abs slip drop" style="left:{x}px;top:{y}px;--r:{r}deg"><b class="deva">शिकायत</b>'
        f'<span class="typed">complaint no. {i + 1}</span></div>' for i, (x, y, r) in enumerate(slips))
    body = f"""
<style>
.bg {{ inset:0; background:var(--paper); }}
.slip {{ width:250px; padding:14px 18px 16px; background:var(--white); border:4px solid var(--ink); box-shadow:8px 8px 0 var(--ink); }}
.slip b {{ display:block; font-size:44px; line-height:1.15; }}
.slip span {{ font-size:19px; }}
.clip {{ left:96px; top:180px; width:930px; padding:34px 44px 60px; background:var(--paper2); --r:-1.5deg;
         box-shadow:0 22px 50px rgba(0,0,0,.28); }}
.clip .rule {{ border-top:3px solid var(--ink); border-bottom:1px solid var(--ink); height:9px; margin-bottom:22px; }}
.clip h1 {{ font-size:212px; }}
.clip .greek {{ columns:2; column-gap:34px; margin-top:28px; }}
.pipe {{ left:0; top:0; width:1920px; height:1080px; }}
.pipe .pp {{ fill:none; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--d, 0)); }}
.leak {{ transform-origin:1452px 318px; transform:scale(var(--o, 0)); }}
.band {{ left:-80px; top:388px; width:2080px; height:350px; background:var(--ink); --r:-3deg; padding:22px 0 0 190px;
         display:flex; align-items:flex-end; gap:40px; box-shadow:0 30px 70px rgba(0,0,0,.45); }}
.band .n {{ font-size:390px; color:var(--red); line-height:.8; }}
.band .w {{ font-size:170px; color:var(--paper); }}
.band .why {{ position:absolute; left:196px; bottom:-56px; font-size:24px; background:var(--yel); padding:8px 16px; }}
.src {{ left:96px; top:880px; font-size:19px; background:var(--white); padding:8px 14px; max-width:1200px; }}
</style>
<div class="abs bg"></div>
<div class="abs half" style="--hc:var(--red);--hs:18px;left:1180px;top:-330px;width:1000px;height:1000px;opacity:.55"></div>
<div class="abs ghost deva gh" style="font-size:600px;left:760px;top:330px;line-height:1">इंदौर</div>
<svg class="abs pipe" viewBox="0 0 1920 1080">
  <path class="pp" pathLength="1" d="M1040 160 L1450 160 L1450 470 L1940 470" style="stroke:var(--ink);stroke-width:40"/>
  <path class="pp" pathLength="1" d="M1040 160 L1450 160 L1450 470 L1940 470" style="stroke:var(--blue);stroke-width:26"/>
  <g class="leak"><path d="M1452 290 C1490 300 1500 330 1480 350 C1470 380 1430 370 1420 352 C1395 335 1410 300 1452 290 Z"
     fill="#7a5328" stroke="var(--ink)" stroke-width="4"/></g>
  <circle class="drip" r="9" fill="#7a5328" stroke="var(--ink)" stroke-width="3"/><circle class="drip" r="7" fill="#7a5328"
     stroke="var(--ink)" stroke-width="3"/></svg>
<div class="abs clip drop" style="{torn(2, 'rb', 50, 14)}">
  <div class="rule"></div>
  <h1 class="cond"><span class="mark mk">Sewage</span><br>in the taps.</h1>
  {greek(10, 3)}
</div>
<div class="abs tag kk pop" style="left:96px;top:96px;background:var(--ink);color:var(--paper);--r:-1.5deg">Indore · Bhagirathpura · Dec 2025</div>
{slip_html}
<div class="abs band slam bd"><span class="n cond">{E(deaths)}</span><span class="w cond">deaths</span>
  <span class="why typed">judicial commission: {E(D["indore_deaths"]["value"])}</span></div>
<div class="abs src typed sr pop">Source: ETV Bharat on the judicial commission report, Sep 2026 (report not public). Pipe and slips: illustration.</div>
{grain()}"""
    js = """
K('.kk', '--o', IN(.3, .4), 'back'); K('.clip', '--o', IN(.55, .55), 'back'); K('.mk', '--o', IN(1.5, .7), 'io');
K('.pp', '--d', [[1.0, 0], [3.1, 1]], 'io'); K('.leak', '--o', IN(3.05, .4), 'back');
K('.slip', '--o', (i) => IN(4.9 + i * .22, .4), 'back');
K('.bd', '--o', SLAM(6.7), 'inq'); K('.sr', '--o', IN(7.05, .35));
const drips = document.querySelectorAll('.drip'), gh = document.querySelector('.gh');
HK.push(t => {
  drips.forEach((d, i) => { const q = t < 3.3 ? -1 : ((t - 3.3 + i * .55) % 1.1) / 1.1;
    d.setAttribute('cx', 1450 + i * 14); d.setAttribute('cy', 370 + 120 * q * q); d.style.opacity = q < 0 ? 0 : 1 - q; });
  gh.style.transform = `translateX(${-t * 8}px)`;
});"""
    return body, js


def title() -> tuple:
    still = map_still("ring", "ring snaps", 0.5)
    c = RING
    dots = "".join(f'<circle class="dp" cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in c["dots"])
    body = f"""
<style>
.bg {{ inset:0; background:var(--yel); opacity:calc(1 - var(--x, 0)); }}
.still {{ inset:0; width:1920px; height:1080px; opacity:var(--o, 0); }}
.motif {{ left:0; top:0; width:1920px; height:1080px; overflow:visible; }}
.ring {{ fill:rgba(227,54,42,.1); stroke:var(--red); }}
.ringk {{ fill:none; stroke:var(--ink); }}
.dp {{ fill:var(--red); stroke:var(--ink); }}
.dp:last-child {{ stroke:#61b8ff; }}
.deco {{ opacity:calc(1 - var(--x, 0)); }}
.word {{ left:0; width:1920px; text-align:center; opacity:calc(1 - var(--x, 0)); transform:scale(calc(1 + .06 * var(--x, 0))); }}
.hi {{ font-size:210px; line-height:1.25; }}
.en {{ display:inline-block; font-size:150px; color:var(--red); text-shadow:8px 8px 0 var(--ink); letter-spacing:.01em; }}
.tp {{ display:inline-block; font-size:58px; padding:6px 34px 12px; background:rgba(255,249,228,.9); box-shadow:0 3px 10px rgba(0,0,0,.18); }}
</style>
<div class="abs bg bgx"></div>
<div class="deco dx">
  <div class="abs half" style="--hc:var(--red);--hs:20px;left:-260px;top:520px;width:900px;height:900px;opacity:.5"></div>
  <div class="abs half" style="--hc:var(--ink);--hs:14px;left:1420px;top:-260px;width:760px;height:760px;opacity:.22"></div>
  <div class="abs ghost deva gh" style="font-size:640px;left:-60px;top:150px;line-height:1;--gs:rgba(22,19,17,.13)">शिकायत</div>
  {grain()}
</div>
<img class="abs still st" src="{img(still)}">
<svg class="abs motif" viewBox="0 0 1920 1080"><g class="mg">
  <circle class="ringk" cx="{c['cx']}" cy="{c['cy']}" r="0"/><circle class="ring" cx="{c['cx']}" cy="{c['cy']}" r="0"/>{dots}</g></svg>
<div class="abs word wx" style="top:420px">
  <div class="hi deva wipe hw">तीसरी शिकायत</div>
  <div style="margin-top:-28px"><span class="en cond slam es" style="--r:-2deg">Teesri Shikayat</span></div>
  <div style="margin-top:34px"><span class="tp serif pop tt" style="--r:-3deg">the third complaint</span></div>
</div>"""
    js = f"""
K('.hw', '--o', IN(.55, .8), 'io'); K('.es', '--o', SLAM(1.15), 'inq'); K('.tt', '--o', IN(2.5, .4), 'back');
K('.bgx, .dx, .wx', '--x', [[3.95, 0], [4.55, 1]], 'io'); K('.st', '--o', [[4.2, 0], [4.95, 1]], 'io');
const ring = document.querySelector('.ring'), ringk = document.querySelector('.ringk'), mg = document.querySelector('.mg');
const dps = document.querySelectorAll('.dp'), gh = document.querySelector('.gh');
const CX = {c['cx']}, CY = {c['cy']}, R = {c['r']}, S0 = .42, Y0 = 250, RS = {[r for _, _, r in c['dots']]};
HK.push(t => {{
  // the motif sits small above the name, then grows onto the map's own ring for the cut (t = 5)
  const m = EZ.io(clamp((t - 3.85) / 1.1)), s = S0 + (1 - S0) * m, cy = Y0 + (CY - Y0) * m;
  mg.setAttribute('transform', `translate(${{960 + (CX - 960) * m}} ${{cy}}) scale(${{s}}) translate(${{-CX}} ${{-CY}})`);
  const r = R * EZ.back(clamp((t - 1.0) / .9));
  ring.setAttribute('r', r); ringk.setAttribute('r', r);
  ring.style.strokeWidth = (14 - 9 * m) / s; ringk.style.strokeWidth = (24 * (1 - m)) / s;  // bold poster ring -> the map's line
  dps.forEach((d, i) => {{ const q = EZ.back(clamp((t - .15 - i * .3) / .35));
    d.setAttribute('r', RS[i] * (1 + .6 * (1 - m)) * q); d.style.strokeWidth = (i === 2 ? 4 : 6 * (1 - m)) / s; }});
  gh.style.transform = `translateX(${{-t * 10}}px)`;
}});"""
    return body, js


def mumbai() -> tuple:
    n = int(D["mumbai_complaints"]["value"].split(" ")[0].replace(",", ""))
    unfit = D["b_ward_unfit"]["value"]
    body = f"""
<style>
.bg {{ inset:0; background:var(--ink); }}
canvas {{ left:990px; top:70px; }}
.num {{ left:96px; top:160px; font-size:340px; color:var(--paper); text-shadow:14px 14px 0 var(--red); font-variant-numeric:tabular-nums; }}
.lab {{ left:104px; top:470px; font-size:72px; color:var(--yel); }}
.clip {{ left:90px; top:610px; width:860px; padding:30px 40px 44px; background:var(--white); --r:1.6deg;
         box-shadow:0 22px 50px rgba(0,0,0,.45); }}
.clip q {{ display:block; font-size:66px; line-height:1.08; quotes:"“" "”"; }}
.clip .by {{ font-size:22px; margin-top:16px; }}
.note {{ left:1470px; top:690px; width:380px; padding:22px 24px; background:var(--pink); --r:4deg; font-size:23px; line-height:1.35; }}
.note b {{ font-family:var(--sans); font-stretch:75%; font-weight:800; font-size:44px; display:block; line-height:1; margin-bottom:8px; }}
.src {{ left:96px; top:908px; font-size:19px; color:var(--paper); opacity:calc(.7 * var(--o, 0)); }}
</style>
<div class="abs bg"></div>
<div class="abs half" style="--hc:var(--yel);--hs:18px;left:-300px;top:300px;width:1000px;height:1000px;opacity:.16"></div>
<div class="abs ghost deva gh" style="font-size:560px;left:300px;top:-170px;line-height:1;--gs:rgba(242,232,208,.08)">मुंबई</div>
<canvas class="abs" width="940" height="840"></canvas>
<div class="abs tag kk pop" style="left:96px;top:92px;background:var(--yel);--r:-1.5deg">Mumbai · Jan–Aug 2026</div>
<div class="abs num cond ct">0</div>
<div class="abs lab cond lb pop">dirty-water complaints</div>
<div class="abs clip slam cq" style="{torn(5, 'tb', 50, 12)}">
  <div class="tape" style="left:330px;top:-14px;transform:rotate(-4deg)"></div>
  <q class="serif"><span class="mark mq">Immediate alerts</span> to residents.</q>
  <div class="by typed">— BMC standard operating procedure, 30 Sep 2026</div></div>
<div class="abs note typed drop nt brut"><b>B ward (Dongri)</b>{E(unfit.split("%")[0])}% of water samples unfit.
  City: {E(unfit.split(" vs ")[1].split(" (")[0].replace(" citywide", ""))}.</div>
<div class="abs src typed sr">Free Press Journal, 1 Oct 2026 · each slip is one complaint</div>
{grain()}"""
    js = f"""
const N = {n};
K('.kk', '--o', IN(.3, .4), 'back'); K('.lb', '--o', IN(.9, .4), 'back'); K('.cq', '--o', SLAM(4.3), 'inq');
K('.mq', '--o', IN(4.75, .6), 'io'); K('.nt', '--o', IN(6.2, .45), 'back'); K('.sr', '--o', IN(1.4));
const ct = document.querySelector('.ct'), cv = document.querySelector('canvas'), g = cv.getContext('2d'), gh = document.querySelector('.gh');
let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const COLS = ['#f2e8d0', '#fffcf3', '#f2e8d0', '#f5b400', '#fffcf3', '#e3362a', '#ff5d8f', '#1d3fae'];
// a pile of complaint slips, densest in the middle
const slips = [...Array(N)].map(() => {{
  const a = rnd() * 6.283, r = Math.pow(rnd(), .75) * 400;
  return [470 + Math.cos(a) * r * 1.1, 420 + Math.sin(a) * r * .95, (rnd() - .5) * 1.6, COLS[Math.floor(rnd() * COLS.length)]];
}});
HK.push(t => {{
  const k = Math.round(N * EZ.out(clamp((t - .6) / 2.5)));
  ct.textContent = k.toLocaleString('en-IN');
  g.clearRect(0, 0, cv.width, cv.height);
  g.lineWidth = 2; g.strokeStyle = '#161311';
  for (let i = 0; i < k; i++) {{
    const [x, y, a, c] = slips[i];
    g.save(); g.translate(x, y); g.rotate(a); g.fillStyle = c; g.fillRect(-19, -12, 38, 24); g.strokeRect(-19, -12, 38, 24);
    g.fillStyle = 'rgba(22,19,17,.35)'; g.fillRect(-13, -6, 22, 3); g.fillRect(-13, 1, 15, 3); g.restore();
  }}
  gh.style.transform = `translateX(${{-t * 8}}px)`;
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
    X0, NW, GAP, NH, YS = 160, 355, 60, 128, [250, 490, 730]
    tilt = [-1.4, .9, -.6, 1.2, -1.0, .7, -1.3, 1.0, .8, -1.1, .6]
    pos = [(X0 + c * (NW + GAP), YS[r]) for r, c, *_ in nodes]
    mw, mh = NW + 60, NH + 52
    pts = [52, 3, 88, 1, 101, 22, 98, 52, 96, 86, 62, 100, 42, 98, 8, 95, -1, 62, 3, 36, 7, 12, 30, 3, 61, 6]
    xy = [f"{v * (mw if k % 2 == 0 else mh) / 100:.1f}" for k, v in enumerate(pts)]
    d = (f"M{xy[0]} {xy[1]} C{xy[2]} {xy[3]} {xy[4]} {xy[5]} {xy[6]} {xy[7]} C{xy[8]} {xy[9]} {xy[10]} {xy[11]} {xy[12]} {xy[13]} "
         f"C{xy[14]} {xy[15]} {xy[16]} {xy[17]} {xy[18]} {xy[19]} C{xy[20]} {xy[21]} {xy[22]} {xy[23]} {xy[24]} {xy[25]}")
    ring = f'<svg class="mk" viewBox="0 0 {mw} {mh}"><path pathLength="1" d="{d}"/></svg>'
    boxes = "".join(f'<div class="node {k}" style="left:{x}px;top:{y}px;--r:{tl}deg">{ring}<b class="cond">{E(nm)}</b>'
                    f'<small class="typed">{E(sb)}</small></div>'
                    for (x, y), (_, _, nm, sb, k), tl in zip(pos, nodes, tilt))
    links = []
    for i in range(len(nodes) - 1):
        (xa, ya), (xb, yb) = pos[i], pos[i + 1]
        if ya == yb:  # same row: edge to edge
            y = ya + NH / 2
            a, b = (xa + NW + 12, xb - 14) if xb > xa else (xa - 12, xb + NW + 14)
            links.append(f"M{a} {y} L{b} {y}")
        else:  # down to the next row
            x = xa + NW / 2
            links.append(f"M{x} {ya + NH + 14} L{x} {yb - 16}")
    paths = "".join(f'<path class="ln{i}" pathLength="1" d="{d}"/>' for i, d in enumerate(links))
    lanes = "".join(f'<div class="abs lane typed a{i}" style="left:{X0}px;top:{y - 44}px">{n}</div>'
                    for i, (y, n) in enumerate(zip(YS, ["01 / listen", "02 / detect", "03 / act"])))
    note = ("Bedrock quota on this account is 0, so the model is ours: Gemma 4 E4B in llama.cpp on one EC2 Graviton4 "
            "instance, no inbound ports (requests over SQS). Nova plugs into the same code." if agent else
            "Template mode: the case steps use fixed wording when the model instance is off.")
    body = f"""
<style>
.bg {{ inset:0; background-color:var(--blue);
       background-image:linear-gradient(rgba(255,255,255,.16) 2px, transparent 2px), linear-gradient(90deg, rgba(255,255,255,.16) 2px, transparent 2px),
       linear-gradient(rgba(255,255,255,.07) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.07) 1px, transparent 1px);
       background-size:200px 200px, 200px 200px, 40px 40px, 40px 40px; }}
.node {{ position:absolute; width:{NW}px; height:{NH}px; padding:16px 22px; background:var(--paper); border:4px solid var(--ink);
         --hl:0; box-shadow:10px 10px 0 var(--ink);
         opacity:min(1, calc(var(--o, 0) * 3)); filter:brightness(calc(1 - .5 * var(--gd, 0) * (1 - var(--hl))))
                saturate(calc(1 - .5 * var(--gd, 0) * (1 - var(--hl))));
         transform:rotate(calc(var(--r) * (1 - var(--hl)))) scale(calc(1 + (1 - var(--o, 0)) * .3 + .07 * var(--hl))); }}
.node.ai {{ background:var(--yel); }} .node.guard {{ background:var(--red); color:var(--white); }}
.node b {{ display:block; font-size:39px; white-space:nowrap; }}
.node small {{ display:block; font-size:20px; margin-top:8px; white-space:nowrap; }}
.mk {{ position:absolute; left:-34px; top:-30px; width:{NW + 60}px; height:{NH + 52}px; overflow:visible; }}
.mk path {{ fill:none; stroke:var(--red); stroke-width:7; stroke-linecap:round; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--hl)); }}
.node.guard .mk path {{ stroke:var(--yel); }}
svg.links {{ left:0; top:0; width:1920px; height:1080px; }}
.links path {{ fill:none; stroke:var(--white); stroke-width:6; stroke-dasharray:1; stroke-dashoffset:calc(1 - var(--d, 0)); }}
.links path.done {{ marker-end:url(#ah); }}
.links path.hot {{ stroke:var(--yel); }}
.pulse {{ fill:var(--yel); stroke:var(--ink); stroke-width:4; }}
.lane {{ font-size:22px; font-weight:700; color:var(--white); letter-spacing:.12em; text-transform:uppercase; opacity:var(--o, 0); }}
.legend {{ right:150px; top:84px; display:flex; gap:22px; }}
.legend span {{ font-family:var(--type); font-weight:700; font-size:19px; padding:6px 14px; border:3px solid var(--ink);
               background:var(--paper); box-shadow:5px 5px 0 var(--ink); }}
.legend .ai {{ background:var(--yel); }} .legend .guard {{ background:var(--red); color:var(--white); }}
.note {{ left:{X0 + 3 * (NW + GAP)}px; top:{YS[2] - 6}px; width:{NW}px; font-size:17px; line-height:1.5; color:var(--white);
         opacity:calc(.8 * var(--o, 0)); }}
</style>
<div class="abs bg"></div>
<div class="abs ghost cond gh" style="font-size:420px;left:40px;top:690px;--gs:rgba(255,255,255,.1)">serverless</div>
<div class="abs tag kk pop" style="left:{X0}px;top:80px;background:var(--paper);--r:-1.2deg">On AWS · one CDK stack · ap-south-1</div>
<div class="abs legend pop lg" style="--r:.8deg"><span>plain code, tested</span><span class="ai">AI or speech</span><span class="guard">policy guard, fails closed</span></div>
{lanes}
<svg class="abs links" viewBox="0 0 1920 1080"><defs><marker id="ah" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4"
  markerHeight="4" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#fffcf3"/></marker></defs>
  {paths}<circle class="pulse" r="11" cx="-50" cy="-50"/></svg>
{boxes}
<div class="abs note typed nt">{E(note)}</div>
{grain()}"""
    # cues (shot-relative): "Step Functions holds each case for days" 3.57, "DynamoDB streams feed the tripwire" ~5.9,
    # "and Polly speaks Hindi" ~8.2
    js = """
const nodes = document.querySelectorAll('.node');
K('.kk', '--o', IN(.2, .4), 'back'); K('.lg', '--o', IN(.5, .4), 'back'); K('.lane', '--o', (i) => IN(.4 + i * .8)); K('.nt', '--o', IN(2.8));
K('.node', '--o', (i) => IN(.45 + i * .21, .38), 'back');
K('.links path', '--d', (i) => [[.62 + i * .21, 0], [.92 + i * .21, 1]], 'io');
document.body.style.setProperty('--gd', 0);
K('body', '--gd', [[3.3, 0], [3.75, 1]]);
const HL = {7: [[3.35, 0], [3.8, 1], [5.7, 1], [6.05, 0]], 4: [[5.8, 0], [6.2, 1], [8.0, 1], [8.3, 0]],
            5: [[6.05, 0], [6.45, 1], [8.0, 1], [8.3, 0]], 6: [[6.3, 0], [6.7, 1], [8.0, 1], [8.3, 0]], 10: [[8.05, 0], [8.5, 1]]};
for (const [i, keys] of Object.entries(HL)) TR.push({el: nodes[i], v: '--hl', keys, ez: 'out'});
const hot = [document.querySelector('.ln4'), document.querySelector('.ln5')], pulse = document.querySelector('.pulse');
const gh = document.querySelector('.gh');
HK.push(t => {
  hot.forEach(p => p.classList.toggle('hot', t > 6.0 && t < 8.2));
  document.querySelectorAll('.links path').forEach(p => p.classList.toggle('done', parseFloat(p.style.getPropertyValue('--d')) > .97));
  // a report travelling DynamoDB -> Pipes -> Tripwire
  const q = clamp((t - 6.1) / 1.8);
  if (q > 0 && q < 1) { const seg = q < .5 ? hot[0] : hot[1], f = (q % .5) * 2, L = seg.getTotalLength(), pt = seg.getPointAtLength(f * L);
    pulse.setAttribute('cx', pt.x); pulse.setAttribute('cy', pt.y); } else pulse.setAttribute('cx', -50);
  gh.style.transform = `translateX(${-t * 10}px)`;
});"""
    return body, js


def cost() -> tuple:
    c = D["cost_per_incident"]
    rs, usd = re.search(r"Rs ([\d.]+), \$([\d.]+)", c["value"]).groups()
    homes = c["detail"].split(" homes")[0]
    dots = lambda a, b, w=30: f"{a} {'.' * max(2, w - len(a) - len(b))} {b}"  # noqa: E731
    lines = ["<b>TEESRI SHIKAYAT</b>", "one incident, live run", "-" * 32, dots("HOMES WARNED", homes), dots("REOPENED", "1"),
             dots("AWS, ON-DEMAND", f"${usd}"), "-" * 32, f"<b>{dots('TOTAL', f'₹{rs}')}</b>", "priced with the AWS Pricing API"]
    receipt = "".join(f'<div class="rl">{x}</div>' for x in lines)
    body = f"""
<style>
.bg {{ inset:0; background:var(--yel); }}
.big {{ left:90px; top:70px; font-size:560px; color:var(--ink); text-shadow:18px 18px 0 var(--red); }}
.per {{ left:120px; top:640px; font-size:96px; background:var(--ink); color:var(--paper); padding:8px 28px 10px; --r:-2.5deg; }}
.rcp {{ left:1120px; top:96px; width:640px; padding:40px 44px 70px; background:var(--white); --r:2deg; box-shadow:0 26px 60px rgba(0,0,0,.3); }}
.roll {{ clip-path:inset(0 0 calc((1 - var(--o, 0)) * 100%) 0); }}
.rl {{ font-family:var(--type); font-size:27px; line-height:1.55; white-space:pre; text-align:left; }}
.rl:first-child, .rl:nth-child(2) {{ text-align:center; }}
.rl b {{ font-weight:700; }}
.st {{ left:1250px; top:640px; font-size:96px; --r:-11deg; }}
.src {{ left:120px; top:850px; width:930px; font-size:18px; line-height:1.45; }}
</style>
<div class="abs bg"></div>
<div class="abs half" style="--hc:var(--red);--hs:22px;left:-200px;top:-300px;width:1100px;height:1100px;opacity:.38"></div>
<div class="abs ghost deva" style="font-size:520px;left:900px;top:420px;line-height:1;--gs:rgba(22,19,17,.12)">एक रुपया</div>
<div class="abs big cond slam bg1" style="--r:-3deg">₹1</div>
<div class="abs per cond pop pp">per incident</div>
<div class="abs rcp drop rc" style="{torn(9, 'b', 26, 22)}"><div class="roll ro">{receipt}</div></div>
<div class="abs stamp st sm" style="{stamp_mask()}">measured</div>
<div class="abs src typed sr pop">Step Functions history + Lambda logs of a live run, priced with the AWS Pricing API (ap-south-1, on-demand,
no free tier). Telegram messages are free. The model instance is extra: $0.43/h while on; it stops itself when idle.</div>
{grain()}"""
    js = """
K('.bg1', '--o', SLAM(.4), 'inq'); K('.pp', '--o', IN(.95, .4), 'back'); K('.rc', '--o', IN(.6, .45), 'back');
K('.ro', '--o', [[.9, 0], [2.5, 1]], 'lin'); K('.sm', '--o', SLAM(2.75), 'inq'); K('.sr', '--o', IN(1.4, .4));"""
    return body, js


def close() -> tuple:
    still = map_still("warned", "everyone in the ring warned", 9)
    repo = "github.com/aryangorde6/teesri-shikayat"
    body = f"""
<style>
.still {{ left:0; top:0; width:1920px; height:1080px; filter:grayscale(1) contrast(1.15) brightness(1.05);
          transform-origin:{RING['cx']}px {RING['cy']}px; }}
.tint {{ inset:0; background:var(--yel); mix-blend-mode:multiply; }}
svg.w {{ left:0; top:0; width:1920px; height:1080px; }}
.wave {{ fill:none; stroke:var(--red); stroke-width:10; }}
.sheet {{ left:-40px; top:-30px; width:1240px; height:1140px; background:var(--paper); box-shadow:20px 0 60px rgba(0,0,0,.35);
          transform:translateX(calc((1 - var(--o, 0)) * -105%)) rotate(-1deg); }}
.k {{ left:120px; top:118px; font-size:24px; background:var(--ink); color:var(--paper); --r:-1.5deg; }}
.h1 {{ left:116px; top:190px; font-size:230px; }}
.st {{ left:150px; top:600px; font-size:124px; --r:-6deg; }}
.links {{ left:120px; top:790px; display:grid; gap:12px; }}
.links div {{ font-size:24px; background:var(--ink); color:var(--paper); padding:7px 16px; justify-self:start; }}
.links span {{ color:var(--yel); font-weight:700; margin-right:18px; }}
.fine {{ left:122px; top:900px; font-size:18px; line-height:1.5; }}
</style>
<img class="abs still" src="{img(still)}"><div class="abs tint"></div>
<div class="abs half" style="--hc:var(--ink);--hs:12px;left:900px;top:-200px;width:1400px;height:1400px;opacity:.16"></div>
<svg class="abs w" viewBox="0 0 1920 1080"><circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/>
  <circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/><circle class="wave" cx="{RING['cx']}" cy="{RING['cy']}"/></svg>
<div class="abs sheet sh" style="{torn(12, 'r', 40, 26)}"></div>
<div class="abs tag k pop kk">Teesri Shikayat · <span class="deva" style="letter-spacing:0;font-size:27px">तीसरी शिकायत</span></div>
<div class="abs h1 cond"><span class="ln"><span class="l">Closed at</span></span><span class="ln"><span class="l">the tap,</span></span></div>
<div class="abs stamp st sm" style="{stamp_mask()}">not on paper.</div>
<div class="abs links typed"><div class="pop u1" style="--r:-.6deg"><span>CODE</span>{E(repo)}</div>
  <div class="pop u2" style="--r:.4deg"><span>LIVE</span>{E(D["live_url"]["value"])}</div></div>
<div class="abs fine typed pop f">Not affiliated with BMC or any water board. Demo homes are simulated, except mine.<br>
  Demo channel: Telegram; WhatsApp plugs into the same adapter.</div>
{grain()}"""
    # cues: "Built for the monsoon..." 0.6-3.7, "Teesri Shikayat: closed at the tap, not on paper." 4.29-7.48
    js = f"""
K('.sh', '--o', IN(3.6, .55), 'io'); K('.kk', '--o', IN(4.2, .4), 'back'); K('.l', '--o', (i) => IN(4.95 + i * .55, .7));
K('.sm', '--o', SLAM(6.4), 'inq'); K('.u1', '--o', IN(7.7, .4), 'back'); K('.u2', '--o', IN(7.95, .4), 'back');
K('.f', '--o', IN(8.3, .4));
const still = document.querySelector('.still'), waves = document.querySelectorAll('.wave');
HK.push(t => {{
  still.style.transform = `scale(${{1.0 + t * .009}})`;
  // the warning going out: rings leave the cluster while the monsoon line is spoken
  waves.forEach((w, i) => {{ const q = clamp((t - .7 - i * 1.0) / 2.4);
    w.setAttribute('r', {RING['r']} * (.15 + 1.25 * EZ.out(q))); w.style.opacity = q > 0 && q < 1 ? .9 * (1 - q) : 0; }});
}});"""
    return body, js


def thumbnail() -> str:
    """The YouTube thumbnail (video/thumbnail.png, 1280x720): the warned ring and the one-line story, readable small."""
    still = map_still("warned", "everyone in the ring warned", 9)
    homes = D["enrolled_in_ring"]["value"].split(" ")[0]
    return f"""
<style>
.still {{ left:0; top:0; width:1920px; height:1080px; transform:translate(470px, -10px) scale(1.12);
          transform-origin:{RING['cx']}px {RING['cy']}px; filter:saturate(1.05) contrast(1.05); }}
.panel {{ left:-20px; top:-20px; width:1180px; height:1120px; background:var(--ink); }}
.h {{ left:84px; top:260px; font-size:168px; color:var(--paper); }}
.h span {{ display:block; }} .h .s {{ color:var(--yel); text-shadow:10px 10px 0 var(--red); }}
.osm {{ right:18px; bottom:14px; font-size:20px; color:#e8e8e8; background:rgba(22,19,17,.75); padding:4px 12px; }}
</style>
<div id="stage">
<img class="abs still" src="{img(still)}">
<div class="abs half" style="--hc:var(--red);--hs:16px;left:1250px;top:-260px;width:800px;height:800px;opacity:.35"></div>
<div class="abs panel" style="{torn(21, 'r', 34, 30)}"></div>
<div class="abs tag" style="left:84px;top:120px;background:var(--yel);transform:rotate(-2deg);font-size:34px">Teesri Shikayat ·
  <span class="deva" style="letter-spacing:0;font-size:38px">तीसरी शिकायत</span></div>
<div class="abs h cond"><span>3 complaints.</span><span class="s">{E(homes)} homes</span><span class="s">warned.</span></div>
<div class="abs osm typed">Map © OpenStreetMap contributors</div>
{grain()}</div>"""


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
        textures(page)
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
            page.set_content(f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body><div id=\"stage\">{body}</div>"
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
