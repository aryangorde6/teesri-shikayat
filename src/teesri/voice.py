"""Voice in (Telegram OGG -> S3 -> Transcribe hi-IN) and voice out (Polly Kajal)."""
import json
import logging
import os

import boto3

log = logging.getLogger()
_s3 = _transcribe = _polly = None


def _clients():
    global _s3, _transcribe, _polly
    if _s3 is None:
        _s3, _transcribe, _polly = boto3.client("s3"), boto3.client("transcribe"), boto3.client("polly")
    return _s3, _transcribe, _polly


def job_name(hh_id: str, message_id: int) -> str:
    """One job per voice message. Re-delivered webhooks hit ConflictException instead of a 2nd job."""
    return f"vn_{hh_id}_{message_id}"


def start_transcription(name: str, ogg: bytes) -> bool:
    s3, transcribe, _ = _clients()
    bucket = os.environ["BUCKET"]
    s3.put_object(Bucket=bucket, Key=f"voice/{name}.ogg", Body=ogg, ContentType="audio/ogg")
    try:
        transcribe.start_transcription_job(
            TranscriptionJobName=name,
            LanguageCode="hi-IN",
            MediaFormat="ogg",
            Media={"MediaFileUri": f"s3://{bucket}/voice/{name}.ogg"},
            OutputBucketName=bucket,
            OutputKey=f"transcripts/{name}.json",
        )
        return True
    except transcribe.exceptions.ConflictException:
        return False


def read_transcript(name: str) -> tuple[str, str]:
    s3, _, _ = _clients()
    key = f"transcripts/{name}.json"
    doc = json.load(s3.get_object(Bucket=os.environ["BUCKET"], Key=key)["Body"])
    return " ".join(t["transcript"] for t in doc["results"]["transcripts"]).strip(), key


def speak(text: str) -> bytes:
    _, _, polly = _clients()
    out = polly.synthesize_speech(Engine="neural", VoiceId="Kajal", LanguageCode="hi-IN", OutputFormat="mp3", Text=text)
    return out["AudioStream"].read()
