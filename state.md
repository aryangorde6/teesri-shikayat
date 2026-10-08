# State: what's built so far

Last updated: Thu 08 Oct 2026, 18:42 IST · Event: WeMakeDevs × AWS Environmental Hacks (Heat and Water), Oct 8–11

**Teesri Shikayat** ("the third complaint"): residents send Hindi voice notes about dirty tap water on Telegram. When 3 homes within 250 m report it inside 72 h, everyone enrolled nearby is warned, and only residents can close the case.

## Done

| When | What | Commit | Verified |
|---|---|---|---|
| Thu 12:49 | Repo, README with the AI-tools note | `8b224ad` | — |
| Thu 12:51 | CDK stack: DynamoDB table (streams + GSI1), S3 media bucket, one arm64 Python 3.13 Lambda behind a public Function URL. Telegram webhook checks the secret-token header; secrets live in SSM. | `8660d4d` | ✅ echo on the real phone, 12:58 |
| Thu 13:05 | **Joining:** `/start <ward>` → location → consent buttons → joined. **Voice:** voice note → S3 → Transcribe hi-IN → Transcribe-finished event → Nova fills a fixed schema → code validates → report saved → Hindi text receipt + Polly Kajal voice. **Fallback:** if the model can't read it, the resident answers 3 button questions (colour, smell, since when); a failed read is never counted as clean. **Channel adapter:** Telegram today, the simulated phone wall uses the same interface. Re-delivered webhooks and double taps can't create a second report. | `90b5c38` | ✅ phone, 13:15: Transcribe heard "पानी गंदा है"; Nova refused (quota 0) → buttons → brown/smell/3 days → text + Kajal voice receipt |

