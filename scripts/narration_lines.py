"""Every sentence the narration might say, numbered once, for one Chatterbox run that covers every variant
(agent mode, template mode, the ALT line for slot 2). Writes video/narration/lines.json and the Colab notebook.

Usage: python3 scripts/narration_lines.py
Then: build-voice --clips <dir> --lines video/narration/lines.json --script video/narration/voiceover[-template].md
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "video/narration"
SCRIPTS = ["voiceover.md", "voiceover-template.md"]
ALT = ["Dozens died."]  # slot 2, if "Thirty-six died" is too strong for the source (36 deaths examined; Wikipedia: 32)
SLOT = re.compile(r"^## (\d+):(\d\d)\s*[–-]\s*(\d+):(\d\d)\s*·\s*(.*)$")


# --- the same splitting and spoken forms as video-tools/build-voice, so the texts match exactly ----------------
def slots(path):
    out, cur = [], None
    for line in pathlib.Path(path).read_text().splitlines():
        m = SLOT.match(line)
        if m:
            cur = [m[5].strip(), []]
            out.append(cur)
        elif cur is not None and line.strip() and not line.lstrip().startswith(("#", ">", "|", "<!--")):
            cur[1].append(re.sub(r"\[[^\]]*\]\s*", "", line.strip()))
    return [(label, " ".join(t)) for label, t in out]


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“$])", text) if s.strip()]


def spoken(s):
    s = re.sub(r"\$0(?:\.00)?\b", "zero dollars", s)
    s = re.sub(r"\$(\d[\d,.]*)", r"\1 dollars", s)
    s = re.sub(r"(\d)\s*%", r"\1 percent", s)
    s = re.sub(r"(\d)\s*M\b", r"\1 million", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    return s.replace("—", ", ").replace("–", " to ")


def main() -> None:
    lines, seen = [], set()
    for name in SCRIPTS:
        for label, text in slots(DIR / name):
            for s in sentences(text):
                say = spoken(s)
                if say not in seen:
                    seen.add(say)
                    lines.append({"n": len(lines) + 1, "label": label, "say": say})
    for say in ALT:
        lines.append({"n": len(lines) + 1, "label": "2 Indore (ALT)", "say": say})
    (DIR / "lines.json").write_text(json.dumps(lines, ensure_ascii=False, indent=1) + "\n")

    nb = json.loads((DIR / "notebook.tmpl.json").read_text())
    cell = nb["cells"][2]
    src = "".join(cell["source"]).replace("__LINES__", json.dumps([{"n": l["n"], "say": l["say"]} for l in lines], ensure_ascii=False))
    cell["source"] = src.splitlines(keepends=True)
    (DIR / "narration-chatterbox.ipynb").write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(lines)} sentences -> {DIR / 'lines.json'} and narration-chatterbox.ipynb")


if __name__ == "__main__":
    main()
