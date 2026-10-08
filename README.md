# Teesri Shikayat — the third complaint

**A tripwire for dirty tap water.** When three homes close together report dirty water, everyone around them is warned, and only the residents can close the case.

Built for the WeMakeDevs × AWS **Environmental Hacks** (Heat and Water track), Oct 8–11, 2026. Demo setting: Dongri, B ward, Mumbai. Not affiliated with BMC or any water board.

## The problem

- **Mumbai logged 1,514 contaminated-water complaints from January to August 2026.** On 30 Sep 2026 the BMC Standing Committee asked for a coordinated response with *immediate alerts to residents* ([Free Press Journal, 1 Oct 2026](https://www.freepressjournal.in/mumbai/mumbai-bmc-orders-24x7-action-on-contaminated-water-complaints-after-1514-cases-in-2026)).
- Averages hide pockets: 0.28% of samples were unfit citywide in 2025-26, but **4.03% in B ward (Dongri/Umarkhadi)** (same source). A leaking service line pulls sewage into one lane, not the whole city.
- **Complaints arrive one by one, and nobody connects them.** In Indore's Bhagirathpura (Dec 2025), residents reported discoloured, foul water from mid-December; the first illness came on Dec 27 and over 1,400 people fell ill ([Wikipedia](https://en.wikipedia.org/wiki/2025_Indore_drinking_water_contamination)). A judicial commission examined 36 deaths and linked 24 directly to sewage in the pipeline, as reported by [ETV Bharat](https://www.etvbharat.com/en/bharat/600-page-report-unravels-bhagirathpura-deaths-in-indore-enn26090102772) (the report is not public).

BMC's SOP asks for immediate alerts to residents. Teesri Shikayat does that from the street up, and lets residents confirm when the tap is clean.

## How it works

1. **Join in one tap.** Scan a QR code → Telegram bot → share your location → tap हाँ (consent). No app, no forms.
2. **Complain the way people do: a Hindi voice note.** Amazon Transcribe (hi-IN) writes it down; Amazon Nova fills a fixed schema (colour, smell, since when, who is ill); code validates every field. If the model can't read it, the resident answers three button questions instead. A failed read never counts as "clean".
3. **The tripwire (code, no AI).** Every new report flows DynamoDB Streams → EventBridge Pipes → a rule: **3 different homes, every pair within 250 m, within 72 h.** If all three are within 30 m (one building, one tank), there's no area alarm; those flats get tank-cleaning advice instead. A report belongs to at most one incident (one DynamoDB transaction), so two simultaneous "third" reports make exactly one incident.
4. **A case per incident (Step Functions).** The case agent briefs a local volunteer in Hindi; one tap approves. Then every enrolled home in the 250 m ring gets a Hindi warning (text + Amazon Polly voice): boil water, ORS, see a doctor, the nearest public hospital. The ward office gets a formal email **with no names or numbers**.
5. **Closed at the tap, not on paper.** When the ward office says "resolved", that is a request to close the case, and Cedar denies it: only residents can close a case. Every home in the ring is asked "पानी साफ़ है?". Any "not clean" reopens the case at once; at least 3 "clean" and no "not clean" closes it; silence never closes it.

```mermaid
flowchart LR
  TG[Telegram voice note] --> L[API Lambda] --> S3[(S3)] --> TR[Transcribe hi-IN] --> EB[EventBridge] --> L
  L -->|"Nova schema or buttons"| DDB[(DynamoDB)]
  DDB -->|Streams| P["EventBridge Pipes<br/>RPT inserts only"] --> TW["Tripwire Lambda<br/>rule in code"]
  TW -->|incident| SF[Step Functions case]
  SF --> C["Case Lambda<br/>Cedar on every action"]
  C --> V["Volunteer approval<br/>task token"]
  C --> W["Ring warning<br/>Map + Polly"]
  C --> M[Ward office email]
  C --> K["Check-ins: REOPENED or CLOSED_AT_TAP"]
  POP["GHS-POP 2025<br/>Open Data on AWS"] -.-> TW
```

## The model decides language; code decides actions

- The tripwire, the ring, the recipients, the timers and the closure rule are plain code with tests.
- A human volunteer approves every broadcast.
- **Cedar** (`src/teesri/policy.py`) checks every side effect and every agent tool call, and fails closed (missing context or an evaluation error is a DENY). Every decision is logged and shown on the console's Safety tab.

| Policy | Rule |
|---|---|
| only-residents-close | Nobody but the quorum evaluator, with a quorum of residents, can close a case |
| no-pii-to-authority | The ward office email may not contain names or phone numbers (checked in the draft itself) |
| allowlisted-recipients | Messages and email only to enrolled homes and the configured inbox |
| approval-before-broadcast | No warning without the volunteer's approval |
| approved-templates-only | Broadcasts only from fixed, reviewed templates |
| consent-before-message | Only homes that said हाँ are messaged |
| read-only-before-approval | While preparing a case, the agent may only read |

**Case agent (Strands).** Three goals: brief the volunteer, write to the ward office, handle the ward office's reply. Numbers in its output come from code; a brief that cites a report that doesn't exist, or adds numbers, is rejected. At most 6 tool calls per goal; any failure falls back to fixed templates. *Status: this AWS account's Bedrock quota is still 0 (support case open), so the deployed case runs in template mode; agent mode is tested offline with a scripted model and switches on with `AGENT_MODE=agent`.*

## What's real and what's simulated

- **Real:** the Telegram bot, the voice pipeline, the tripwire, Step Functions, Cedar, Polly, the ring population and map data, and my own phone.
- **Simulated, and labelled on screen:** homes A–V on the phone wall (they use the same code path as a real phone, through a channel adapter), the "+2 days" demo clock, the ward office's reply (a console button), and the ward office inbox (a test inbox).
- **Indore replay:** a labelled reconstruction. Complaint dates are not public, so it assumes three complaints on Dec 15–17.
- **Channel:** Telegram for the demo. WhatsApp plugs into the same adapter (`src/teesri/channel.py`).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                                           # 45 tests, no AWS account needed
./build.sh && AWS_PROFILE=<profile> cdk deploy                          # one stack: Teesri (ap-south-1)
AWS_PROFILE=<profile> .venv/bin/python scripts/set_webhook.py           # point the Telegram bot at the stack
AWS_PROFILE=<profile> .venv/bin/python scripts/scenario.py seed          # 22 simulated homes; then open <FunctionUrl>/console
```

Secrets live in SSM Parameter Store (`/teesri/telegram/bot-token`, `/teesri/telegram/webhook-secret`, `/teesri/console-token`), never in code.

## Data

- Population in a warning ring: **GHS-POP R2023A, epoch 2025, 100 m** (European Commission, Joint Research Centre; CC BY 4.0), read from the Registry of Open Data on AWS (`s3://jrc-ghsl/ghs-pop/`) by `scripts/precompute_population.py`. Shown as "~N people"; when the grid doesn't cover a ring it says "NO DATA", never 0.
- Place coordinates and the nearest public hospital: © OpenStreetMap contributors (ODbL).

## Privacy

A home's location is used only after the resident taps हाँ; tapping नहीं deletes what was saved. Reports keep the transcript and a few symptom flags, nothing more. The authority sees counts and anonymised reports, never names or numbers. The public console shows no Telegram ids and rounds real homes to about 100 m.

## AI tools used

This project was built with help from AI coding agents (Claude).
