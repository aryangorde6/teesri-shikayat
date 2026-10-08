# Recording checklist (Sat, after the 14:00 freeze)

One live run films the PHONE shots and the WEB shots together: `console_tour.py --third phone` drives the console and waits for your phone at each step.

## Before

- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/preflight.py` says READY (webhook, Pipe, no leftover case, quiet off, phone enrolled with no old reports, agent mode). Without Nova it prints a ⚠️ line, not a ❌: record in template mode.
- [ ] Model on: `AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py model on` (about 1 min; shots 6, 8, 10, 11 need it). Preflight then shows "Self-hosted model answers". After recording: `scenario.py model off` ($0.43/h while on; it also stops itself after an idle hour).
- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py quiet off` (the console must NOT show the red "real phones muted" chip)
- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py reset` — add `--mine` to also clear your phone's old test reports (otherwise your phone shows as "reported" before you've sent anything)
- [ ] Phone: Do Not Disturb off, volume up, Telegram open on @TeesriShikayatBot, `scrcpy --record phone.mp4` running
- [ ] AWS console (GNOME screencast, picture-in-picture): Step Functions → CaseMachine → latest execution open; crop out the account id and email
- [ ] Shot 5 (joining) on camera: send `बंद` first so you can join fresh. Then scan `assets/qr-start-B.png` → Start → 📎 → Location → **search "Dongri" and send that place (not your home)** → हाँ → "आप जुड़ गए ✅"

## The run

1. `AWS_PROFILE=hackathon .venv/bin/python scripts/console_tour.py --third phone` (seeds A–V, makes your phone the volunteer, records `video/web-tour/web-tour.webm` + `beats.json`)
2. When it prints "waiting for your voice note": send a ~4 s Hindi voice note, e.g. *"नल से भूरा पानी आ रहा है, बहुत बदबू है, दो दिन से"* (shot 6). Without Nova, the keyword reader files it straight away as long as you say a colour (पीला/भूरा/काला) or बदबू; otherwise the three buttons appear.
3. The ring snaps (shot 7). Your phone gets the volunteer card → tap **हाँ, भेजें** (shot 8; label: "demo: my phone plays the volunteer").
4. Your phone plays the warning (shot 9).
5. The tour sends the ward office reply ("+2 days", shot 11). Your phone asks "पानी साफ़ है?" → tap **नहीं, अभी भी गंदा** → REOPENED.
6. The tour ends on the Indore replay (shot 12).

## After

- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/cost_per_incident.py` → put the ₹ figure into `video/slides-data.json` (shot 13)
- [ ] `scenario.py reset` (stops the case so it doesn't sit waiting for 7 days)
- [ ] Every label from the spec is on screen: "Simulated home A–V", "demo: my phone plays the volunteer", "+2 days (demo clock)", "Indore replay: reconstruction", "Not affiliated with BMC"

## Assemble (after the footage)

Preview any time: `.venv/bin/python scripts/build_video.py --out video/out/animatic.mp4` renders the full 2:48. A missing clip shows as a labelled placeholder.

1. **Cards:** run `.venv/bin/python scripts/build_cards.py`, after putting the final ₹ figure into `video/slides-data.json`. In template mode, also run `--mode template --out video/cards/template`.
2. **Narration:** open `video/narration/narration-chatterbox.ipynb` in Colab (T4) → Run all → unzip the clips into one folder. Then run `~/aws_environment/video-tools/build-voice --clips <folder> --lines video/narration/lines.json --script video/narration/voiceover.md --length 168 --spread [--music <file>] --out video/out/voice.wav`. Use `voiceover-template.md` for template mode, or edit slot 2 to "Dozens died." if you choose the ALT line.
3. **Footage:** put `phone.mp4` (scrcpy), `aws.mp4` (screencast), `stock-tap.mp4` and `cam-tap.mp4` into `video/footage/`. Set each `"in": null` in `video/edl.json` to the second where that moment starts in your recording. The console tour needs nothing: its in-points come from `beats.json`.
4. **Check** that the shot 9 caption ("20 of 23 … All 23") matches what the console says in your run.
5. **Render:** `.venv/bin/python scripts/build_video.py --voice video/out/voice.wav --subs video/out/voice.srt [--mode template] --out video/out/teesri.mp4`. It must print 2:4x (the limit is 3:00).
