from __future__ import annotations

import os
import threading
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.models import JobStatus
from app.services.discovery import DiscoveryService
from app.services.markdown_writer import MarkdownWriter
from app.services.summaries import SummaryService
from app.services.tags import TagService
from app.services.transcripts import TranscriptService


class JobManager:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        discovery_service: DiscoveryService,
        transcript_service: TranscriptService,
        summary_service: SummaryService,
        tag_service: TagService,
        markdown_writer: MarkdownWriter,
    ) -> None:
        self.database = database
        self.settings = settings
        self.discovery_service = discovery_service
        self.transcript_service = transcript_service
        self.summary_service = summary_service
        self.tag_service = tag_service
        self.markdown_writer = markdown_writer
        self._threads: dict[int, threading.Thread] = {}
        self._cancel_events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, job_id: int) -> None:
        with self._lock:
            existing = self._threads.get(job_id)
            if existing and existing.is_alive():
                return
            cancel_event = threading.Event()
            thread = threading.Thread(target=self._run_job, args=(job_id, cancel_event), daemon=True)
            self._cancel_events[job_id] = cancel_event
            self._threads[job_id] = thread
            thread.start()

    def cancel(self, job_id: int) -> None:
        event = self._cancel_events.get(job_id)
        if event:
            event.set()

    def open_output_folder(self, job_id: int) -> None:
        job = self.database.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        if hasattr(os, "startfile"):
            os.startfile(job["output_path"])  # type: ignore[attr-defined]

    def _run_job(self, job_id: int, cancel_event: threading.Event) -> None:
        options = self.database.get_options(job_id)
        output_root = Path(options.output_path).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        log_dir = output_root / "_job_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"job-{job_id}.log"
        self.database.mark_job_started(job_id, str(log_file))
        self.database.add_event(job_id, "info", "job", "Job started.")

        try:
            for row in self.database.get_processing_queue(job_id):
                if cancel_event.is_set():
                    self.database.add_event(job_id, "warning", "job", "Cancellation requested.")
                    self.database.complete_job(job_id, JobStatus.CANCELLED)
                    return

                self.database.set_current_video(job_id, row["video_id"], row["title"])
                self.database.mark_job_video_started(job_id, row["video_id"])
                self.database.add_event(job_id, "info", "video", f"Processing {row['title']}")

                try:
                    candidate = self.discovery_service.fetch_video_details(row["video_id"])
                    existing = self.database.get_video(candidate.video_id)
                    if (
                        not options.force_reprocess
                        and existing
                        and existing["processing_status"] == "completed"
                        and existing["content_hash"] == candidate.content_signature
                        and existing["transcript_file_path"]
                    ):
                        self.database.mark_job_video_skipped(job_id, candidate.video_id, "Already collected and unchanged.")
                        self.database.add_event(job_id, "info", "skip", f"Skipped unchanged video: {candidate.title}")
                        continue

                    self.database.upsert_video_stub(candidate)
                    transcript = self.transcript_service.collect(candidate, retries=options.transcript_retries)
                    summary = self.summary_service.build(candidate.title, transcript.text)
                    tags = self.tag_service.build(candidate, transcript.text)
                    prior_path = existing["transcript_file_path"] if existing else None
                    path, chunks = self.markdown_writer.write(
                        output_root,
                        candidate,
                        transcript,
                        summary,
                        tags,
                        existing_file_path=prior_path,
                    )
                    if prior_path and Path(prior_path).exists() and Path(prior_path).resolve() != path.resolve():
                        Path(prior_path).unlink()
                    self.database.replace_transcript_chunks(candidate.video_id, chunks)
                    self.database.upsert_channel(candidate.channel_id, candidate.channel_name, candidate.channel_url, str(path.parent))
                    self.database.mark_job_video_complete(
                        job_id,
                        candidate.video_id,
                        source_type=transcript.source_type,
                        transcript_file_path=str(path),
                        summary=summary,
                        tags=tags,
                        content_hash=candidate.content_signature,
                    )
                    self.database.add_event(job_id, "info", "write", f"Saved transcript to {path}")
                except Exception as exc:
                    message = str(exc)
                    self.database.mark_job_video_failed(job_id, row["video_id"], message)
                    self.database.add_event(job_id, "error", "video", f"{row['title']}: {message}")
                    _append_text(log_file, f"[{row['video_id']}] {row['title']} | {row['url']} | {message}")
                finally:
                    self.database.set_current_video(job_id, None, None)

            self.database.complete_job(job_id, JobStatus.COMPLETED)
            self.database.add_event(job_id, "info", "job", "Job completed.")
        except Exception as exc:
            self.database.add_event(job_id, "error", "job", f"Fatal job error: {exc}")
            _append_text(log_file, f"[job] Fatal error: {exc}")
            self.database.complete_job(job_id, JobStatus.FAILED)


def _append_text(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
