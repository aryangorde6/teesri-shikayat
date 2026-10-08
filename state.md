# State: what's built so far

Last updated: Thu 08 Oct 2026, 17:00 IST · Event: WeMakeDevs × AWS Environmental Hacks (Heat and Water), Oct 8–11

**Teesri Shikayat** ("the third complaint"): residents send Hindi voice notes about dirty tap water on Telegram. When 3 homes within 250 m report it inside 72 h, everyone enrolled nearby is warned, and only residents can close the case.

## Done

| When | What | Commit | Verified |
|---|---|---|---|
| Thu 12:49 | Repo, README with the AI-tools note | `8b224ad` | — |
| Thu 12:51 | CDK stack: DynamoDB table (streams + GSI1), S3 media bucket, one arm64 Python 3.13 Lambda behind a public Function URL. Telegram webhook checks the secret-token header; secrets live in SSM. | `8660d4d` | ✅ echo on the real phone, 12:58 |
| Thu 13:05 | **Joining:** `/start <ward>` → location → consent buttons → joined. **Voice:** voice note → S3 → Transcribe hi-IN → Transcribe-finished event → Nova fills a fixed schema → code validates → report saved → Hindi text receipt + Polly Kajal voice. **Fallback:** if the model can't read it, the resident answers 3 button questions (colour, smell, since when); a failed read is never counted as clean. **Channel adapter:** Telegram today, the simulated phone wall uses the same interface. Re-delivered webhooks and double taps can't create a second report. | `90b5c38` | ✅ phone, 13:15: Transcribe heard "पानी गंदा है"; Nova refused (quota 0) → buttons → brown/smell/3 days → text + Kajal voice receipt |

| Thu 13:30 | **Tripwire:** every new report → DynamoDB Streams → EventBridge Pipe (filter: `RPT#` inserts) → Tripwire Lambda (rule in code, no model). Fires when ≥3 different homes report dirty water within 72 h and every pair is within 250 m → `INC#` incident with "3 homes · 212 m · 71 h" numbers. All within 30 m (one building) → tank advice to those homes, no alarm. A report within 250 m of an open incident joins it. A report belongs to at most one incident (one DynamoDB transaction), so two simultaneous third reports make exactly one incident. Fallback wording fixed: "sorry, couldn't hear" only when nothing was heard. | `ca6d1ed` | ✅ live smoke test 13:28: 4 labelled test reports in Dongri → Pipe → `incident` (4 homes · 202 m · 50 h); test items deleted after |
| Thu 15:10 | **Ring population:** `scripts/precompute_population.py` read a 3 km × 3 km window around Dongri from GHS-POP 2025 (100 m, `s3://jrc-ghsl`, Open Data on AWS) once into `src/teesri/data/ghs_pop_dongri.json`; the Lambda sums the part of each cell inside the ring. Incidents store `ring_pop`, or "NO DATA" (never 0). **Demo scenario:** `scripts/scenario.py reset [--mine] | seed | building | stand-in | status`. 22 simulated homes A–V around your pin (A and B already reported, demo clock ~71 h / 20 h ago, 212 m apart), one building 600 m north (3 flats). Homes are findable by place for ring warnings. | `e9b319d`, `587a38a` | ✅ live: A none, B none, stand-in third report → incident 3 homes · 212 m · 70.8 h · ~20,100 people; building → tank advice; reset after |
| Thu 16:15 | **Case workflow (Step Functions, Fri AM block done early):** one Standard execution per incident (named by the incident id). Brief → volunteer card with हाँ, भेजें / अभी नहीं (task token) → warning text + Kajal voice to every enrolled home in the ring (Map) → ward office email (no names/numbers; stored for the console test inbox, SES once an inbox is set) → wait for the ward reply → "Resolved" is a close request: **Cedar DENY, only residents can close** → check-ins ("पानी साफ़ है?"; a नहीं ends the round at once) → REOPENED ↺ | CLOSED_AT_TAP (≥3 clean, 0 dirty, by the quorum evaluator) | STILL_OPEN (silence never closes). **Cedar** (`policy.py`, cedarpy): 7 policies, fail-closed (safe defaults, evaluation error = DENY), every decision an `EVT#` item. Agent goals run in **template mode** (no Bedrock quota). Scenario CLI gained `volunteer phone|sim`, `approve`, `ward-reply`, `answer <home> yes|no`; reset stops running cases. | `4f0adba` | ✅ live: approve → 24 homes warned (all Cedar ALLOW), email stored, ward "Resolved" → `ward_office close_case DENY only-residents-close` → E answers नहीं → REOPENED → waiting for the ward again; reset after |
| Thu 16:55 | **Console** at `<FunctionUrl>/console` (Fri night block, done early): OSM map with home dots + the red 250 m ring and its card ("3 homes · 212 m · 71 h → likely pipe-leak zone", "~20,100 people… GHS-POP"), phone wall (A–V, volunteer, building, my phone; warned homes pulse, voice chips play the Polly warning), Case tab (step ladder, Hindi brief, ward reply, timeline), **Safety tab** (every Cedar decision; DENY rows big and red), test inbox (the ward email), "+2 days (demo clock)" badge, one-building toast. Public `/api/state` masks Telegram ids (phone-1) and rounds real homes to ~100 m; demo controls need the console token (SSM `/teesri/console-token`, never printed). | `c622d51` | ✅ checked in the browser pane at 1600×900 through a full live run (ring, 24 warned, DENY row, REOPENED); reset after |

