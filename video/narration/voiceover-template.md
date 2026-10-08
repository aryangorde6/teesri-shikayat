# Voice-over (template mode: no Bedrock quota) — read against the video timeline

The narration from `~/aws_environment/prep/video-script.md`, one section per slot. `build-voice --script` reads the "## M:SS–M:SS · label" headings. Variants: `voiceover-template.md` (no Bedrock quota) and the line marked ALT in `lines.json` (slot 2). One Colab run (`narration-chatterbox.ipynb`) makes clips for every variant.

## 0:00–0:07 · 1 my tap

Every monsoon in Mumbai, the water from my tap turns dirty. I never knew if the house next door had it too.

## 0:07–0:15 · 2 Indore

In Indore last December, a leaking pipe pulled sewage into the taps. People complained one by one. Thirty-six died.

## 0:15–0:27 · 3 the idea

This is Teesri Shikayat, the third complaint. When three homes close together report dirty water, everyone around them is warned. And only the residents can close the case.

## 0:27–0:36 · 4 Mumbai

Mumbai logged over fifteen hundred dirty-water complaints this year. Last week, the city said: warn residents at once.

## 0:36–0:45 · 5 joining

Nothing new to learn. Scan a code, tap Start on Telegram, share your location, and you're in.

## 0:45–1:01 · 6 voice note

Then you complain the way people actually do: a voice note, in Hindi. Amazon Transcribe writes it down, and plain code picks out what matters: the colour, the smell, how long, and who's sick.

## 1:01–1:13 · 7 tripwire

Two neighbours already reported. Mine is the third within two hundred and fifty metres in three days. The tripwire fires, and the ring is marked as a likely pipe leak.

## 1:13–1:26 · 8 volunteer

A case opens in Step Functions. It sums up all three complaints for a local volunteer, in Hindi. One tap to approve.

## 1:26–1:38 · 9 warning

Everyone in the ring hears this. Twenty of these homes never complained.

## 1:38–1:47 · 10 ward email

The ward office gets a formal complaint. Names and numbers never leave the lane. Cedar checks that.

## 1:47–2:09 · 11 closed at the tap

Two days later, the ward office replies: resolved. That's a request to close the case, and Cedar says no. Only residents can close it. So it asks them. My tap says no. The case reopens.

## 2:09–2:22 · 12 Indore replay

Replayed on Indore's dates, the third complaint would have raised the alarm about ten days before the first person fell ill.

## 2:22–2:37 · 13 AWS

It all runs serverless on AWS. Step Functions holds each case for days, DynamoDB streams feed the tripwire, and Polly speaks Hindi. One incident costs about one rupee.

## 2:37–2:48 · 14 close

Built for the monsoon that floods the street and dirties the tap. Teesri Shikayat: closed at the tap, not on paper.
