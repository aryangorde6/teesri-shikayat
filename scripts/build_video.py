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
    CSS = ("*{margin:0;box-sizing:border-box} body{width:%dpx;height:%dpx;background:transparent;position:relative;"
           "font-family:'Noto Sans','Noto Sans Devanagari',sans-serif;color:#e7edf2}"
           ".label{position:absolute;left:40px;bottom:126px;font-size:26px;background:rgba(15,20,25,.85);border:1px solid #8a99a8;"
           "border-radius:999px;padding:8px 20px}"
           ".cap{position:absolute;left:50%%;transform:translateX(-50%%);bottom:120px;font-size:44px;font-weight:700;"
           "background:rgba(15,20,25,.88);padding:16px 30px;border-radius:14px;text-align:center;max-width:1600px}"
           ".ph{position:absolute;inset:0;border:4px dashed #f59e0b;display:flex;flex-direction:column;justify-content:center;"
           "align-items:center;text-align:center;padding:30px;background:#161d24}"
           ".ph b{font-size:34px;color:#f59e0b} .ph span{font-size:26px;margin-top:14px;color:#cbd5e1}")

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


def segment(src: dict, dur: float, box, tmp: pathlib.Path, text: Text, beats: dict, web: str, tag: str) -> tuple:
    """One visual source -> an mp4 of exactly dur seconds at box size (w, h), plus its audio as a wav (or None)."""
    x, y, w, h = box
    out, wav = tmp / f"{tag}.mp4", None
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,fps={FPS}"
    if "card" in src:
        ff("-loop", 1, "-t", dur, "-i", ROOT / pick(src, "card"), "-vf", fit, *VENC, "-an", out)
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
    ff("-ss", start, "-i", path, "-t", dur, "-vf", f"{fit},tpad=stop_mode=clone:stop_duration={dur}", "-t", dur, *VENC, "-an", out)
    if src.get("audio") and has_audio(path):
        wav = tmp / f"{tag}.wav"
        ff("-ss", start, "-i", path, "-t", dur, "-vn", "-ac", 2, "-ar", 48000, "-af", f"loudnorm=I=-20:TP=-2,apad=whole_dur={dur}",
           "-t", dur, wav)
    return out, wav


def silence(dur: float, path: pathlib.Path) -> pathlib.Path:
    ff("-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo", path)
    return path


def render_shot(shot: dict, tmp: pathlib.Path, text: Text, beats: dict, web: str) -> tuple:
    n, (t0, t1) = shot["n"], shot["t"]
    total = t1 - t0
    parts, clock, vids, wavs = shot["parts"], 0.0, [], []
    for i, p in enumerate(parts):
        dur = p.get("dur", total - clock) if i < len(parts) - 1 else total - clock
        box = p.get("box", [0, 0, W, H])
        v, a = segment(p, dur, box, tmp, text, beats, web, f"s{n:02d}p{i}")
        if box != [0, 0, W, H]:  # place the box on the full frame
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
        v, a = segment(o, dur, o["box"], tmp, text, beats, web, f"s{n:02d}o{j}")
        inputs += ["-i", v]
        k = len(inputs) // 2 - 1
        chain.append(f"[{k}:v]setpts=PTS+{at}/TB[o{j}];[{last}][o{j}]overlay={o['box'][0]}:{o['box'][1]}:eof_action=pass[v{j}]")
        last = f"v{j}"
        if a:
            extra_audio.append((a, at))
    span = shot.get("caption_span", [0, total])  # seconds into the shot the caption shows
    for key, html_, enable in (("label", '<div class="label">{}</div>', ""),
                               ("caption", '<div class="cap">{}</div>', f":enable='between(t,{span[0]},{span[1]})'")):
        if pick(shot, key):
            inputs += ["-i", text.png(html_.format(esc(pick(shot, key))))]
            k = len(inputs) // 2 - 1
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


def one_line_subs(src: pathlib.Path, dst: pathlib.Path, max_chars: int = 100) -> None:
    """Burned-in subtitles stay on one line: a longer cue becomes two cues, split at a comma in its middle third (else
    at the space nearest the middle), its time shared by length. A wrapped line would run into the labels above it."""
    def sec(s):
        h, m, r = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(r.replace(",", "."))

    def stamp(x):
        ms = round(x * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    cues = []
    for block in src.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        a, b = (sec(x.strip()) for x in lines[1].split("-->"))
        txt = " ".join(lines[2:])
        if len(txt) > max_chars:
            n = len(txt)
            cuts = [i for i, c in enumerate(txt) if c == "," and n / 3 < i < 2 * n / 3] or \
                   [i for i, c in enumerate(txt) if c == " "]
            i = min(cuts, key=lambda i: abs(i - len(txt) / 2))
            head, tail = txt[:i + 1].strip(), txt[i + 1:].strip()
            mid = a + (b - a) * len(head) / (len(head) + len(tail))
            cues += [(a, mid, head), (mid, b, tail)]
        else:
            cues.append((a, b, txt))
    dst.write_text("".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{t}\n\n" for n, (a, b, t) in enumerate(cues, 1)),
                   encoding="utf-8")


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
        finally:
            text.close()
        (tmp / "v.txt").write_text("".join(f"file '{v}'\n" for v, _ in rendered))
        (tmp / "a.txt").write_text("".join(f"file '{a}'\n" for _, a in rendered))
        ff("-f", "concat", "-safe", 0, "-i", tmp / "v.txt", "-c", "copy", tmp / "video.mp4")
        ff("-f", "concat", "-safe", 0, "-i", tmp / "a.txt", "-ac", 2, "-ar", 48000, tmp / "diegetic.wav")
        audio = tmp / "diegetic.wav"
        if VOICE and not ONLY:
            ff("-i", ROOT / VOICE, "-i", audio, "-filter_complex", "[0]aresample=48000,aformat=channel_layouts=stereo[v];"
               "[v][1]amix=inputs=2:normalize=0:duration=longest", tmp / "mix.wav")
            audio = tmp / "mix.wav"
        video = tmp / "video.mp4"
        if SUBS and not ONLY:
            one_line_subs(ROOT / SUBS, tmp / "subs.srt")
            ff("-i", video, "-vf", f"subtitles={tmp / 'subs.srt'}:force_style='FontName=Noto Sans,FontSize=13,PrimaryColour=&H00FFFFFF,"
               "BackColour=&HB0000000,BorderStyle=3,Outline=3,Shadow=0,MarginV=14'", *VENC, "-an", tmp / "video-subs.mp4")
            video = tmp / "video-subs.mp4"
        ff("-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", OUT)
    d = duration(OUT)
    print(f"{OUT}  {int(d // 60)}:{d % 60:04.1f}  (limit 3:00)")


if __name__ == "__main__":
    main()
