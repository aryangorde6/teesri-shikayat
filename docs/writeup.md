# Teesri Shikayat — submission writeup (draft)

*Paste into the form. Fill the two links on submission day. Status lines marked ⚠ change if the Bedrock quota arrives.*

**Teesri Shikayat ("the third complaint") is a tripwire for dirty tap water.** When three homes close together report dirty water, everyone around them is warned, and only the residents can close the case. Heat and Water track. Demo setting: Dongri, B ward, Mumbai.

## The problem

Every monsoon in Mumbai, the water from my tap turns dirty, and I never know whether the house next door has it too. Mumbai logged 1,514 contaminated-water complaints from January to August 2026. B ward had 4.03% unfit samples against 0.28% citywide. On 30 Sep 2026 the BMC asked for *immediate alerts to residents* (Free Press Journal, 1 Oct 2026). A leaking line pulls sewage into one lane, but complaints arrive one at a time and nobody connects them. In Indore's Bhagirathpura (Dec 2025), residents complained about foul water from mid-December, and the first illness came on Dec 27. Over 1,400 people fell ill. A judicial commission examined 36 deaths.

## What I built

1. **Join in one tap.** Scan a QR code, open the Telegram bot, share your location and tap हाँ to consent. There is no app to install and no form to fill.
2. **Complain the way people do: a Hindi voice note.** Amazon Transcribe (hi-IN) writes it down. Amazon Nova fills a fixed schema (colour, smell, since when, who is ill), and code validates every field. If the model can't read the note, the resident answers three button questions instead.
3. **The tripwire is code, not AI.** It fires on 3 different homes, every pair within 250 m, within 72 h. If all three homes are within 30 m (one building, one tank), there is no area alarm; those flats get tank-cleaning advice instead. A report belongs to at most one incident, enforced by a DynamoDB transaction.
4. **One case per incident.** A Step Functions case briefs a local volunteer in Hindi, and one tap approves the warning. Every enrolled home in the 250 m ring then gets a Hindi warning as text plus an Amazon Polly voice note: boil water, ORS, see a doctor, and the nearest public hospital. The ward office gets a formal email with no names or numbers.
5. **Closed at the tap, not on paper.** When the ward office says "resolved", that only counts as a request to close, and Cedar denies it. The residents are asked instead. Any "not clean" reopens the case. At least 3 "clean" answers and no "not clean" closes it, and silence never does.

**The model decides language; code decides actions.** The tripwire, the ring, the recipients, the timers and the closure rule are plain, tested code (48 tests). Cedar checks every side effect and every agent tool call, and fails closed. Every decision appears on the console's Safety tab. A human approves every broadcast.

The demo uses 22 simulated homes on a phone wall, labelled on screen, plus my real phone. Simulated homes go through the same code path as a real phone, via a channel adapter.

## Where AWS fits

- **Lambda** (Function URLs) runs the Telegram webhook, the console API, the tripwire and the case steps.
- **S3 + Transcribe (hi-IN) + EventBridge** turn voice notes into transcripts. **Bedrock (Nova 2 Lite)** extracts the fields.
- **DynamoDB Streams → EventBridge Pipes** (filtered to new reports) feed the tripwire Lambda.
- **Step Functions** (Standard) holds each case for days: the volunteer approval is a task token, the warning fans out through a Map state, and timers handle the ward reply and the check-in rounds.
- **Strands Agents SDK** runs the case agent's three goals: brief the volunteer, write to the ward office, handle the ward office's reply. It has at most 6 tool calls per goal and falls back to fixed templates on any error.
- **Cedar** (cedarpy) holds 8 policies, including only-residents-close and no-PII-to-authority.
- **Polly** (Kajal, neural Hindi) speaks the warnings, synthesised once per incident and reused.
- **SES** sends the ward office email.
- **Open Data on AWS:** GHS-POP 2025 (100 m), read from the JRC bucket, gives the population of each ring (~20,100 people in the demo ring).
- **CDK (Python)** deploys everything as one stack in ap-south-1. Secrets live in SSM Parameter Store.
- **Cost:** one incident (24 homes warned, one reopen) costs about ₹1 ($0.011), measured from a live run's Step Functions history and Lambda logs and priced with the AWS Pricing API.

⚠ This AWS account's Bedrock quota was 0 throughout the build (support case open). Voice notes therefore fall back to the button questions, and the case agent runs in template mode. Agent mode is tested offline with a scripted model and switches on with one setting.

## Links

- Repo: https://github.com/aryangorde6/teesri-shikayat
- Live console: https://eirioqqhvtvve3aw5xhpje2wju0jztrl.lambda-url.ap-south-1.on.aws/console
- Video: _(YouTube link)_

## AI tools used

Built with help from AI coding agents (Claude, in Claude Code) for code, tests and docs. _(Aryan: edit this line to say it in your own words.)_

*Not affiliated with BMC or any water board.*
