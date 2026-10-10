"""Renders the video from video/edl.json: cards, the console tour (in-points from beats.json), phone and AWS footage,
labels and captions, the narration and the diegetic sound (voice note, Polly warning, tap). A missing file or an
unset in-point becomes a labelled placeholder, so the full 2:48 can be previewed before the footage exists.

Usage: .venv/bin/python scripts/build_video.py [--mode agent|template] [--voice voice.wav] [--subs voice.srt]
                                                [--out video/out/teesri.mp4] [--only 7]
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARGS = sys.argv[1:]


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


MODE = arg("--mode", "agent")
VOICE, SUBS, ONLY = arg("--voice"), arg("--subs"), arg("--only")
OUT = ROOT / arg("--out", "video/out/teesri.mp4")
W, H, FPS, BG = 1920, 1080, 30, "0x0f1419"
VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", "4"]


def pick(d: dict, key: str, default=None):
    return d.get(f"{key}@{MODE}", d.get(key, default))


def ff(*a):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, a)], check=True)


def has_audio(path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True).stdout
    return bool(out.strip())


def duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out not in ("", "N/A") else 0.0


class Text:
    """Labels, captions and placeholders, drawn by Chromium so Hindi is shaped properly."""
    # the same type and colour system as the motion cards (scripts/build_cards.py): Ubuntu Sans, amber for the signal
    CSS = ("*{margin:0;box-sizing:border-box} body{width:%dpx;height:%dpx;background:transparent;position:relative;"
           "font-family:'Ubuntu Sans','Noto Sans','Noto Sans Devanagari',sans-serif;color:#f3efe7}"
           ".label{position:absolute;left:44px;bottom:130px;font-family:'Ubuntu Sans Mono',monospace;font-size:21px;"
           "letter-spacing:.14em;text-transform:uppercase;background:rgba(10,15,20,.82);border:1px solid rgba(255,255,255,.14);"
           "border-radius:999px;padding:9px 22px 9px 18px;box-shadow:0 10px 30px rgba(0,0,0,.35)}"
           ".label.r{left:auto;right:44px}"
           ".label::before{content:'';display:inline-block;width:10px;height:10px;border-radius:50%%;background:#ffb020;"
           "margin-right:14px;vertical-align:2px}"
           ".cap{position:absolute;left:50%%;transform:translateX(-50%%);bottom:128px;font-size:46px;font-weight:700;width:max-content;"
           "background:rgba(10,15,20,.88);border:1px solid rgba(255,255,255,.12);padding:18px 36px;border-radius:18px;"
           "text-align:center;max-width:1600px;box-shadow:0 24px 60px rgba(0,0,0,.45)}"
           ".sub{position:absolute;left:50%%;transform:translateX(-50%%);bottom:40px;white-space:nowrap;font-size:40px;"
           "font-weight:500;background:rgba(10,15,20,.76);padding:8px 26px 11px;border-radius:14px}"
           ".ph{position:absolute;inset:0;border:4px dashed #ffb020;display:flex;flex-direction:column;justify-content:center;"
           "align-items:center;text-align:center;padding:30px;background:#111922}"
           ".ph b{font-size:34px;color:#ffb020} .ph span{font-size:26px;margin-top:14px;color:#c9d1d9}"
           ".co{position:absolute;background:rgba(14,20,26,.94);border:1px solid rgba(255,255,255,.11);border-radius:22px;"
           "padding:26px 32px;font-size:33px;line-height:1.38;box-shadow:0 26px 70px rgba(0,0,0,.5)}"
           ".co h4{font-family:'Ubuntu Sans Mono',monospace;font-weight:500;font-size:19px;letter-spacing:.2em;"
           "text-transform:uppercase;color:#ffb020;margin-bottom:14px}"
           ".co h4::before{content:'';display:inline-block;width:10px;height:10px;border-radius:50%%;background:currentColor;"
           "margin-right:14px;vertical-align:2px}"
           ".co .hi{font-family:'Noto Serif Devanagari',serif;font-size:28px;color:#aab3bd;margin-bottom:10px;line-height:1.5}"
           ".co .en{font-weight:500} .co ul{padding-left:28px;margin-top:8px} .co li{margin:4px 0}"
           ".co .chip{display:inline-block;font-family:'Ubuntu Sans Mono',monospace;font-size:23px;border:1.5px solid rgba(255,255,255,.16);"
           "background:rgba(255,255,255,.04);border-radius:999px;padding:6px 18px;margin:10px 10px 0 0}"
           ".co .btn{display:inline-block;background:#1c2631;border:1px solid rgba(255,255,255,.08);border-radius:12px;"
           "padding:6px 18px;margin:12px 10px 0 0;font-size:25px}"
           ".co .on{background:#ffb020;color:#0a0f14;font-weight:700}"
           ".co.warn{border-left:5px solid #ffb020}"
           ".co.aws{padding:12px 22px;border-radius:999px} .co.aws h4{margin:0;font-size:18px}"
           ".co.ok h4{color:#34d399} .co.ok .chip{border-color:rgba(52,211,153,.55)}"
           ".spot{position:absolute;border:4px solid #ffb020;border-radius:16px;"
           "box-shadow:0 0 0 4000px rgba(10,14,18,.55),0 0 30px 6px rgba(255,176,32,.5)}"
           # the stage behind a framed phone: the cards' background, so a phone shot sits in the same world
           ".stage{position:absolute;inset:0;background:radial-gradient(1300px 900px at 15%% 8%%,#18232e 0%%,rgba(10,15,20,0) 62%%),"
           "radial-gradient(1000px 800px at 92%% 105%%,#131c25 0%%,rgba(10,15,20,0) 60%%),#0a0f14}"
           ".stage::after{content:'';position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.07) 1.3px,"
           "transparent 1.6px);background-size:30px 30px}"
           ".body{position:absolute;background:#161c23;border:1px solid rgba(255,255,255,.16);box-shadow:0 40px 90px rgba(0,0,0,.6),"
           "inset 0 0 0 2px #0b0f13}")

    def __init__(self, tmp: pathlib.Path):
        self.tmp, self.n = tmp, 0
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()

    def png(self, body: str, w: int = W, h: int = H) -> pathlib.Path:
        self.n += 1
        page = self.browser.new_page(viewport={"width": w, "height": h})
        page.set_content(f"<!doctype html><meta charset=utf-8><style>{self.CSS % (w, h)}</style><body>{body}</body>")
        path = self.tmp / f"text{self.n:03d}.png"
        page.screenshot(path=str(path), omit_background=True)
        page.close()
        return path

    def close(self):
        self.browser.close()
        self.pw.stop()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;")


def segment(src: dict, dur: float, box, tmp: pathlib.Path, text: Text, beats: dict, web: str, tag: str, bare=False) -> tuple:
    """One visual source -> an mp4 of exactly dur seconds at box size (w, h), plus its audio as a wav (or None)."""
    x, y, w, h = box
    out, wav = tmp / f"{tag}.mp4", None
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,fps={FPS}"
    if bare:
        fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps={FPS}"
    if "card" in src:
        # push: a slow zoom-in by that fraction over the part (worked at 2x so each step is half a pixel, no judder)
        push = src.get("push", 0)
        zoom = (f",scale={2 * w}:{2 * h},zoompan=z='1+{push}*on/{round(dur * FPS)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
                f":d=1:s={w}x{h}:fps={FPS}") if push else ""
        ff("-loop", 1, "-framerate", FPS, "-t", dur, "-i", ROOT / pick(src, "card"), "-vf", fit + zoom, *VENC, "-an", out)
        return out, None
    if "beat" in src:
        name = next((k for k in beats if src["beat"].lower() in k.lower()), None)
        file, start = (web, beats[name] + src.get("offset", 0)) if name is not None else (None, None)
    else:
        file, start = pick(src, "file"), src.get("in")
    path = ROOT / file if file else None
    if not path or not path.exists() or start is None:
        why = "missing file" if not path or not path.exists() else "set its in-point in edl.json"
        png = text.png(f'<div class="ph"><b>{esc(pick(src, "what", file or src.get("beat", "")))}</b>'
                       f'<span>{esc(file or "web tour")} · {why}</span></div>', w, h)
        ff("-loop", 1, "-t", dur, "-i", png, "-vf", f"fps={FPS},format=yuv420p", *VENC, "-an", out)
        return out, None
    start = max(0.0, float(start))
    crop = "crop={2}:{3}:{0}:{1},".format(*src["crop"]) if "crop" in src else ""  # [x, y, w, h] of the source frame
    # push on footage too: a slow zoom-in over the part, so a still console page doesn't sit dead (same 2x zoompan as cards)
    push = src.get("push", 0)
    zoom = (f",scale={2 * w}:{2 * h},zoompan=z='1+{push}*on/{round(dur * FPS)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
            f":d=1:s={w}x{h}:fps={FPS}") if push else ""
    ff("-ss", start, "-i", path, "-t", dur, "-vf", f"{crop}{fit},tpad=stop_mode=clone:stop_duration={dur}{zoom}", "-t", dur,
       *VENC, "-an", out)
    if src.get("audio") and has_audio(path):
        wav = tmp / f"{tag}.wav"
        ff("-ss", start, "-i", path, "-t", dur, "-vn", "-ac", 2, "-ar", 48000, "-af", f"loudnorm=I=-20:TP=-2,apad=whole_dur={dur}",
           "-t", dur, wav)
    return out, wav


def silence(dur: float, path: pathlib.Path) -> pathlib.Path:
    ff("-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo", path)
    return path


RADIUS, BEZEL, MARGIN = {"phone": 40, "rise": 40, "window": 14}, {"phone": 14, "rise": 14, "window": 1}, 46


def frame_kind(src: dict, box) -> str:
    """Boxed footage gets a frame: a phone body for the phone recordings ("rise": its top runs off the frame), a window
    for the AWS console. "frame": "none" in the edl keeps the old flat box."""
    if list(box) == [0, 0, W, H] or src.get("frame") == "none":
        return ""
    return src.get("frame") or ("phone" if "phone" in str(pick(src, "file", "")) else "window")


def inner_box(box, kind: str) -> list:
    """A phone that would touch the top or bottom of the frame is given room for its body and shadow."""
    x, y, w, h = box
    top = MARGIN if kind == "phone" and y == 0 else 0
    bottom = MARGIN if kind in ("phone", "rise") and y + h == H else 0
    return [x, y + top, w, h - top - bottom]


def dims(path) -> tuple:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True).stdout.strip()
    return tuple(int(x) for x in out.split(",")[:2])


def frame(v, box, kind: str, text: Text, stage: bool) -> tuple:
    """Where the footage sits (x, y), the png under it (body + shadow, on the stage or on transparent) and its corner mask."""
    vw, vh = dims(v)
    x, y = box[0] + (box[2] - vw) // 2, box[1] + (box[3] - vh) // 2
    r, b = RADIUS[kind], BEZEL[kind]
    top = y - b if kind != "rise" else y - 240  # a rising phone's top is off the frame
    under = text.png(('<div class="stage"></div>' if stage else "") +
                     f'<div class="body" style="left:{x - b}px;top:{top}px;width:{vw + 2 * b}px;height:{y + vh + b - top}px;'
                     f'border-radius:{r + b}px"></div>')
    corners = f"0 0 {r}px {r}px" if kind == "rise" else f"{r}px"
    mask = text.png(f'<div style="position:absolute;inset:0;background:#fff;border-radius:{corners}"></div>', vw, vh)
    return x, y, under, mask


def render_shot(shot: dict, tmp: pathlib.Path, text: Text, beats: dict, web: str) -> tuple:
    n, (t0, t1) = shot["n"], shot["t"]
    total = t1 - t0
    parts, clock, vids, wavs = shot["parts"], 0.0, [], []
    for i, p in enumerate(parts):
        dur = p.get("dur", total - clock) if i < len(parts) - 1 else total - clock
        box = p.get("box", [0, 0, W, H])
        kind = frame_kind(p, box)
        inner = inner_box(box, kind) if kind else box
        v, a = segment(p, dur, inner, tmp, text, beats, web, f"s{n:02d}p{i}", bare=bool(kind))
        if kind:  # the footage in its frame, on the stage
            x, y, under, mask = frame(v, inner, kind, text, stage=True)
            placed = tmp / f"s{n:02d}p{i}full.mp4"
            ff("-loop", 1, "-framerate", FPS, "-t", dur, "-i", under, "-i", v, "-loop", 1, "-framerate", FPS, "-t", dur, "-i", mask,
               "-filter_complex", f"[2:v]alphaextract[m];[1:v]format=rgba[f];[f][m]alphamerge[o];[0:v][o]overlay={x}:{y}:shortest=1",
               "-t", dur, *VENC, "-an", placed)
            v = placed
        elif box != [0, 0, W, H]:  # place the box on the full frame
            placed = tmp / f"s{n:02d}p{i}full.mp4"
            ff("-i", v, "-vf", f"pad={W}:{H}:{box[0]}:{box[1]}:color={BG}", *VENC, "-an", placed)
            v = placed
        labels = "".join(f'<div class="label">{esc(lbl)}</div>' for lbl in [pick(p, "label")] if lbl)
        if labels:
            v2 = tmp / f"s{n:02d}p{i}lab.mp4"
            ff("-i", v, "-i", text.png(labels), "-filter_complex", "[0][1]overlay=0:0", *VENC, "-an", v2)
            v = v2
        vids.append(v)
        wavs.append(a or silence(dur, tmp / f"s{n:02d}p{i}sil.wav"))
        clock += dur
    lst = tmp / f"s{n:02d}.txt"
    lst.write_text("".join(f"file '{v}'\n" for v in vids))
    base = tmp / f"s{n:02d}base.mp4"
    ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", base)
    alst = tmp / f"s{n:02d}a.txt"
    alst.write_text("".join(f"file '{a}'\n" for a in wavs))
    audio = tmp / f"s{n:02d}.wav"
    ff("-f", "concat", "-safe", 0, "-i", alst, "-ac", 2, "-ar", 48000, audio)

    # overlays (picture-in-picture) and the shot's own label/caption on top
    inputs, chain, last, extra_audio = ["-i", base], [], "0:v", []
    for j, o in enumerate(shot.get("overlays", [])):
        at = o.get("at", 0)
        dur = o.get("dur", total - at)
        kind = frame_kind(o, o["box"])
        inner = inner_box(o["box"], kind) if kind else o["box"]
        v, a = segment(o, dur, inner, tmp, text, beats, web, f"s{n:02d}o{j}", bare=bool(kind))
        if kind:  # body and shadow under it, rounded corners on it
            x, y, under, mask = frame(v, inner, kind, text, stage=False)
            inputs += ["-loop", 1, "-framerate", FPS, "-t", total, "-i", under]
            ku = inputs.count("-i") - 1
            inputs += ["-i", v, "-loop", 1, "-framerate", FPS, "-t", dur, "-i", mask]
            kv, km = ku + 1, ku + 2
            chain.append(f"[{last}][{ku}:v]overlay=0:0:enable='between(t,{at},{at + dur})'[u{j}];[{km}:v]alphaextract[m{j}];"
                         f"[{kv}:v]format=rgba[f{j}];[f{j}][m{j}]alphamerge,setpts=PTS+{at}/TB[o{j}];"
                         f"[u{j}][o{j}]overlay={x}:{y}:eof_action=pass[v{j}]")
        else:
            inputs += ["-i", v]
            k = inputs.count("-i") - 1
            chain.append(f"[{k}:v]setpts=PTS+{at}/TB[o{j}];[{last}][o{j}]overlay={o['box'][0]}:{o['box'][1]}:eof_action=pass[v{j}]")
        last = f"v{j}"
        if a:
            extra_audio.append((a, at))
    for j, snd in enumerate(shot.get("sounds", [])):  # a sound file laid over the shot, e.g. the voice note being recorded
        if not (ROOT / snd["file"]).exists():  # footage/ is not committed: a fresh clone renders without the sound effects
            print(f"  shot {n}: no {snd['file']}, sound skipped", flush=True)
            continue
        wav = tmp / f"s{n:02d}snd{j}.wav"
        # a sound effect sets its own gain in dB (too short for loudnorm); the voice note is levelled like the narration
        af = f"volume={snd['db']}dB" if "db" in snd else "loudnorm=I=-20:TP=-2"
        ff("-i", ROOT / snd["file"], "-ac", 2, "-ar", 48000, "-af", af, wav)
        extra_audio.append((wav, snd.get("at", 0)))
    # callouts: English on the frame (what the Hindi says, what the AI filed), html placed by its own CSS, faded in and out
    for j, c in enumerate(shot.get("callouts", [])):
        at = c.get("at", 0)
        end = min(total, at + c.get("dur", total - at))
        inputs += ["-loop", 1, "-t", total, "-i", text.png(pick(c, "html"))]
        k = inputs.count("-i") - 1
        chain.append(f"[{k}:v]format=rgba,fade=t=in:st={at}:d=0.4:alpha=1,fade=t=out:st={end - 0.3}:d=0.3:alpha=1[cf{j}];"
                     f"[{last}][cf{j}]overlay=0:'18*pow(max(0,1-(t-{at})/0.5),3)':enable='between(t,{at},{end})'[c{j}]")
        last = f"c{j}"
    span = shot.get("caption_span", [0, total])  # seconds into the shot the caption shows
    # label_at "right" keeps the shot's label off a phone on the left; caption_css moves the caption (e.g. off a PiP)
    lab_cls = "label r" if shot.get("label_at") == "right" else "label"
    for key, html_, enable in (("label", f'<div class="{lab_cls}">{{}}</div>', ""),
                               ("caption", f'<div class="cap" style="{shot.get("caption_css", "")}">{{}}</div>',
                                f":enable='between(t,{span[0]},{span[1]})'")):
        if pick(shot, key):
            inputs += ["-i", text.png(html_.format(esc(pick(shot, key))))]
            k = inputs.count("-i") - 1
            chain.append(f"[{last}][{k}:v]overlay=0:0{enable}[t{key}]")
            last = f"t{key}"
    out = tmp / f"s{n:02d}.mp4"
    if chain:
        ff(*inputs, "-filter_complex", ";".join(chain), "-map", f"[{last}]", "-t", total, *VENC, "-an", out)
    else:
        shutil.copy(base, out)
    for j, (a, at) in enumerate(extra_audio):  # overlay sound (e.g. the phone playing the warning) mixed in at its time
        mixed = tmp / f"s{n:02d}mix{j}.wav"
        ms = int(at * 1000)
        ff("-i", audio, "-i", a, "-filter_complex", f"[1]adelay={ms}|{ms}[d];[0][d]amix=inputs=2:normalize=0:duration=first",
           "-ac", 2, "-ar", 48000, mixed)
        audio = mixed
    return out, audio


def loudness(src: pathlib.Path, dst: pathlib.Path, target: float = -15.0) -> pathlib.Path:
    """Two-pass loudnorm to `target` LUFS as one linear gain (no pumping). YouTube turns loud videos down but never
    turns quiet ones up, and the raw mix measured -19.8 LUFS."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP=-1.5:LRA=20:print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(out[out.rindex("{"):out.rindex("}") + 1])
    ff("-i", src, "-af", f"loudnorm=I={target}:TP=-1.5:LRA=20:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
       f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']},aresample=48000",
       "-ac", 2, dst)
    return dst


