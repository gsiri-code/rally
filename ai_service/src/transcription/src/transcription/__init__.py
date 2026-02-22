from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


def transcribe_mp3(*, mp3_path: str, request_id: str) -> dict[str, Any]:
    audio_file = Path(mp3_path)
    if not audio_file.exists() or not audio_file.is_file():
        raise RuntimeError(f"MP3 file not found: {mp3_path}")

    with audio_file.open("rb") as file_handle:
        payload = file_handle.read()
    return transcribe_bytes(
        audio_bytes=payload,
        filename=audio_file.name,
        mime_type="audio/mpeg",
        request_id=request_id,
    )


def transcribe_bytes(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    request_id: str,
) -> dict[str, Any]:
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY.")

    endpoint = os.getenv(
        "ELEVENLABS_STT_URL",
        "https://api.elevenlabs.io/v1/speech-to-text",
    )
    model_id = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")

    headers = {
        "xi-api-key": api_key,
        "X-Request-Id": request_id,
    }

    files = {
        "file": (filename, audio_bytes, mime_type),
    }
    data = {
        "model_id": model_id,
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            endpoint,
            headers=headers,
            files=files,
            data=data,
        )
        response.raise_for_status()
        payload = response.json()

    text = str(payload.get("text") or payload.get("transcript") or "").strip()
    if not text:
        raise RuntimeError("Transcription response did not include text.")

    return {
        "text": text,
        "confidence": payload.get("confidence"),
        "duration_sec": payload.get("duration_seconds") or payload.get("duration"),
        "segments": payload.get("words") or payload.get("segments") or [],
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Transcribe an MP3 file to text")
    parser.add_argument("mp3_path")
    parser.add_argument("--request-id", default="local-cli")
    args = parser.parse_args()

    result = transcribe_mp3(mp3_path=args.mp3_path, request_id=args.request_id)
    print(json.dumps(result, indent=2))