**Tests:** 40 passing (`.venv/bin/python -m pytest -q`): console API hides Telegram ids + rounds real homes, demo controls need the token and only answer for simulated homes, full case (brief, only the volunteer can approve, 23 warned / 20 never complained, email has no ids, ward claim → DENY, नहीं → REOPENED, 3 clean → CLOSED_AT_TAP), warning without approval DENY, closure quorum incl. silence ≠ closed, 5 Cedar policy tests, demo story end to end (3 homes · 212 m · 71 h, 23 enrolled in the ring, 20 never complained), one building + reset keeps real homes, ring population (partial cells, NO DATA never 0), tripwire (fire at 3 homes · 212 m · 71 h, one home 300 m away, 73 h span, same home ×3, clear water never counts, one building → tank advice once, 4th report joins, two simultaneous third reports → one incident, stream re-delivery), webhook secret, joining, declining deletes data, re-delivered updates ignored, model path, button fallback incl. double tap, voice before joining, geohash, distances, field validation, receipt text, "heard but no details" wording.

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

## Next (from the plan)

1. ✅ Phone home pin set to Dongri, B ward (18.9622, 72.8368, OpenStreetMap) directly in the table: Telegram on a computer cannot send a chosen location. To change it from the phone app: 📎 → Location → search the place → tap it. The 13:15 test report stays at the old spot, outside any ring; clear test data before recording.
2. ✅ Population + demo scenario (done Thu afternoon, ahead of plan).
3. ✅ Step Functions case, approval, warning, email (template mode). **Left for Fri AM:** Strands agent in place of the templates once a model works (shot 10's PII DENY and shot 11's "agent tries close_case" need it); SES test inbox (needs you to verify an address).
4. ✅ Cedar on every action + Safety tab; ward "resolved" → close DENY → check-ins → REOPENED / CLOSED_AT_TAP.
5. ✅ Console. Still to do: Strands agent mode (waiting on Bedrock), Indore replay tab (shot 12), cost per incident (shot 13), README, SES test inbox (needs you). **Sat 14:00 feature freeze**, then video.

## Open issues

- **Nova quota is 0** (AWS support case open). Voice notes fall back to buttons until it's approved. If not approved by **Fri 10:00 IST**, the agent is built on a model the account can already use, and swapped to Nova later.
- Kickoff details (submission deadline in IST, form fields) not recorded yet.
- A brand-new Pipe starts reading the stream a minute or two after it says RUNNING (starting position LATEST). Not a problem once it has been running; for the demo it is deployed days ahead.