def sub_cues(src: pathlib.Path, max_chars: int = 76) -> list:
    """Burned-in subtitles stay on one line: a longer cue is halved, at a comma in its middle third (else at the space
    nearest the middle), its time shared by length, until every piece fits. A wrapped line would run into the labels."""
    def sec(s):
        h, m, r = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(r.replace(",", "."))

    def split(a, b, txt):
        if len(txt) <= max_chars:
            return [(a, b, txt)]
        n = len(txt)
        cuts = [i for i, c in enumerate(txt) if c == "," and n / 3 < i < 2 * n / 3] or [i for i, c in enumerate(txt) if c == " "]
        i = min(cuts, key=lambda i: abs(i - n / 2))
        head, tail = txt[:i + 1].strip(), txt[i + 1:].strip()
        mid = a + (b - a) * len(head) / (len(head) + len(tail))
        return split(a, mid, head) + split(mid, b, tail)

    cues = []
    for block in src.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        a, b = (sec(x.strip()) for x in lines[1].split("-->"))
        cues += split(a, b, " ".join(lines[2:]))
    return cues


def subs_track(cues: list, text: Text, tmp: pathlib.Path) -> pathlib.Path:
    """The subtitles as one image track (ffconcat: a png per cue, a blank between), drawn by Chromium in the cards' type."""
    blank = text.png("")
    lines, clock = ["ffconcat version 1.0"], 0.0
    for a, b, t in cues:
        if a > clock:
            lines += [f"file '{blank}'", f"duration {a - clock:.3f}"]
        lines += [f"file '{text.png(f'<div class=sub>{esc(t)}</div>')}'", f"duration {b - a:.3f}"]
        clock = b
    lines += [f"file '{blank}'", "duration 1", f"file '{blank}'"]
    track = tmp / "subs.ffconcat"
    track.write_text("\n".join(lines) + "\n")
    return track


