# State: what's built so far

Last updated: Thu 08 Oct 2026, 13:30 IST · Event: WeMakeDevs × AWS Environmental Hacks (Heat and Water), Oct 8–11

**Teesri Shikayat** ("the third complaint"): residents send Hindi voice notes about dirty tap water on Telegram. When 3 homes within 250 m report it inside 72 h, everyone enrolled nearby is warned, and only residents can close the case.

## Done

| When | What | Commit | Verified |
|---|---|---|---|
| Thu 12:49 | Repo, README with the AI-tools note | `8b224ad` | — |
| Thu 12:51 | CDK stack: DynamoDB table (streams + GSI1), S3 media bucket, one arm64 Python 3.13 Lambda behind a public Function URL. Telegram webhook checks the secret-token header; secrets live in SSM. | `8660d4d` | ✅ echo on the real phone, 12:58 |
| Thu 13:05 | **Joining:** `/start <ward>` → location → consent buttons → joined. **Voice:** voice note → S3 → Transcribe hi-IN → Transcribe-finished event → Nova fills a fixed schema → code validates → report saved → Hindi text receipt + Polly Kajal voice. **Fallback:** if the model can't read it, the resident answers 3 button questions (colour, smell, since when); a failed read is never counted as clean. **Channel adapter:** Telegram today, the simulated phone wall uses the same interface. Re-delivered webhooks and double taps can't create a second report. | `90b5c38` | ✅ phone, 13:15: Transcribe heard "पानी गंदा है"; Nova refused (quota 0) → buttons → brown/smell/3 days → text + Kajal voice receipt |

| Thu 13:30 | **Tripwire:** every new report → DynamoDB Streams → EventBridge Pipe (filter: `RPT#` inserts) → Tripwire Lambda (rule in code, no model). Fires when ≥3 different homes report dirty water within 72 h and every pair is within 250 m → `INC#` incident with "3 homes · 212 m · 71 h" numbers. All within 30 m (one building) → tank advice to those homes, no alarm. A report within 250 m of an open incident joins it. A report belongs to at most one incident (one DynamoDB transaction), so two simultaneous third reports make exactly one incident. Fallback wording fixed: "sorry, couldn't hear" only when nothing was heard. | `ca6d1ed` | ✅ live smoke test 13:28: 4 labelled test reports in Dongri → Pipe → `incident` (4 homes · 202 m · 50 h); test items deleted after |

**Tests:** 24 passing (`.venv/bin/python -m pytest -q`): tripwire (fire at 3 homes · 212 m · 71 h, one home 300 m away, 73 h span, same home ×3, clear water never counts, one building → tank advice once, 4th report joins, two simultaneous third reports → one incident, stream re-delivery), webhook secret, joining, declining deletes data, re-delivered updates ignored, model path, button fallback incl. double tap, voice before joining, geohash, distances, field validation, receipt text, "heard but no details" wording.

## Live resources (AWS ap-south-1, stack `Teesri`)

- Function URL: https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/ (`/` health, `/tg` Telegram webhook)
- Bot: @TeesriShikayatBot (webhook set by `scripts/set_webhook.py`)
- SSM: `/teesri/telegram/bot-token`, `/teesri/telegram/webhook-secret` (SecureString; never printed or committed)
- EventBridge rule: Transcribe job state change (`vn_*`) → the same Lambda
- Tripwire Lambda `Teesri-Tripwire…` fed by Pipe `ReportsToTripwire-…` (DynamoDB stream, `RPT#` INSERT only)

## How to work on it

```bash
cd ~/teesri-shikayat
.venv/bin/python -m pytest -q                                          # tests
./build.sh && AWS_PROFILE=hackathon cdk deploy --require-approval never  # deploy
AWS_PROFILE=hackathon .venv/bin/python scripts/set_webhook.py            # only if the URL changes
```

## Data model (as built)

| PK | SK | What |
|---|---|---|
| `HH#tg<chat_id>` | `PROFILE` | ward, lat, lon, consent_ts, channel |
| `HH#sim-<x>` | `MSG#<ts>#<id>` | messages shown on the simulated phone wall |
| `DRAFT#<rpt>` | `META` | a voice note waiting for button answers (TTL 1 day) |
| `RPT#<hh>-<msg_id>` | `META` | hh_id, ts, lat, lon, colour, smell, since_days, illness, vulnerable, source (nova/buttons), transcript, inc_id once claimed; GSI1 = `GH6#<geohash6>` / ts |
| `INC#<inc-yyyymmdd-hash>` | `META` | status (OPEN … CLOSED_AT_TAP), centre lat/lon, ring_m 250, homes (set), report_ids (set), fired {homes, spread_m, span_h}; GSI1 = `IGH6#<geohash6>` / created_ts. Id comes from its earliest report and will name the Step Functions execution. |
| `UPD#<update_id>` | `META` | Telegram de-duplication (TTL 2 days) |
| `ONCE#<key>` | `META` | "at most once per N hours" (e.g. tank advice per home per 72 h) |
| `FEED` | `<ts>#<id>` | what the console shows: tripwire decisions (incident / joined / one_building), later warnings and closures |

## Next (from the plan)

1. ✅ Phone home pin set to Dongri, B ward (18.9622, 72.8368, OpenStreetMap) directly in the table: Telegram on a computer cannot send a chosen location. To change it from the phone app: 📎 → Location → search the place → tap it. The 13:15 test report stays at the old spot, outside any ring; clear test data before recording.
2. **Thu night:** GHS-POP population for the ring ("~N people", "NO DATA" never 0); demo scenario script (22 simulated homes A–V, demo clock).
3. **Fri AM:** Step Functions case (named by incident id) → Strands agent brief → volunteer approval (task token) → Polly warning to every enrolled home in the ring + SES email to the ward office.
4. **Fri PM:** Cedar on every action + Safety tab trace; ward office "resolved" → agent `close_case` DENY → check-ins → REOPENED / CLOSED_AT_TAP.
5. **Fri night:** console (map + ring, phone wall, Safety tab, scenario button). **Sat 14:00 feature freeze**, then video.

## Open issues

- **Nova quota is 0** (AWS support case open). Voice notes fall back to buttons until it's approved. If not approved by **Fri 10:00 IST**, the agent is built on a model the account can already use, and swapped to Nova later.
- Kickoff details (submission deadline in IST, form fields) not recorded yet.
- A brand-new Pipe starts reading the stream a minute or two after it says RUNNING (starting position LATEST). Not a problem once it has been running; for the demo it is deployed days ahead.
