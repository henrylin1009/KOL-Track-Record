"""
groq_transcriber.py — Groq Whisper API 轉錄封裝
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_RETRIES = 5
RPM_SLEEP_SEC = 3.0


def transcribe_audio(audio_path: str) -> str:
    """將音頻檔轉成繁體中文文字。遇 429 指數退避重試。"""
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY 未設定，請填入 .env")

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(audio_path)

    ext = path.suffix.lower().lstrip(".")
    mime = {
        "m4a": "audio/m4a",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "opus": "audio/opus",
    }.get(ext, "application/octet-stream")

    audio_bytes = path.read_bytes()
    boundary = "----GroqBoundary7MA4YWxk"

    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        audio_bytes,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="model"\r\n\r\n',
        config.GROQ_WHISPER_MODEL.encode(),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\n',
        b"zh\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="response_format"\r\n\r\n',
        b"json\r\n",
        f"--{boundary}--\r\n".encode(),
    ])

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            GROQ_TRANSCRIBE_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "trading-model/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(RPM_SLEEP_SEC)
            return data.get("text", "").strip()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                wait = min(60, 2 ** attempt * 5)
                time.sleep(wait)
                continue
            detail = e.read().decode()[:300]
            raise RuntimeError(f"Groq API HTTP {e.code}: {detail}") from e
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(f"Groq 轉錄失敗: {last_err}")