def main() -> None:
    edl = json.loads((ROOT / "video/edl.json").read_text())
    beats_path = ROOT / edl["beats"]
    beats = {b["beat"]: b["t"] for b in json.loads(beats_path.read_text())} if beats_path.exists() else {}
    shots = [s for s in edl["shots"] if not ONLY or str(s["n"]) == ONLY]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # scratch files go next to the output, not /tmp: on a machine where /tmp is RAM, 1080p intermediates got the render killed
    with tempfile.TemporaryDirectory(dir=OUT.parent, prefix=".build-") as td:
        tmp = pathlib.Path(td)
        text = Text(tmp)
        try:
            rendered = []
            for s in shots:
                rendered.append(render_shot(s, tmp, text, beats, edl["web"]))
                print(f"  shot {s['n']:>2}  {s['t'][0]:>3}–{s['t'][1]:<3} s", flush=True)
            track = subs_track(sub_cues(ROOT / SUBS), text, tmp) if SUBS and not ONLY else None
        finally:
            text.close()
        (tmp / "v.txt").write_text("".join(f"file '{v}'\n" for v, _ in rendered))
        (tmp / "a.txt").write_text("".join(f"file '{a}'\n" for _, a in rendered))
        ff("-f", "concat", "-safe", 0, "-i", tmp / "v.txt", "-c", "copy", tmp / "video.mp4")
        ff("-f", "concat", "-safe", 0, "-i", tmp / "a.txt", "-ac", 2, "-ar", 48000, tmp / "diegetic.wav")
        audio = tmp / "diegetic.wav"
        if VOICE and not ONLY:  # mono narration copied to both channels at full level (a plain upmix costs it 3 dB)
            ff("-i", ROOT / VOICE, "-i", audio, "-filter_complex", "[0]aresample=48000,pan=stereo|c0=c0|c1=c0[v];"
               "[v][1]amix=inputs=2:normalize=0:duration=longest", tmp / "mix.wav")
            audio = loudness(tmp / "mix.wav", tmp / "mix-norm.wav")
        video = tmp / "video.mp4"
        if track:
            ff("-i", video, "-f", "concat", "-safe", 0, "-i", track, "-filter_complex",
               "[1:v]format=rgba[s];[0:v][s]overlay=0:0:eof_action=pass", *VENC, "-an", tmp / "video-subs.mp4")
            video = tmp / "video-subs.mp4"
        ff("-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", OUT)
    d = duration(OUT)
    print(f"{OUT}  {int(d // 60)}:{d % 60:04.1f}  (limit 3:00)")


if __name__ == "__main__":
    main()
