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
- Search and tags in the library: search titles (original and translated) and tags; add tags to any video (the "+ Tag" button on the item, press Enter to add), then click tags in the bar above the list to filter. Multiple tags can be selected (a video must have all of them), and filtering combines with search.
- Subtitle check: merges duplicates, fixes timing, and fills in blank translations (runs once automatically after translation, and can be re-run from the button next to each library item).
- Light and dark themes, and Traditional Chinese / English interface. Both are three-state buttons: auto (follow the system, the default) → manual choices.

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
| Start | `python -m tubetran` or `TubeTran.exe` | `python -m tubetran --server` or `TubeTran.exe --server` |
| UI | A standalone window (uses the system's WebView2) | No window; open http://127.0.0.1:8000/ in a browser |
| Port | Fixed `47321` (a random port if it is taken); local connections only | `8000` by default; change with `--host` and `--port` |
| Extra requirements | The `desktop` extra (pywebview); WebView2 on Windows | None |
| Quit | Close the window | `Ctrl+C` |

Both modes share the same backend and frontend. In desktop mode the backend is a thread inside the same process, so closing the window ends the process and leaves no orphaned processes behind.

> **Warning:** Server mode has no authentication. If you use `--host 0.0.0.0` to allow LAN access, anyone on the same network can use your Claude API key to run translations. Only do this on a network you trust.

## Setup & run

Requires [uv](https://docs.astral.sh/uv/). Python is limited to 3.12–3.13 (newer versions may lack prebuilt wheels for some dependencies). Developed and tested mainly on Windows 11.

### Install with `uv tool install` (recommended)

```powershell
uv tool install ".[desktop]"         # run in the project folder; drop [desktop] if you only need server mode
# or straight from GitHub: uv tool install "tubetran[desktop] @ git+https://github.com/codemee/tubetran.git"

tubetran --help                      # list all options
tubetran --server                    # server mode: http://127.0.0.1:8000/
tubetran                             # desktop mode (needs [desktop])
```

Before the first run, create a `.env` in the [data folder](#data-folder) and set `ANTHROPIC_API_KEY` (see `.env.example` for the contents); an environment variable of the same name also works. Upgrade with `uv tool upgrade tubetran` (if installed from a local folder, use `uv tool install --reinstall ".[desktop]"` after changing code); remove with `uv tool uninstall tubetran`.

### Run from source (development)

```powershell
uv sync --extra desktop              # needed for desktop mode; server mode only needs plain `uv sync`
Copy-Item .env.example .env          # then edit .env and set ANTHROPIC_API_KEY

uv run python -m tubetran                 # desktop mode
uv run python -m tubetran --server        # server mode: http://127.0.0.1:8000/
uv run python -m tubetran --server --host 0.0.0.0 --port 9000   # allow LAN access (read the warning above first)
uv run python -m tubetran --help          # list all options
```

You do not need to install `ffmpeg` beforehand (speech recognition uses the decoding libraries bundled with PyAV); if `yt-dlp` asks for it for a particular video, install it then (`scoop install ffmpeg`).

## Configuration

### Settings panel

The settings button at the top right (left of the language button) opens a panel where you can change:

- **Claude API key:** only the first and last two characters are shown, with `*` in between; the full key is never sent back to the browser. To replace it, just paste a new one. The program starts fine without a key and opens the panel automatically so you can enter one.
- **Translation model:** the options are the models this key can actually use, queried from Anthropic (a valid key is required).
- **Speech-to-text (STT) model:** the options are the models officially supported by faster-whisper (from its `available_models()`); only used when a video has no captions.

Pressing "Save" writes to the `.env` in the data folder and takes effect immediately for jobs started afterwards — no restart needed.

> **Priority:** operating-system environment variables **take priority over** `.env`. If `ANTHROPIC_API_KEY`, `TRANSLATE_MODEL` or `WHISPER_MODEL` is already set as an environment variable before startup, the panel locks that field and says where it comes from (changing it in the panel would have no effect). To change it, edit the environment variable, or remove it and then use the panel.

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

1. The `TUBETRAN_DATA_DIR` environment variable, if set
2. Development (running from the source folder): the project root
3. Otherwise (`uv tool install`, packaged app): the user data directory — `%LOCALAPPDATA%\TubeTran` on Windows, `~/Library/Application Support/TubeTran` on macOS, `$XDG_DATA_HOME/TubeTran` on Linux (`~/.local/share/TubeTran` if unset)

Contents:

| Item | Description |
| --- | --- |
| `.env` | Settings and the API key |
| `cache/<video_id>/` | Per-video cache: `subs.json` (raw subtitles), `translated.json` (final result), `trans_partial.json` (translation checkpoint, removed when finished), `progress.json` (playback position), `tags.json` (tags; up to 10, 20 characters each), `audio.*` (audio, when there were no captions), `translated.pre-check.json` (backup taken before a manual check) |
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
tubetran/
  cli.py            Command-line entry: desktop mode / --server
  config.py         Settings and the data folder
  main.py           FastAPI routes and static files
  jobs.py           Background jobs, cache, library, playback progress
  services/         subtitles, transcribe (Whisper), translate, review (check), export (SRT/VTT)
  static/           Frontend (no build step): index.html, app.js, i18n.js, style.css, logo/
packaging/          PyInstaller configuration and launcher (launch.py)
tests/              pytest
```

## Development & tests

```powershell
uv run uvicorn tubetran.main:app --reload --reload-dir tubetran   # development: reload on code changes
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
