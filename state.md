# State: what's built so far

Last updated: Thu 08 Oct 2026, 13:10 IST · Event: WeMakeDevs × AWS Environmental Hacks (Heat and Water), Oct 8–11

**Teesri Shikayat** ("the third complaint"): residents send Hindi voice notes about dirty tap water on Telegram. When 3 homes within 250 m report it inside 72 h, everyone enrolled nearby is warned, and only residents can close the case.

## Done

| When | What | Commit | Verified |
|---|---|---|---|
| Thu 12:49 | Repo, README with the AI-tools note | `8b224ad` | — |
| Thu 12:51 | CDK stack: DynamoDB table (streams + GSI1), S3 media bucket, one arm64 Python 3.13 Lambda behind a public Function URL. Telegram webhook checks the secret-token header; secrets live in SSM. | `8660d4d` | ✅ echo on the real phone, 12:58 |
| Thu 13:05 | **Joining:** `/start <ward>` → location → consent buttons → joined. **Voice:** voice note → S3 → Transcribe hi-IN → Transcribe-finished event → Nova fills a fixed schema → code validates → report saved → Hindi text receipt + Polly Kajal voice. **Fallback:** if the model can't read it, the resident answers 3 button questions (colour, smell, since when); a failed read is never counted as clean. **Channel adapter:** Telegram today, the simulated phone wall uses the same interface. Re-delivered webhooks and double taps can't create a second report. | `90b5c38` | ⏳ deployed; waiting for the phone test |

**Tests:** 15 passing (`.venv/bin/python -m pytest -q`): webhook secret, joining, declining deletes data, re-delivered updates ignored, model path, button fallback incl. double tap, voice before joining, geohash, distances, field validation, receipt text.

## Live resources (AWS ap-south-1, stack `Teesri`)

- Function URL: https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/ (`/` health, `/tg` Telegram webhook)
- Bot: @TeesriShikayatBot (webhook set by `scripts/set_webhook.py`)
- SSM: `/teesri/telegram/bot-token`, `/teesri/telegram/webhook-secret` (SecureString; never printed or committed)
- EventBridge rule: Transcribe job state change (`vn_*`) → the same Lambda

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
| `RPT#<hh>-<msg_id>` | `META` | hh_id, ts, lat, lon, colour, smell, since_days, illness, vulnerable, source (nova/buttons), transcript; GSI1 = `GH6#<geohash6>` / ts |
| `UPD#<update_id>` | `META` | Telegram de-duplication (TTL 2 days) |

## Next (from the plan)

1. **Phone test** of joining + voice (use a Dongri pin, not your home location).
2. **Thu night:** DynamoDB Streams → EventBridge Pipes (`RPT#` inserts) → tripwire Lambda (≥3 homes, 250 m, 72 h; one-building guard at 30 m) → `INC#` with a conditional write. Tests for the 7 tripwire cases. GHS-POP population grid for the demo ring.
3. **Fri AM:** Step Functions case (named by incident id) → Strands agent brief → volunteer approval (task token) → Polly warning to every enrolled home in the ring + SES email to the ward office.
4. **Fri PM:** Cedar on every action + Safety tab trace; ward office "resolved" → agent `close_case` DENY → check-ins → REOPENED / CLOSED_AT_TAP.
5. **Fri night:** console (map + ring, phone wall, Safety tab, scenario button). **Sat 14:00 feature freeze**, then video.

## Open issues

- **Nova quota is 0** (AWS support case open). Voice notes fall back to buttons until it's approved. If not approved by **Fri 10:00 IST**, the agent is built on a model the account can already use, and swapped to Nova later.
- Kickoff details (submission deadline in IST, form fields) not recorded yet.
