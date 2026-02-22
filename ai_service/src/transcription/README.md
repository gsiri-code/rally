## transcription

MP3 transcription tool package.

Environment variables:
- `TRANSCRIPTION_API_KEY` (or `OPENAI_API_KEY`)
- `TRANSCRIPTION_API_URL` (optional, defaults to OpenAI `/audio/transcriptions`)
- `TRANSCRIPTION_MODEL` (optional, defaults to `gpt-4o-mini-transcribe`)

CLI usage:

```bash
transcription /path/to/audio.mp3 --request-id req_123
```
