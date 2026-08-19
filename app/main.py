from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import Database
from app.job_manager import JobManager
from app.models import ProcessingOptions
from app.services.discovery import DiscoveryService
from app.services.fallback_transcriber import FallbackTranscriber
from app.services.markdown_writer import MarkdownWriter
from app.services.summaries import SummaryService
from app.services.tags import TagService
from app.services.transcripts import TranscriptService

settings = get_settings()
database = Database(settings.app_paths.db_path)
discovery_service = DiscoveryService(database)
transcript_service = TranscriptService(FallbackTranscriber(settings))
summary_service = SummaryService()
tag_service = TagService()
markdown_writer = MarkdownWriter(settings)
job_manager = JobManager(
    database=database,
    settings=settings,
    discovery_service=discovery_service,
    transcript_service=transcript_service,
    summary_service=summary_service,
    tag_service=tag_service,
    markdown_writer=markdown_writer,
)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def _parse_utc_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Stored values are UTC ISO without timezone.
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _format_duration(total_seconds: int | float | None) -> str:
    if total_seconds is None:
        return "n/a"
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _compute_timing(job: object, processed: int) -> dict[str, object]:
    # job is sqlite3.Row-like
    started_at = _parse_utc_iso(job["started_at"]) if job else None
    total_videos = int(job["total_videos"] or 0) if job else 0
    estimated_seconds = int(job["estimated_seconds"] or 0) if job else 0

    if not started_at:
        return {
            "elapsed_seconds": None,
            "remaining_seconds": None,
            "elapsed_display": "n/a",
            "remaining_display": "n/a",
            "eta_display": "n/a",
        }

    now = datetime.now(timezone.utc)
    elapsed_seconds = max(0, int((now - started_at).total_seconds()))

    remaining_seconds: int | None
    if processed > 0 and total_videos > 0:
        per_video = elapsed_seconds / max(1, processed)
        remaining_seconds = max(0, int(per_video * max(0, total_videos - processed)))
    else:
        remaining_seconds = max(0, estimated_seconds - elapsed_seconds) if estimated_seconds else None

    if remaining_seconds is not None:
        eta_display = (now + timedelta(seconds=remaining_seconds)).astimezone().strftime("%H:%M:%S")
    else:
        eta_display = "n/a"

    return {
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "elapsed_display": _format_duration(elapsed_seconds),
        "remaining_display": _format_duration(remaining_seconds) if remaining_seconds is not None else "n/a",
        "eta_display": eta_display,
    }


def render_template(name: str, request: Request, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "app_name": settings.app_name,
            "default_output_path": str(settings.app_paths.default_output_root),
            "poll_ms": settings.progress_poll_ms,
            **context,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    jobs = database.list_recent_jobs()
    return render_template("index.html", request, jobs=jobs)


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    input_url: str = Form(...),
    output_path: str = Form(...),
    skip_shorts: bool = Form(False),
    skip_livestreams: bool = Form(False),
    skip_members_only: bool = Form(False),
    force_reprocess: bool = Form(False),
) -> HTMLResponse:
    options = ProcessingOptions(
        output_path=str(Path(output_path).expanduser()),
        skip_shorts=skip_shorts,
        skip_livestreams=skip_livestreams,
        skip_members_only=skip_members_only,
        transcript_retries=settings.transcript_retries,
        force_reprocess=force_reprocess,
    )

    try:
        analysis = discovery_service.analyze(input_url.strip(), options)
        job_id = database.create_analyzed_job(analysis, options)
    except Exception as exc:
        return render_template("partials/analysis_panel.html", request, analysis=None, analysis_error=str(exc))

    return render_template("partials/analysis_panel.html", request, analysis=analysis, analysis_error=None, job_id=job_id)


@app.post("/jobs/{job_id}/start")
async def start_job(job_id: int) -> RedirectResponse:
    if not database.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job_manager.start(job_id)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int) -> RedirectResponse:
    if not database.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job_manager.cancel(job_id)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/open-output")
async def open_output(request: Request, job_id: int) -> Response:
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        output_path = Path(job["output_path"]).expanduser()
        output_path.mkdir(parents=True, exist_ok=True)
        job_manager.open_output_folder(job_id)
        database.add_event(job_id, "info", "ui", f"Opened output folder: {output_path}")
    except Exception as exc:
        database.add_event(job_id, "error", "ui", f"Open output folder failed: {exc}")
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int) -> HTMLResponse:
    payload = database.hydrate_analysis(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    job = payload["job"]
    videos = payload["videos"]
    processed = int(job["completed_videos"] + job["skipped_videos"] + job["failed_videos"])
    timing = _compute_timing(job, processed)
    return render_template("job_detail.html", request, job=job, videos=videos, events=payload["events"], timing=timing)


@app.get("/jobs/{job_id}/progress", response_class=HTMLResponse)
async def job_progress(request: Request, job_id: int) -> HTMLResponse:
    payload = database.hydrate_analysis(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    job = payload["job"]
    videos = payload["videos"]
    processed = int(job["completed_videos"] + job["skipped_videos"] + job["failed_videos"])
    timing = _compute_timing(job, processed)
    return render_template("partials/progress_panel.html", request, job=job, videos=videos, events=payload["events"], timing=timing)
