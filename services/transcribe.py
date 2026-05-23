import os
import tempfile

import yt_dlp
from openai import OpenAI


def transcribe_video(url: str) -> str | None:
    """Download a video, extract audio, and transcribe with Whisper.

    Returns the transcript text, or None if no speech was found.
    Raises on download/network/API failure so the caller can mark the job failed.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)

    with tempfile.TemporaryDirectory() as tmp:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp, "audio.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "64",
                }
            ],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        mp3_path = None
        for fname in os.listdir(tmp):
            if fname.endswith(".mp3"):
                mp3_path = os.path.join(tmp, fname)
                break
        if not mp3_path:
            raise RuntimeError("Audio extraction produced no mp3 file")

        with open(mp3_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

    text = (result.text or "").strip()
    return text or None
