# Developer Project Brief

## Project name
YouTube Transcript Collector

## Project repository and working directory
- GitHub repository: `https://github.com/stuartdunc/YTBulkTranscription`
- Local working directory: `C:\Users\stuar\Documents\Python Code\YTBulkTranscription`
- Default branch: `main`
- Codex should treat this repository as the source of truth for the build
- All scaffolding, project structure, README updates, requirements files, and implementation work should be created inside this repository

## Repository-aware implementation notes
- Set up the app as a Python project rooted at the repository root
- Keep the codebase structured for later packaging into a Windows `.exe`
- Add a clear `README.md` with setup, local run steps, and output folder behavior
- Add a `.gitignore` suitable for Python, local databases, logs, model files, caches, and environment files
- Keep local output data outside the repo by default, unless the user chooses a repo-local output path
- Keep large transient audio files and download artifacts out of Git
- Store job state, SQLite database, and logs in predictable app data locations or user-selected output paths
- Keep configuration simple for version 1, ideally via one small config file plus environment variables only where needed

## Project purpose
Build a private local web app for Windows that accepts a YouTube video URL, playlist URL, or channel URL, then collects transcripts and saves them as clean Markdown files for later LLM ingestion.

## Primary goal
Create a simple, stable tool for building a private knowledge base from YouTube content.

## Success criteria
- Easy to use
- Runs smoothly on Windows as a local web app
- Produces clear, well-structured Markdown transcript files
- Suitable for later ingestion into a Supabase SQL and vector database pipeline
- Handles single videos, playlists, and full channels
- Resumes interrupted jobs
- Skips unsupported content cleanly and logs failures

## Target user
Single private user only. No accounts, no multi-user support, no cloud storage.

## Core scope

### Input types
- Single YouTube video URL
- YouTube playlist URL
- YouTube channel URL

### Processing behavior
- Detect input type automatically from one input field
- For a video: process that video only
- For a playlist: process every accessible video in the playlist
- For a channel: process every accessible video on the channel
- On re-run, process new or updated videos only
- Overwrite old transcript files when a video has changed

### Transcript extraction priority
1. Use YouTube captions first
2. If captions are missing or unusable, retry automatically
3. If retries fail, fall back to local speech-to-text
4. If fallback fails, skip the video and log the error

### Language scope
- English only
- No translation required

### Content filters on first screen
Add tick box filters for:
- Skip Shorts
- Skip livestreams
- Skip members-only or unavailable videos

## User interface

### Screen 1: Setup
Fields and controls:
- Single input box for URL
- Output folder path input
- Tick boxes for filters
- Start button

### Screen 2: Analysis and confirmation
Show:
- Detected input type: video, playlist, or channel
- Channel or playlist name where available
- Number of videos found
- Number of videos to process
- Number of videos skipped
- Rough estimated time based on video duration and extraction method assumptions
- Go button

### Screen 3: Progress
Show:
- Progress bar
- Current video title
- Completed count
- Remaining count
- Running estimated time remaining
- List of completed videos
- List of skipped videos
- Cancel or stop control

### Screen 4: Completion
Show:
- Job summary
- Error log view
- Open output folder button
- Path to saved index and logs

## Output requirements

### Folder structure
- One folder per channel
- One Markdown file per video
- Channel folder name should be based on the channel name and sanitized for Windows file paths

### Video file naming
- Video Title - YYYY-MM-DD.md
- Sanitize invalid filename characters
- If filename collision occurs, append video ID

### Markdown file contents
Each video must be saved as a separate Markdown file.
No special heading level requirement is needed beyond clean readable structure.

Recommended structure inside each file:

```md
Title: [video title]
Channel: [channel name]
URL: [video URL]
Publish Date: [YYYY-MM-DD]
Video ID: [video id]
Source Type: [caption or speech-to-text fallback]
Date Collected: [timestamp]
Duration: [if available]
Summary: [short summary]
Tags: [comma-separated tags]

Transcript:
[chunked transcript text]
```

### Transcript chunking
- Chunk transcript when appropriate
- Preferred chunk size: about 800 to 1200 words
- Keep chunks contiguous and ordered
- Do not over-fragment short videos
- Preserve timestamps only if easily available from the source without hurting simplicity
- If timestamps are included, keep them lightweight and readable

### Summary generation
- Add a short summary at the top of each Markdown file
- Summary should be concise and useful for later retrieval
- No paid APIs
- Prefer a lightweight local summarisation approach or rule-based extractive summary for version 1
- Keep this modular so a better summary method can be swapped in later

### Tagging strategy
Chosen approach for version 1:
- Use lightweight automatic tags only
- Include channel name, year, playlist name where relevant, and simple keyword-based topic tags
- Do not require a separate heavy local LLM for tagging in version 1
- Design tagging so AI-generated tags can be added later without changing the core schema

## Indexing and database requirements

### Local app database
Use a local SQLite database for indexing and job state.

Store:
- Video metadata
- File path
- Source URL
- Channel ID and channel name
- Playlist ID where relevant
- Publish date
- Last checked date
- Last processed date
- Processing status
- Error status and error message
- Transcript summary
- Transcript chunk records
- Chunk order
- Chunk text
- Tags
- Content hash or signature for change detection

