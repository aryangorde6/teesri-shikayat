<!--
For AWS Builder Center. Paste everything below the line into the article editor.
Title field:       Three complaints, one warning: a dirty-water tripwire on AWS
Description field: Hindi voice notes on Telegram, a tripwire in plain code, and a Step Functions case that only the residents can close. What I built in four days for the WeMakeDevs × AWS Environmental Hacks, and what fought back.
Tags:              hackathon, aws-step-functions, amazon-transcribe, amazon-dynamodb, strands-agents, aws-lambda, amazon-polly, graviton
Images:            upload the three files named in the [IMAGE: …] lines from docs/img/, then delete those lines.
-->
---

Every monsoon in Mumbai, the water from my tap turns dirty, and I never know whether the house next door has it too. A leaking service line pulls sewage into one lane's supply, but the complaints reach the ward office one at a time and nobody joins them up.

I built **Teesri Shikayat** ("the third complaint") in four days for the WeMakeDevs × AWS Environmental Hacks, Heat and Water track. This is what it does, how it runs on AWS, and what fought back.

## The problem is bigger than my tap

Mumbai logged 1,514 contaminated-water complaints from January to August 2026, and B ward had 4.03% unfit water samples against 0.28% citywide (Free Press Journal, 1 Oct 2026). In Indore's Bhagirathpura, residents complained about foul water from mid-December 2025; over 1,400 people fell ill, and a judicial commission examined 36 deaths.

During the hackathon I phoned 11 people in Mumbai, Pune, Amravati, Delhi, Baroda and Vellore. Most had not known their water was dirty, and most said reaching the BMC or their local water authority was the hard part. A friend in Delhi had spent 2–3 days in hospital after a sewage pipe leak. Those are the two gaps I built for: the homes that don't know, and the complaints that never add up.

## The idea: the third complaint

One complaint is a bad day. Three from different homes close together is a pipe.

- Residents scan a QR code, open the Telegram bot, share their location and consent, and complain the way people actually do: **a Hindi voice note**.
- When **three different homes within 250 m report dirty water inside 72 hours**, a local volunteer gets a short brief and approves one warning with a tap.
- **Every enrolled home in that 250 m ring** gets a Hindi warning as text and as a voice note: boil the water, ORS, see a doctor, the nearest public hospital. In the demo, 20 of the 23 homes warned had never complained.
- The ward office gets one formal email with counts, **never names or phone numbers**.
- When the ward office says "resolved", that only *asks* to close the case. The residents are asked; any "not clean" reopens it, and silence never closes it.

[IMAGE: docs/img/console-warned.jpg — caption: The live console after the warning: the 250 m ring on the map and the homes that were warned.]

## How it runs on AWS

Everything is one **AWS CDK (Python)** stack in ap-south-1, with three **AWS Lambda** functions (Python 3.13, arm64, reserved concurrency as a cost guard).

```
Telegram voice note
  → Lambda Function URL → Amazon S3 → Amazon Transcribe (hi-IN)
  → Amazon EventBridge (job finished) → Lambda files the report in Amazon DynamoDB
  → DynamoDB Streams → EventBridge Pipe (new reports only) → tripwire Lambda
  → AWS Step Functions case:
       volunteer approves → warn the ring (Map state + Amazon Polly) → email the ward (Amazon SES)
       → ward replies "resolved" → residents asked → CLOSED_AT_TAP, or back to REOPENED
```

**Listening.** A voice note reaches a Lambda Function URL and goes to S3 and to Amazon Transcribe in Hindi (hi-IN). An EventBridge rule on Transcribe's job-state events wakes the same Lambda when the job finishes, so nothing polls.

**Detecting.** Reports land in one on-demand DynamoDB table with Streams. An EventBridge Pipe filters the stream down to new reports and calls the tripwire. The tripwire is plain code, not AI: three different homes, every pair within 250 m, within 72 hours. If all three are within 30 m, it's one building's water tank, so those flats get tank advice and there's no area alarm. The ring's population comes from GHS-POP 2025 on the **Registry of Open Data on AWS**, read straight from S3: about 20,100 people in the demo ring, and "NO DATA", never 0, where the grid doesn't reach.

**Acting.** Each incident starts one Step Functions Standard execution. The volunteer's approval is a **task token**, so the case waits for a human at no cost. A Map state warns every home in the ring, with one Polly (Kajal, Hindi) voice note synthesised per incident and reused. The ward office's reply is a second task token, and each round of residents' check-ins is a third. "Reopen until the residents say clean" is a loop in the state machine's definition, not in my code.

[IMAGE: docs/img/stepfunctions-run.jpg — caption: One real case in Step Functions: approval, warnings, the ward's reply, the residents' check-in, and the reopen.]

