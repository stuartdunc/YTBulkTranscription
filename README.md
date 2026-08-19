# YTBulkTranscription

Local FastAPI app for collecting transcripts from YouTube videos, playlists, and channels into Markdown files with SQLite indexing and resumable job tracking.

## What version 1 includes

- Single setup screen for a YouTube URL, output path, and content filters
- Analysis step before processing starts
- Sequential background job runner with progress polling
- `yt-dlp` discovery for videos, playlists, and channels
- Captions-first transcript collection through `youtube-transcript-api`
- Optional `faster-whisper` fallback for videos without captions
- SQLite tracking for jobs, videos, transcript chunks, and event logs
- Channel-folder Markdown output for later LLM ingestion

## Project layout

```text
app/
  main.py
  config.py
  database.py
  job_manager.py
  models.py
  utils.py
  services/
  static/
  templates/
tests/
```

## Requirements

- Python 3.10+
- `ffmpeg` on `PATH` if you want speech-to-text fallback downloads
- Windows is the primary target, but the code is otherwise standard Python

## Setup

```powershell
cd "C:\Users\stuar\Documents\Python Code\YTBulkTranscription"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell script activation is blocked or appears to hang, skip activation and use the venv Python directly:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

## One-click launch (recommended)

Double-click `run_webapp.cmd` to create the venv (first run), install dependencies (first run), open your browser, and start the server in that same window.
If port `8000` is busy, it automatically falls back to `8765`.

Optional speech-to-text fallback:

```powershell
pip install "faster-whisper>=1.1.0,<2.0"
```

## Run locally

```powershell
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

## Output behavior

- Default output root: `G:\My Drive\Business Stuff\Youtube\Transcripts`
- One folder per channel
- One Markdown file per video
- Per-job error logs in `<output>/_job_logs/`
- Local SQLite state in `%LOCALAPPDATA%\YTBulkTranscription\state\ytbulktranscription.sqlite3`
- Override app state location with `YTBT_APP_DATA_DIR` if you prefer (or if `%LOCALAPPDATA%` is not writable)
- Override default output root with `YTBT_DEFAULT_OUTPUT_ROOT`

## Notes on fallback transcription

- Version 1 prefers captions first for speed and reliability
- If captions are missing, the app retries, then attempts local speech-to-text
- Fallback is optional by design; without `faster-whisper`, captionless videos will fail with a clear error

## Current limitations

- Processing is sequential
- Channel discovery relies on `yt-dlp` response shape for public channel URLs
- Members-only and unavailable detection is best-effort from metadata
- Job resume is implemented through persisted status and unchanged-video skipping, but there is not yet a dedicated resume button because rerunning the same URL creates a new job that reuses the stored index