### Reason for this choice
This gives a clean local index now and maps well to later migration into Supabase SQL and a vector database pipeline.

### Future compatibility
Design the local schema so it is easy to move to:
- Supabase Postgres tables for metadata and chunks
- pgvector or another vector store for embeddings

## Job behavior and resilience

### Resume support
- If a run stops halfway, the next run should resume from where it left off
- Completed unchanged videos should be skipped
- Failed videos should be retryable

### Change detection
- Re-runs should process new or updated videos only
- Compare by video ID plus metadata and transcript freshness signals
- Where possible, track updated captions or content hash
- Safe fallback: if uncertain, reprocess and overwrite that one video

### Retry behavior
- Retry transcript extraction automatically before fallback
- Retry count should be configurable, default 2 or 3
- Log each failure reason clearly

### Error logging
- Show errors in-app
- Save an error log file in the output folder for each job
- Include timestamp, video title, URL, stage failed, and error reason

## Scale requirement
- Must support channels up to 1000 videos
- Simple and stable matters more than raw speed
- Process sequentially by default
- Concurrency should be optional and conservative if added later

## Technical recommendation

### Recommended stack
- Python backend
- FastAPI for local web app server
- Simple HTML, HTMX, and minimal JavaScript frontend or equivalent lightweight frontend
- yt-dlp for video, channel, and playlist discovery plus metadata collection
- YouTube Transcript API or yt-dlp subtitle extraction for captions-first path
- Local speech-to-text fallback using a lightweight English model
- SQLite for local index and job tracking
- File-based Markdown output

### Speech-to-text fallback recommendation
Keep package weight low.
Recommended version 1 choice:
- Use a lightweight local English model only
- Prefer a model and runtime approach kept below roughly 300 MB for the fallback component
- Make the speech-to-text model optional to install on first use if needed
- Captions-first should remain the default path to reduce processing time and size

Suggested implementation path:
- Version 1 default fallback: whisper.cpp or faster-whisper with a small English-only model chosen to stay within the size goal
- Keep fallback modular so model choice can be swapped later

## Non-functional requirements
- Local only
- Stable on Windows
- Clear progress feedback
- Clean file naming
- Clean Markdown output
- Low setup complexity
- No paid APIs
- Suitable for private knowledge base building

## Out of scope for version 1
- Multi-user support
- Cloud sync
- In-app search
- Translation
- Browser extension
- Automatic embeddings generation
- Supabase sync inside the first version
- Full desktop packaging in version 1

## Security and privacy requirements
- All processing should run locally where possible
- No external paid API calls
- Do not store credentials unless later needed for private video access
- Assume public or accessible videos only in version 1

## Suggested local data model

### Tables or equivalent structures

#### jobs
- id
- input_url
- input_type
- output_path
- created_at
- started_at
- completed_at
- status
- total_videos
- completed_videos
- skipped_videos
- failed_videos
- settings_json

#### channels
- channel_id
- channel_name
- channel_url
- folder_path
- last_scanned_at

#### videos
- video_id
- channel_id
- playlist_id nullable
- title
- url
- publish_date
- duration_seconds
- is_short
- is_livestream
- is_members_only_or_unavailable
- summary
- tags_json
- source_type
- transcript_file_path
- content_hash
- last_checked_at
- last_processed_at
- processing_status
- error_message

#### transcript_chunks
- id
- video_id
- chunk_index
- chunk_text
- chunk_word_count
- chunk_start_time nullable
- chunk_end_time nullable

## Acceptance criteria
- User can paste a video, playlist, or channel URL into one input field
- App correctly detects the input type
- App shows an analysis screen before processing starts
- App processes all accessible videos for playlists and channels
- App applies selected filters before processing
- App prefers captions first
- App falls back to local speech-to-text when needed
- App saves one Markdown file per video inside one folder per channel
- App writes clean metadata, summary, tags, and transcript text to each file
- App logs failures both in the UI and to a file
- App resumes interrupted jobs
- App skips unchanged videos on re-run and processes new or updated videos only
- App maintains a local SQLite index suitable for later migration to Supabase and a vector database pipeline

## Implementation guidance for developer
Build version 1 for reliability first.
Keep the architecture modular.
Separate these components:
- URL detection and source discovery
- Video metadata collection
- Caption extraction
- Audio transcription fallback
- Summary and tag generation
- Markdown writer
- SQLite indexer
- Job manager and resume logic
- UI state and progress reporting

## Preferred version 1 priorities
1. Reliable URL detection and video discovery
2. Clean Markdown output
3. Stable captions-first extraction
4. Resume and re-run logic
5. Local indexing for later vector pipeline use
6. Lightweight fallback transcription
7. Summary and tags

## Version 1 recommended defaults
- Sequential processing
- Rough time estimates only
- Lightweight summary generation
- Lightweight tags
- Conservative retries
- Local SQLite index

## Future version 2 ideas
- Export to Supabase schema directly
- Embedding generation pipeline
- Better summarisation and topic tagging
- Packaged Windows executable
- Optional private video access through authenticated cookies or user-supplied credentials
- In-app transcript preview
- Search across saved transcripts