## An agent that isn't allowed to close the case

A case agent built with the **Strands Agents SDK** writes the volunteer's brief and the ward email, and reads the ward's reply. It gets at most 6 tool calls per goal and falls back to fixed templates on any failure.

Every side effect, and every tool call the agent makes, asks **Cedar** first: 8 policies that fail closed. Among them are *only-residents-close*, *no-pii-to-authority*, *approval-before-broadcast* and *consent-before-message*. In the demo, when the ward office says "resolved", the agent tries `close_case`, and Cedar says no. The console's Safety tab shows every decision.

[IMAGE: docs/img/console-deny.jpg — caption: The agent asks to close the case after the ward says "resolved"; Cedar denies it.]

## What fought back

**1. Bedrock quota was 0, everywhere, all week.** Every Nova and Claude quota showed 0 in ap-south-1, ap-southeast-1 and us-east-1. Singapore briefly showed 8M tokens a minute, then dropped back to 0. Nothing in the console said it was an account-level hold, so it took me hours to tell it apart from a region or model problem.

Lambda couldn't run a model (this account caps Lambda memory at 3,008 MB), so I hosted one myself: **Gemma 4 E4B in llama.cpp on one EC2 Graviton4 instance** (c8g.4xlarge). It has no inbound ports at all. Requests arrive on an encrypted SQS queue, answers go back as DynamoDB items, and its IAM role can write only its own two kinds of items, using a `dynamodb:LeadingKeys` condition. The llama.cpp build is SHA-256-pinned, IMDSv2 is required, and the instance stops itself after an idle hour. It reads a voice note in about 2 seconds for $0.43 an hour. The model only fills a fixed schema (colour, smell, since when, who is ill), code validates every field, and a keyword reader takes over when the model is off. Nova on Bedrock plugs into the same code with one setting.

**2. A brand-new EventBridge Pipe isn't listening yet.** It says RUNNING, but with starting position LATEST it starts reading the stream a minute or two later. Reports written in that window are skipped without a trace. My lesson: after creating a Pipe, send one canary record and watch it arrive before trusting it.

**3. Two "third" reports at the same moment.** If two neighbours report at once, both reports could see three homes and open two incidents. A DynamoDB transaction lets a report belong to at most one incident, so there is exactly one.

**4. "Resolved" is not the same as clean.** The easy design closes the case when the authority says so. Task tokens made the better rule cheap: the ward office's "resolved" only starts the residents' check-in, up to three rounds with a Wait between supply times. Any "not clean" loops back to REOPENED; at least three "clean" and none "not clean" gives CLOSED_AT_TAP.

## Securing it

Homes, consent and reports sit under my own **KMS** key (rotated yearly), with point-in-time recovery and deletion protection on the table. Voice notes and transcripts expire after 30 days. **CloudTrail** logs every API call with log-file validation. **IAM Access Analyzer** shows the bot's URL is the only part of the stack reachable from outside. A **GuardDuty** finding, a failed case, or any Lambda error emails a person through one **SNS** topic, via **CloudWatch** alarms.

## Cost and proof

One real incident (23 homes warned, one reopen) cost **₹0.94 ($0.0107)**. I measured it from its own Step Functions history and Lambda logs and priced it with the AWS Pricing API; the model instance is extra while it is on. 66 tests (pytest with moto, no AWS account needed) cover the tripwire, the ring, the closure rule, the Cedar policies and the public API, and run on GitHub Actions on every push.

## What it can't do yet

- **It needs neighbours on it.** In a lane where nobody has joined, nothing fires. Joining has to happen where water already gets talked about: a QR poster on the building's tank or the society notice board.
- **It detects complaints, not contamination.** Three complaints say "look here", not "this water is unsafe". The ward office still has to test the water.
- **The thresholds are chosen by hand.** 3 homes, 250 m and 72 hours were checked only against a replay of Indore's timeline. With a ward's real complaint records, they could be tuned.
- **Only Dongri, in Mumbai's B ward, has local population and hospital data**, and the bot speaks only Hindi on Telegram for now. Marathi and WhatsApp come next.

## How I built it

I built it solo, over four days, starting from an empty folder. I used Claude Code as my AI coding agent. I set the direction at each step (what to build, what to cut, how the video should look), reviewed the results and tested the bot on my own phone; it wrote most of the code. The narration in the demo video is a synthetic voice (Chatterbox TTS).

## Links

- Demo video (2:54): https://youtu.be/L0UteWpltyw
- Code: https://github.com/aryangorde6/teesri-shikayat
- Live console: https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/console
- Try the bot (Telegram, Hindi): https://t.me/TeesriShikayatBot?start=B

*Not affiliated with BMC or any water board.*
