# Teesri Shikayat — submission writeup (draft)

*One section per form field, named as on First Commit's form (Sep 2026); match them when this event's form opens. Paste each section into its field. Fill the YouTube link on submission day.*

## Project title

Teesri Shikayat: a tripwire for dirty tap water

## Track

Heat and Water

## Description

Every monsoon in Mumbai, the water from my tap turns dirty, and I never know whether the house next door has it too. A leaking service line pulls sewage into one lane, but complaints reach the ward office one at a time and nobody connects them. Mumbai logged 1,514 contaminated-water complaints from January to August 2026; B ward had 4.03% unfit samples against 0.28% citywide, and on 30 Sep the BMC asked for immediate alerts to residents (Free Press Journal, 1 Oct 2026). In Indore's Bhagirathpura, residents complained about foul water from mid-December 2025; the first illness came on Dec 27, over 1,400 people fell ill, and a judicial commission examined 36 deaths.

Teesri Shikayat ("the third complaint") joins those complaints up. Residents scan a code, open the Telegram bot, share their location and consent, and complain the way people actually do: a Hindi voice note. When three different homes within 250 m report dirty water inside 72 hours, a local volunteer approves one warning with a tap, and every enrolled home in that ring gets a Hindi warning as text and a voice note: boil water, ORS, see a doctor, the nearest public hospital. Most of them never complained (20 of the 23 warned in the demo). The ward office gets a formal email with counts, never names or numbers. When the ward office says "resolved", that only asks to close the case: the residents are asked, any "not clean" reopens it, and silence never closes it. It is for the families on one pipe, the volunteer who knows the lane, and a ward office that gets one joined-up case instead of scattered complaints.

In the demo, homes A–V on the phone wall are simulated and labelled on screen; my phone is real.

*(Optional, only if it happened: one or two sentences on what the people you asked said about dirty water, and how many joined the bot without help.)*

## How did you use AWS in your project?

Ship it (services), one CDK stack in ap-south-1, three Lambdas (Python 3.13, arm64, reserved concurrency as a cost guard).

**Listening.** A Telegram voice note reaches a Lambda Function URL, goes to S3 and to Amazon Transcribe (hi-IN). An EventBridge rule on Transcribe's job-state events (our `vn_` jobs, COMPLETED or FAILED) wakes the same Lambda to finish the report, so nothing polls.

**Reading.** This account's Bedrock quota was 0 in every region we tried for the whole event (support case open), so the language model is one we host: Gemma 4 E4B in llama.cpp on one EC2 Graviton4 instance (c8g.4xlarge). It has no inbound ports at all: requests arrive on an encrypted SQS queue, answers come back as DynamoDB items, and its IAM role may write only items keyed `MODEL#heartbeat` or `MODELRESP#…` (a `dynamodb:LeadingKeys` condition). The llama.cpp build is SHA-256-pinned, the weights live in S3, IMDSv2 is required, the disk is encrypted, and it stops itself after an idle hour ($0.43/h while on). About 2 s per voice note. The model only fills a fixed schema (colour, smell, since when, who is ill); code validates every field, and a keyword reader takes over when the model is off. Nova on Bedrock plugs into the same code with one setting.

**Detecting.** One on-demand DynamoDB table with Streams. An EventBridge Pipe filters the stream to INSERTs whose key starts with `RPT#` (new reports only; a failed batch is bisected) and calls the tripwire Lambda. The tripwire is code, not AI: 3 different homes, every pair within 250 m, within 72 h; all three within 30 m is one building's tank, so those flats get tank advice and no area alarm. A DynamoDB transaction lets a report belong to at most one incident, so two "third" reports at the same moment make exactly one. The ring's population comes from GHS-POP 2025 (100 m) in the Registry of Open Data on AWS (`s3://jrc-ghsl`): ~20,100 people in the demo ring, and "NO DATA", never 0, where the grid doesn't reach.

