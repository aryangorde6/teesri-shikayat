# Recording checklist (Sat, after the 14:00 freeze)

One live run films the PHONE shots and the WEB shots together: `console_tour.py --third phone` drives the console and waits for your phone at each step.

## Before

- [ ] Bedrock: if the quota has arrived, `AGENT_MODE` is `agent` in `infra/stack.py` and deployed (shots 6, 10, 11 need it). If not, decide: template mode, or wait.
- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py quiet off` (the console must NOT show the red "real phones muted" chip)
- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/scenario.py reset` — add `--mine` to also clear your phone's old test reports (otherwise your phone shows as "reported" before you've sent anything)
- [ ] Phone: Do Not Disturb off, volume up, Telegram open on @TeesriShikayatBot, `scrcpy --record phone.mp4` running
- [ ] AWS console (GNOME screencast, picture-in-picture): Step Functions → CaseMachine → latest execution open; crop out the account id and email
- [ ] Shot 5 (joining) on camera: send `बंद` first so you can join fresh. Then scan `assets/qr-start-B.png` → Start → 📎 → Location → **search "Dongri" and send that place (not your home)** → हाँ → "आप जुड़ गए ✅"

## The run

1. `AWS_PROFILE=hackathon .venv/bin/python scripts/console_tour.py --third phone` (seeds A–V, makes your phone the volunteer, records `video/web-tour/web-tour.webm` + `beats.json`)
2. When it prints "waiting for your voice note": send a ~4 s Hindi voice note, e.g. *"नल से भूरा पानी आ रहा है, बहुत बदबू है, दो दिन से"* (shot 6). Without Nova, answer the three buttons.
3. The ring snaps (shot 7). Your phone gets the volunteer card → tap **हाँ, भेजें** (shot 8; label: "demo: my phone plays the volunteer").
4. Your phone plays the warning (shot 9).
5. The tour sends the ward office reply ("+2 days", shot 11). Your phone asks "पानी साफ़ है?" → tap **नहीं, अभी भी गंदा** → REOPENED.
6. The tour ends on the Indore replay (shot 12).

## After

- [ ] `AWS_PROFILE=hackathon .venv/bin/python scripts/cost_per_incident.py` → put the ₹ figure into `video/slides-data.json` (shot 13)
- [ ] `scenario.py reset` (stops the case so it doesn't sit waiting for 7 days)
- [ ] Every label from the spec is on screen: "Simulated home A–V", "demo: my phone plays the volunteer", "+2 days (demo clock)", "Indore replay: reconstruction", "Not affiliated with BMC"