| Thu 13:30 | **Tripwire:** every new report → DynamoDB Streams → EventBridge Pipe (filter: `RPT#` inserts) → Tripwire Lambda (rule in code, no model). Fires when ≥3 different homes report dirty water within 72 h and every pair is within 250 m → `INC#` incident with "3 homes · 212 m · 71 h" numbers. All within 30 m (one building) → tank advice to those homes, no alarm. A report within 250 m of an open incident joins it. A report belongs to at most one incident (one DynamoDB transaction), so two simultaneous third reports make exactly one incident. Fallback wording fixed: "sorry, couldn't hear" only when nothing was heard. | `ca6d1ed` | ✅ live smoke test 13:28: 4 labelled test reports in Dongri → Pipe → `incident` (4 homes · 202 m · 50 h); test items deleted after |
| Thu 14:54 | **Ring population:** `scripts/precompute_population.py` read a 3 km × 3 km window around Dongri from GHS-POP 2025 (100 m, `s3://jrc-ghsl`, Open Data on AWS) once into `src/teesri/data/ghs_pop_dongri.json`; the Lambda sums the part of each cell inside the ring. Incidents store `ring_pop`, or "NO DATA" (never 0). **Demo scenario:** `scripts/scenario.py reset [--mine] | seed | building | stand-in | status`. 22 simulated homes A–V around your pin (A and B already reported, demo clock ~71 h / 20 h ago, 212 m apart), one building 600 m north (3 flats). Homes are findable by place for ring warnings. | `e9b319d`, `587a38a` | ✅ live: A none, B none, stand-in third report → incident 3 homes · 212 m · 70.8 h · ~20,100 people; building → tank advice; reset after |
| Thu 15:10 | **Case workflow (Step Functions, Fri AM block done early):** one Standard execution per incident (named by the incident id). Brief → volunteer card with हाँ, भेजें / अभी नहीं (task token) → warning text + Kajal voice to every enrolled home in the ring (Map) → ward office email (no names/numbers; stored for the console test inbox, SES once an inbox is set) → wait for the ward reply → "Resolved" is a close request: **Cedar DENY, only residents can close** → check-ins ("पानी साफ़ है?"; a नहीं ends the round at once) → REOPENED ↺ | CLOSED_AT_TAP (≥3 clean, 0 dirty, by the quorum evaluator) | STILL_OPEN (silence never closes). **Cedar** (`policy.py`, cedarpy): 7 policies, fail-closed (safe defaults, evaluation error = DENY), every decision an `EVT#` item. Agent goals run in **template mode** (no Bedrock quota). Scenario CLI gained `volunteer phone|sim`, `approve`, `ward-reply`, `answer <home> yes|no`; reset stops running cases. | `4f0adba` | ✅ live: approve → 24 homes warned (all Cedar ALLOW), email stored, ward "Resolved" → `ward_office close_case DENY only-residents-close` → E answers नहीं → REOPENED → waiting for the ward again; reset after |
| Thu 15:21 | **Console** at `<FunctionUrl>/console` (Fri night block, done early): OSM map with home dots + the red 250 m ring and its card ("3 homes · 212 m · 71 h → likely pipe-leak zone", "~20,100 people… GHS-POP"), phone wall (A–V, volunteer, building, my phone; warned homes pulse, voice chips play the Polly warning), Case tab (step ladder, Hindi brief, ward reply, timeline), **Safety tab** (every Cedar decision; DENY rows big and red), test inbox (the ward email), "+2 days (demo clock)" badge, one-building toast. Public `/api/state` masks Telegram ids (phone-1) and rounds real homes to ~100 m; demo controls need the console token (SSM `/teesri/console-token`, never printed). | `c622d51` | ✅ checked in the browser pane at 1600×900 through a full live run (ring, 24 warned, DENY row, REOPENED); reset after |
| Thu 15:25–15:42 | **Strands case agent** (`case_agent.py`, `AGENT_MODE=agent`): three goals, every tool call through Cedar, a DENY returns to the agent as the tool result (email with phone numbers → DENY → redraft; `close_case` → DENY → asks residents); max 6 tool calls; any failure → templates. Tested offline with a scripted model; **deployed in template mode** (no Bedrock quota). **Indore replay** tab (labelled reconstruction, dates re-checked on Wikipedia today). **README** rewritten. **Cost per incident** measured on a live full cycle (warn → reopened → CLOSED_AT_TAP at 15:37): $0.064, 94% Polly; now one Polly call per message (verified 0 re-synths for 24 homes) → ~$0.011 ≈ ₹1. **QR** for `t.me/TeesriShikayatBot?start=B` (`assets/qr-start-B.png`). **`video/slides-data.json`**: every on-screen number with its source. | `fa20414` … `b9d049d` | ✅ CLOSED_AT_TAP seen live (3 clean, 0 dirty, window closed) |
| Thu 15:48–15:52 | **Playwright console tour** (`scripts/console_tour.py`): records the WEB shots at 1920×1080 + `beats.json`; `--third phone` waits for the real phone (one live run films PHONE + WEB together). Rehearsal **quiet mode** (`scenario.py quiet on|off`; red chip on the console while on). **`/stop` or `बंद`** deletes the home (lets shot 5 be filmed fresh). **`video/recording-checklist.md`**. | `4b2a1a7` … | ✅ 86 s rehearsal recorded (stand-in, real phones muted), frames checked |
| Thu 15:53–16:02 | README screenshots (labelled rehearsal); console usable at phone width; button tidying can no longer lose a tap; **`scripts/preflight.py`** (one command: webhook, Pipe, leftover cases, quiet mode, phone enrolled + clean, Nova, agent mode). | `b0990b2` … `b3c27b1` | ✅ preflight run: all green except your 13:15 test report (cleared by `reset --mine` on recording day) and Nova (quota 0) |
| Thu 17:00–17:56 | **Submission writeup** draft (`docs/writeup.md`: problem, build, where AWS fits, AI tools; links filled except the video). **Slide cards** for shots 2, 3, 4, 13, 14 (`scripts/build_cards.py` → `video/cards/`, every number from `slides-data.json`; `--mode template` variant without Nova/Strands). **Narration:** `video/narration/voiceover.md` (agent) + `voiceover-template.md`, one `lines.json` with every variant (44 sentences, incl. ALT "Dozens died."), Colab notebook; `video-tools/build-voice --lines` matches clips by text, so one Colab run covers every decision. Template-mode narration for shots 6/8/10/11 appended to `prep/video-script.md`. | `90ee072` … `65a06bf` | ✅ cards rendered and checked; build-voice ran on dummy clips for both variants (168 s, -19.9 LUFS) |
| Thu 17:47 | Real-phone rehearsal: **blocked**. Telegram Desktop can't be driven (Wayland, no automation); Telegram Web in Chrome needs a QR scan from the phone (Settings → Devices → Link Desktop Device). Kickoff page re-checked 17:50: deadline hour still TBA. | — | — |
| Thu 17:58–18:05 | **Video assembler:** `scripts/build_video.py` renders `video/edl.json` (14 shots: cards, console tour with in-points from `beats.json`, phone/AWS PiP boxes, labels, timed captions, diegetic audio, narration + burned subtitles; `--mode template`). Missing footage becomes labelled placeholders, so the whole cut can be previewed now. Assembly steps added to `video/recording-checklist.md`. | `76314b6` … | ✅ both animatics render at 2:47.9; frames checked; 720p preview sent to Aryan |
| Thu 18:06 | Writeup corrected: SES sends only once an inbox is verified (the demo uses the console's test inbox). | `8aaa361` | — |
| Thu 18:38–18:41 | **Real-phone rehearsal passed** (Claude drove Telegram Web in Chrome): `reset` → `seed` → `volunteer phone` → `stand-in`. Volunteer card on the phone at 18:38 ("3 घर · 212 मीटर · 71 घंटे"); tapped **हाँ, भेजें** → confirmation + Hindi warning text + 0:24 Polly voice note at 18:39; `ward-reply Resolved` → "asking the residents first" + पानी साफ़ है? at 18:39; tapped **नहीं** → "answer recorded" + reopen text + 0:07 voice note at 18:40. Console: chip "reopened ×1" (red), mail stored, feed incident → warned → ward_says_resolved → reopened. Buttons vanish after a tap. Then `reset` (1 case stopped, 237 rows; Aryan's 13:16 report kept). Fixed on the way: `scenario.py status` crashed on incident event rows. | `f440338` | ✅ whole chain on the real phone, ~3 min |

**Tests:** 48 passing (`.venv/bin/python -m pytest -q`): agent mode with a scripted model (PII email DENY → redraft, close DENY → check-ins, brief checked by code, 6-call limit, fallback to templates), console API hides Telegram ids + rounds real homes, demo controls need the token and only answer for simulated homes, full case (brief, only the volunteer can approve, 23 warned / 20 never complained, email has no ids, ward claim → DENY, नहीं → REOPENED, 3 clean → CLOSED_AT_TAP), warning without approval DENY, closure quorum incl. silence ≠ closed, 5 Cedar policy tests, demo story end to end (3 homes · 212 m · 71 h, 23 enrolled in the ring, 20 never complained), one building + reset keeps real homes, ring population (partial cells, NO DATA never 0), tripwire (fire at 3 homes · 212 m · 71 h, one home 300 m away, 73 h span, same home ×3, clear water never counts, one building → tank advice once, 4th report joins, two simultaneous third reports → one incident, stream re-delivery), webhook secret, joining, declining deletes data, re-delivered updates ignored, model path, button fallback incl. double tap, voice before joining, geohash, distances, field validation, receipt text, "heard but no details" wording.

## Live resources (AWS ap-south-1, stack `Teesri`)

- Function URL: https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/ (`/` health, `/tg` Telegram webhook)
- Bot: @TeesriShikayatBot (webhook set by `scripts/set_webhook.py`)
- SSM: `/teesri/telegram/bot-token`, `/teesri/telegram/webhook-secret` (SecureString; never printed or committed)
- EventBridge rule: Transcribe job state change (`vn_*`) → the same Lambda
- Tripwire Lambda `Teesri-Tripwire…` fed by Pipe `ReportsToTripwire-…` (DynamoDB stream, `RPT#` INSERT only)
- Case: Step Functions `CaseMachine…` + Case Lambda. Demo clock on (`DEMO_CLOCK=1`: 30 min to approve, 5 min check-in window)

## How to work on it

**Console:** https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/console — open "Demo controls" and paste the token once:
`AWS_PROFILE=hackathon aws ssm get-parameter --name /teesri/console-token --with-decryption --query Parameter.Value --output text --region ap-south-1`

```bash
cd ~/teesri-shikayat
.venv/bin/python -m pytest -q                                          # tests
./build.sh && AWS_PROFILE=hackathon cdk deploy --require-approval never  # deploy
AWS_PROFILE=hackathon .venv/bin/python scripts/set_webhook.py            # only if the URL changes
```

## Data model (as built)

| PK | SK | What |
|---|---|---|
| `HH#tg<chat_id>` / `HH#sim-<x>` | `PROFILE` | ward, lat, lon, consent_ts, channel, (sim: is_simulated, label); GSI1 = `HGH6#<geohash6>` / hh_id |
| `HH#sim-<x>` | `MSG#<ts>#<id>` | messages shown on the simulated phone wall |
| `DRAFT#<rpt>` | `META` | a voice note waiting for button answers (TTL 1 day) |
| `RPT#<hh>-<msg_id>` | `META` | hh_id, ts, lat, lon, colour, smell, since_days, illness, vulnerable, source (nova/buttons), transcript, inc_id once claimed; GSI1 = `GH6#<geohash6>` / ts |
| `INC#<inc-yyyymmdd-hash>` | `META` | status (OPEN … CLOSED_AT_TAP), centre lat/lon, ring_m 250, homes (set), report_ids (set), fired {homes, spread_m, span_h}; GSI1 = `IGH6#<geohash6>` / created_ts. Id comes from its earliest report and will name the Step Functions execution. |
| `UPD#<update_id>` | `META` | Telegram de-duplication (TTL 2 days) |
| `INC#<id>` | `EVT#<ts>#<ns>` | Cedar decision / case step: actor, action, decision, policy, reason (Safety tab) |
| `INC#<id>` | `CHK#<round>#<hh>` | check-in answer (clean true/false), first answer wins |
| `INC#<id>` | `MAIL#<ts>` | the ward office email (to, subject, body, via stored/ses) |
| `TOK#<short>` | `META` | Step Functions task token behind a Telegram button (TTL 14 days) |
| `CFG#volunteer` | `META` | which home gets the volunteer card |
| `ONCE#<key>` | `META` | "at most once per N hours" (e.g. tank advice per home per 72 h) |
| `FEED` | `<ts>#<id>` | what the console shows: tripwire decisions (incident / joined / one_building), later warnings and closures |

## Next

1. ✅ Thu: voice pipeline, tripwire, population, demo scenario, case workflow, Cedar, console, Indore replay, README, cost, QR, preflight, writeup draft, slide cards, narration scripts + Colab notebook, video assembler, real-phone rehearsal (18:41).
2. ✅ Real-phone rehearsal passed 18:41 (see Done). With the stand-in the ring has 24 homes (24 warned, 21 never complained); in the recording run the phone files the third report itself, so it is 23 / 20, matching the shot 9 caption.
3. **When Bedrock quota arrives:** set `AGENT_MODE` to `agent` in `infra/stack.py`, deploy, run one full case; Nova extraction starts working by itself (voice notes stop falling back to buttons). Shots 6 (Nova JSON), 10 (PII DENY) and 11 ("the agent tries close_case") need this. **Fri 10:00 IST cutoff:** record in template mode (`voiceover-template.md`, `build_cards.py --mode template`, `build_video.py --mode template`; the DENY is then the ward office's close request) or wait.
4. **Needs Aryan:**
   - (a) ✅ Telegram Web linked (18:37).
   - (b) Send the AWS support reply in `~/aws_environment/SEND-QUEUE.md`.
   - (c) Decide slot 2: "Thirty-six died." or the ALT "Dozens died." (the source says 36 deaths *examined*, 24 linked; Wikipedia 32).
   - (d) Run `video/narration/narration-chatterbox.ipynb` on a Colab T4 (~30 min; covers every variant), then listen to how "Teesri Shikayat" is pronounced.
   - (e) Put the AI-tools line in `docs/writeup.md` in your own words.
   - (f) Optional SES test inbox: verify an address in SES, then `aws ssm put-parameter --name /teesri/ward-inbox` and `/teesri/mail-from`.
5. Fri: polish only what's on camera. **Sat 14:00 feature freeze**, then record and assemble (follow `video/recording-checklist.md`: Before → The run → After → Assemble). Sun: YouTube (unlisted, check signed out), paste `docs/writeup.md` into the form, submit hours before the deadline.

## Open issues

- **Bedrock quota is 0** for every model and region tried (Nova throttled, Claude AccessDenied). Quota requests for Nova 2 Lite still `CASE_OPENED` (re-checked 17:52). Voice notes fall back to buttons; the case agent runs in template mode.
- **Deadline hour still TBA:** schedule page re-checked Thu 17:50 ("the hours are being finalised"). Rules page: a submission is a public repo, a YouTube video up to 3 minutes (public or unlisted), and a short writeup (problem, build, where AWS fits); the form closes hard. Form link and fields not published yet.
- Telegram Desktop can't be driven from this machine (Wayland, no automation); phone steps go through Telegram Web in Chrome (linked 18:37). Recording still needs the real phone screen (shots 5, 6, 8, 9, 11).
- The shot 9 caption ("20 of 23 … All 23") is fixed text in `video/edl.json`; check it against the console after the recording run.
- A brand-new Pipe starts reading the stream a minute or two after it says RUNNING (starting position LATEST). Not a problem once it has been running; for the demo it is deployed days ahead.
