**English** | [繁體中文](README.md)

# TubeTran (水管譯工)

Paste a YouTube URL to play the video with bilingual subtitles (original + Traditional Chinese).
One program, two ways to run it: a **desktop app** (just run it) or a **server** (add `--server`).

## Features

- Downloads YouTube captions first (manual captions preferred, then auto-generated); when there are none, downloads the audio and transcribes it locally with Whisper.
- Translates to Traditional Chinese (Taiwan usage) with the Claude API, including the video title.
- Subtitles are overlaid on the video and stay visible in fullscreen (press `F`); switch between bilingual / original / translation, and export SRT / VTT.
- Translated lines are usable while translation is still running; the rest continues in the background, with a clear progress bar.
- A library on the right lists translated, in-progress and interrupted videos; click to watch again, delete the cache if you like. The last playback position is remembered so you can pick up where you left off.
- Subtitle check: merges duplicates, fixes timing, and fills in blank translations (runs once automatically after translation, and can be re-run from the button next to each library item).
- Light (RX-78-2 Gundam) and dark (Evangelion Unit-01) themes, and Traditional Chinese / English interface. Both are three-state buttons: auto (follow the system, the default) → manual choices.

## How it works

1. Fetch captions with `yt-dlp` (manual captions first, then auto-generated).
2. If there are none: download the audio → transcribe locally with `faster-whisper`.
   (The Claude API does not accept audio input, so Whisper handles speech-to-text and Claude only translates.)
3. Translate in batches to Traditional Chinese with the Claude API; misaligned or blank results are retried automatically, and a checkpoint is saved after every batch so an interrupted run resumes where it stopped.
4. After translation, the subtitles are checked automatically and then saved to the cache.

Results are cached in `cache/<video_id>/` inside the data folder, so the same video is never downloaded or billed twice.

## Two modes

| | Desktop mode (default) | Server mode (`--server`) |
| --- | --- | --- |
| Start | `python -m app` or `TubeTran.exe` | `python -m app --server` or `TubeTran.exe --server` |
| UI | A standalone window (uses the system's WebView2) | No window; open http://127.0.0.1:8000/ in a browser |
| Port | Fixed `47321` (a random port if it is taken); local connections only | `8000` by default; change with `--host` and `--port` |
| Extra requirements | The `desktop` extra (pywebview); WebView2 on Windows | None |
| Quit | Close the window | `Ctrl+C` |

Both modes share the same backend and frontend. In desktop mode the backend is a thread inside the same process, so closing the window ends the process and leaves no orphaned processes behind.

> **Warning:** Server mode has no authentication. If you use `--host 0.0.0.0` to allow LAN access, anyone on the same network can use your Claude API key to run translations. Only do this on a network you trust.

## Setup & run

Requires [uv](https://docs.astral.sh/uv/). The project pins Python 3.12 (newer versions may lack prebuilt wheels for some dependencies). Developed and tested mainly on Windows 11.

```powershell
uv sync --extra desktop              # needed for desktop mode; server mode only needs plain `uv sync`
Copy-Item .env.example .env          # then edit .env and set ANTHROPIC_API_KEY

uv run python -m app                 # desktop mode
uv run python -m app --server        # server mode: http://127.0.0.1:8000/
uv run python -m app --server --host 0.0.0.0 --port 9000   # allow LAN access (read the warning above first)
uv run python -m app --help          # list all options
```

You do not need to install `ffmpeg` beforehand (speech recognition uses the decoding libraries bundled with PyAV); if `yt-dlp` asks for it for a particular video, install it then (`scoop install ffmpeg`).

## Configuration

### `.env`

| Variable | Description | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key (required) | — |
| `TRANSLATE_MODEL` | Claude model used for translation | `claude-haiku-5-5` |
| `WHISPER_MODEL` | faster-whisper model size | `small` |
| `TRANSLATE_BATCH_SIZE` | Segments per translation batch | `50` |

faster-whisper uses the GPU automatically when CUDA is available; the model is downloaded on first use, and its size depends on the model (from tens of MB to several GB).

### Data folder

`.env`, the cache and the desktop app's settings all live in the "data folder", located by (in order):

1. The `TRANTUBE_DATA_DIR` environment variable, if set
2. Packaged app: `%LOCALAPPDATA%\TubeTran`
3. Development (running from source): the project root

Contents:

| Item | Description |
| --- | --- |
| `.env` | Settings and the API key |
| `cache/<video_id>/` | Per-video cache: `subs.json` (raw subtitles), `translated.json` (final result), `trans_partial.json` (translation checkpoint, removed when finished), `progress.json` (playback position), `audio.*` (audio, when there were no captions), `translated.pre-check.json` (backup taken before a manual check) |
| `webview/` | The desktop app's browser data (theme and language settings, cookies); excluded by `.gitignore` |
| `tubetran.log` | Output log when there is no console (for example when launched by double-click) |

Clicking ✕ in the library deletes that video's whole `cache/<video_id>/` folder.

## Packaging (Windows)

```powershell
uv sync --extra desktop
uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
```

The result is `packaging/dist/TubeTran/TubeTran.exe` (a folder build; distribute the whole folder). Measured size with local Whisper included: about 266 MB as a folder, about 109 MB compressed, of which the speech-recognition libraries account for roughly 80%. `TubeTran.exe --selftest` checks that every dependency was bundled correctly.

The packaged program runs in desktop mode by default, and `--server` switches to server mode; when started from a terminal, its output is shown in that terminal.

## Project layout

```
app/
  cli.py            Command-line entry: desktop mode / --server
  config.py         Settings and the data folder
  main.py           FastAPI routes and static files
  jobs.py           Background jobs, cache, library, playback progress
  services/         subtitles, transcribe (Whisper), translate, review (check), export (SRT/VTT)
static/             Frontend (no build step): index.html, app.js, i18n.js, style.css, logo/
packaging/          PyInstaller configuration
tests/              pytest
tubetran.py         Launcher script used for packaging
```

## Development & tests

```powershell
uv run uvicorn app.main:app --reload --reload-dir app   # development: reload on code changes
uv run pytest
```

On Windows, when you stop a `--reload` server, end its child processes too (`taskkill /PID <pid> /T /F`); otherwise a stale process can keep holding the port, and your code changes appear not to take effect.

## Notes

- The interface language only affects on-screen text; subtitles and titles are always translated into Traditional Chinese.
- English sentences are often split into fragments, and Chinese word order differs, so a few fragments are not translated literally; the text still reads coherently when followed continuously.
- The no-captions flow (download audio → Whisper) has so far only been verified to the point that the libraries load; it has not yet been run end to end on a real video.
- Translation calls the Claude API and costs money; the cache avoids paying twice, but reprocessing or deleting the cache and watching again translates it again.
- YouTube changes often; if downloads fail, update with `uv lock --upgrade-package yt-dlp && uv sync`. `yt-dlp` may warn that no JavaScript runtime (`deno`) was found; this currently does not affect caption or audio downloads, and if downloads do fail you can install it (`scoop install deno`).
- For personal use only. Respect YouTube's Terms of Service and video copyright.
