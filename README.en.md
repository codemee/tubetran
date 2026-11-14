**English** | [繁體中文](README.md)

# trantube

A local web app: paste a YouTube URL to play the video with bilingual subtitles (original + Traditional Chinese).

## How it works

1. Fetch subtitles with `yt-dlp` (manual captions first, then auto-generated).
2. If there are none: download the audio → transcribe locally with `faster-whisper`.
   (The Claude API does not accept audio input, so Whisper handles speech-to-text and Claude only translates.)
3. Translate in batches to Traditional Chinese (Taiwan usage) via the Claude API; misaligned batches are retried automatically.
4. The frontend plays the video with the YouTube IFrame Player; subtitles sync with playback, are click-to-seek, and can be exported as SRT / VTT.

Results are cached in `cache/<video_id>/`, so the same video is never downloaded or billed twice.

## Setup & run

```powershell
uv sync
Copy-Item .env.example .env   # then edit .env and set ANTHROPIC_API_KEY
uv run uvicorn app.main:app
```

Open http://localhost:8000 . `ffmpeg` must be installed (`scoop install ffmpeg`).

## Configuration (`.env`)

| Variable | Description | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key (required) | — |
| `TRANSLATE_MODEL` | Claude model used for translation | `claude-haiku-5-5` |
| `WHISPER_MODEL` | faster-whisper model size | `small` |
| `TRANSLATE_BATCH_SIZE` | Segments per translation batch | `50` |

faster-whisper uses the GPU automatically when CUDA is available; the model is downloaded on first use.

## Tests

```powershell
uv run pytest
```

## Notes

- YouTube changes often; if downloads fail, update with `uv lock --upgrade-package yt-dlp && uv sync`.
- For personal use only. Respect YouTube's Terms of Service and video copyright.