**Acting.** Each incident starts one Step Functions Standard execution, named after the incident, one Lambda per task. The volunteer's approval is a task token, so the case waits for a human at no cost (no answer in time: UNAPPROVED). A Map state then warns every home in the ring, with an Amazon Polly (Kajal, Hindi) voice note synthesised once per incident. The ward office email goes through SES (a test inbox in the demo). The ward's reply is a second task token; "Resolved" only starts the residents' check-in, a third task token per round, up to three rounds with a Wait between supply windows. Any "not clean" loops back to REOPENED; at least 3 "clean" and no "not clean" gives CLOSED_AT_TAP.

**Guarding.** A Strands Agents SDK case agent writes the volunteer brief and the ward email and handles the reply: at most 6 tool calls per goal, fixed templates on any failure. Every side effect and every agent tool call goes through Cedar (8 policies, fails closed), among them only-residents-close, no-pii-to-authority, approval-before-broadcast and consent-before-message. Every decision is on the console's Safety tab; in the video the agent's `close_case` is denied there. Secrets are in SSM Parameter Store, readable only under `/teesri/*`.

**Cost.** One real incident (23 homes warned, one reopen) cost ₹0.94 ($0.0107), measured from its own Step Functions history and Lambda logs and priced with the AWS Pricing API; the model instance is extra while it is on.

Build it (open source): Strands Agents SDK, Cedar (cedarpy) and the AWS CDK (Python).

**Proof.** 66 tests (moto, no AWS account needed) cover the tripwire, the ring, the closure rule, the Cedar policies and the public API; `scripts/preflight.py` runs 11 checks against the live stack. The console and the bot are live now.

## Team leader's contributions

Solo, over four days from an empty folder, with one author on every commit. I chose the problem and the Dongri / B ward setting, made the product and design decisions, tested every flow on my own phone, recorded the footage and directed the video. AI tools used: Claude Code (Anthropic) as my AI coding agent; it wrote most of the code, the tests, the docs and the video-assembly scripts from those decisions. The narration is a synthetic voice (Chatterbox TTS). Inside the product, Gemma 4 on our EC2 instance reads the voice notes and drafts the case messages, and Cedar policies check every action. *(Aryan: edit so every "I" claim is exactly true, then delete this note.)*

## Help us evaluate you: your feedback on the AWS services you used

Two things that cost me time this week. (1) **Bedrock quota.** Every Nova and Claude quota showed 0 in ap-south-1, ap-southeast-1 and us-east-1. Singapore first said the account was "currently being verified… normally takes less than 2 hours", briefly showed 8M tokens a minute, then dropped to 0; the quota requests filed on Oct 5 still say "case opened". Nothing in the console says the zero is an account-level hold, so it took hours of probing to tell it apart from a region or model problem; one status line would have saved that, and it is why the model runs on EC2. (2) **EventBridge Pipes.** A new Pipe says RUNNING but starts reading the DynamoDB stream a minute or two later (starting position LATEST), so reports written in that window are skipped without a trace. A "reading from" time on the Pipe, or a warning next to LATEST, would make that visible.

## What did you like about the AWS services you used?

Step Functions task tokens carried the whole case: a Standard execution waits days for a volunteer, a ward office or residents at no cost, and the Map, Choice and Wait states made "reopen until the residents say clean" a loop in the definition, not in code. EventBridge Pipes' filter meant the tripwire only ever sees new reports, and DynamoDB transactions settled two simultaneous third reports in one call. IAM's `LeadingKeys` condition let the model instance write only its own two kinds of items. A Graviton4 instance runs a 4B-parameter model at about 2 s per voice note for $0.43 an hour, and stops when idle. Transcribe hi-IN returned a clean Hindi voice note word for word, and Polly's Kajal voice reads every warning in Hindi, synthesised once per incident and reused. The Registry of Open Data gave a population for every ring straight from S3. CDK holds all of it in one stack, and a deploy takes about a minute.

## Links

- GitHub: https://github.com/aryangorde6/teesri-shikayat
- Deployed (live console): https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/console
- YouTube: _(link on submission day)_
- Try the bot (Telegram, in Hindi): https://t.me/TeesriShikayatBot?start=B. One report gets a receipt; an alarm needs three neighbours.

*Not affiliated with BMC or any water board.*