## Final product statement
Build a Windows local web app in Python that accepts a YouTube video, playlist, or channel URL, processes all eligible videos, extracts transcripts using captions first and local speech-to-text fallback second, saves one clean Markdown file per video inside one folder per channel, maintains a local SQLite index of metadata and transcript chunks, resumes interrupted jobs, reprocesses only new or updated videos, and produces output suitable for later ingestion into a Supabase SQL plus vector database pipeline.
## Open-source project review and leverage plan

### Overall recommendation
Do not adopt any of the reviewed repositories as the base application.

Build a clean local web app around your own architecture, then borrow selected ideas:

- Use a captions-first strategy inspired by lightweight caption-focused projects
- Use robust URL discovery and metadata extraction through `yt-dlp`
- Keep speech-to-text fallback modular and lightweight
- Keep the UI, indexing, resume logic, and Markdown output custom to this project

### Project-by-project assessment

#### 1. ArthurFDLR/whisper-youtube
Use as:
- A reference for Whisper parameter exploration
- A reference for testing fallback transcription quality during development

Do not use as:
- The base of the app
- The main processing pipeline

Why:
- It is a Colab-style notebook workflow, not an application structure
- It is focused on transcribing a single video
- It is oriented around GPU-backed notebook execution and optional Google Drive storage

Recommendation:
- Useful as a development reference only
- Do not base production code on it

#### 2. Dicklesworthstone/bulk_transcribe_youtube_videos_from_playlist
Use as:
- A reference for bulk-processing flow
- A reference for progress handling
- A reference for merging transcript segments into cleaner sentence-level text
- A reference for optional metadata capture such as time ranges and confidence-like scores

Do not use as-is for:
- Downloader choice
- Dependency stack
- Core architecture

Why:
- It handles single videos and playlists well and includes useful transcript post-processing ideas
- But it uses `pytube`, SpaCy, CUDA-oriented logic, and a heavier script-first architecture than needed for version 1

Recommendation:
- Borrow the workflow ideas
- Replace `pytube` with `yt-dlp`
- Do not include SpaCy in version 1
- Do not include the OpenAI transcription path
- Keep the good ideas around transcript cleanup, metadata, and batch job flow

Specific bits worth borrowing conceptually:
- Per-video progress and job orchestration
- Segment-merging into readable transcript text
- Lightweight sentence splitting with a regex fallback
- Optional transcript metadata tables for later vector and chunk pipelines

#### 3. hathix/youtube-transcriber
Use as:
- The conceptual basis for captions-first extraction
- A reference for parsing YouTube caption XML into clean plain text

Do not use as:
- The app foundation
- The production code path without modernization

Why:
- It is very small and simple, which is useful
- It proves the value of using YouTube’s own captions first
- But it is an older, minimal script and not a scalable app architecture

Recommendation:
- Keep the captions-first principle
- Re-implement the caption retrieval path in modern Python
- Keep parsing logic simple and robust
- Use this approach before any speech-to-text fallback

#### 4. Doriandarko/Insanely-Fast-Transcription
Use as:
- A reference for optional future acceleration modes
- A reference for a `yt-dlp` based audio download path
- A reference for keeping the transcription backend swappable

Do not use as:
- The default fallback engine for version 1

Why:
- It is built around GPU acceleration, `insanely-fast-whisper`, and `openai/whisper-large-v3`
- That is not the best fit for a Windows-first, simple, low-weight private app
- Your version 1 requirement is stability and reasonable size, not maximum GPU throughput

Recommendation:
- Do not make this the default fallback path
- Consider this only as an optional future “fast mode” for users with suitable hardware
- Keep version 1 on a smaller, lighter local fallback model

### Final build recommendation based on the review

#### Use these ideas
- Captions-first extraction
- `yt-dlp` for input discovery, metadata, and audio download when needed
- Clean transcript post-processing after fallback transcription
- Chunk-aware transcript storage for later SQL and vector ingestion
- Job progress, resume support, and per-video logging

#### Avoid these for version 1
- Colab or notebook-first structure
- `pytube` as the main downloader
- SpaCy as a required dependency
- GPU-only or large-model-first transcription design
- Paid API transcription options

#### Recommended implementation choice for Codex
Core stack for version 1:
- FastAPI local web app
- `yt-dlp` for video, playlist, and channel handling
- Captions-first extraction path
- Lightweight local fallback transcription using `whisper.cpp` or `faster-whisper` with a small English model
- SQLite for indexing, resume state, and chunk records
- Markdown output writer designed for later Supabase plus vector DB ingestion

#### Optional future enhancements
- Add a high-speed GPU mode later
- Add richer sentence segmentation later
- Add better summary and tags later
- Add direct export into Supabase tables later

## Additional instruction for Codex
Build directly in the existing repository at `C:\Users\stuar\Documents\Python Code\YTBulkTranscription` and keep commits small and logical. Start by creating the project skeleton, dependency file, README, `.gitignore`, backend app structure, frontend templates, service modules, and local persistence layer before implementing extraction and transcription flows.
