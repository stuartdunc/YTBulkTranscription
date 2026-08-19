from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.models import AnalysisResult, JobStatus, PlannedAction, ProcessingOptions, VideoCandidate, VideoStatus


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            # Some environments can't create WAL sidecar files; fall back to a safer default.
            connection.execute("PRAGMA journal_mode=DELETE;")
        connection.execute("PRAGMA foreign_keys=ON;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    input_type TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_channel_name TEXT,
                    output_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    total_videos INTEGER NOT NULL DEFAULT 0,
                    planned_videos INTEGER NOT NULL DEFAULT 0,
                    completed_videos INTEGER NOT NULL DEFAULT 0,
                    skipped_videos INTEGER NOT NULL DEFAULT 0,
                    failed_videos INTEGER NOT NULL DEFAULT 0,
                    estimated_seconds INTEGER NOT NULL DEFAULT 0,
                    current_video_id TEXT,
                    current_video_title TEXT,
                    error_log_path TEXT,
                    settings_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    channel_url TEXT,
                    folder_path TEXT,
                    last_scanned_at TEXT
                );

                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    playlist_id TEXT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    publish_date TEXT,
                    duration_seconds INTEGER,
                    is_short INTEGER NOT NULL DEFAULT 0,
                    is_livestream INTEGER NOT NULL DEFAULT 0,
                    is_members_only_or_unavailable INTEGER NOT NULL DEFAULT 0,
                    summary TEXT,
                    tags_json TEXT,
                    source_type TEXT,
                    transcript_file_path TEXT,
                    content_hash TEXT,
                    last_checked_at TEXT,
                    last_processed_at TEXT,
                    processing_status TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS transcript_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_word_count INTEGER NOT NULL,
                    chunk_start_time REAL,
                    chunk_end_time REAL,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS job_videos (
                    job_id INTEGER NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    planned_action TEXT NOT NULL,
                    skip_reason TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    PRIMARY KEY(job_id, video_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                """
            )

    def create_analyzed_job(self, analysis: AnalysisResult, options: ProcessingOptions) -> int:
        with self._lock, self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    input_url, canonical_url, input_type, source_title, source_channel_name,
                    output_path, created_at, status, total_videos, planned_videos,
                    skipped_videos, estimated_seconds, settings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis.input_url,
                    analysis.canonical_url,
                    analysis.input_type.value,
                    analysis.source_title,
                    analysis.source_channel_name,
                    options.output_path,
                    analysis.created_at,
                    JobStatus.ANALYZED.value,
                    analysis.total_videos,
                    analysis.videos_to_process,
                    analysis.skipped_videos,
                    analysis.estimated_seconds,
                    json.dumps(options.to_dict()),
                ),
            )
            job_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO job_videos (
                    job_id, video_id, title, url, position, planned_action, skip_reason, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, video_id) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    position = MIN(job_videos.position, excluded.position),
                    planned_action = excluded.planned_action,
                    skip_reason = excluded.skip_reason,
                    status = excluded.status
                """,
                [
                    (
                        job_id,
                        video.video_id,
                        video.title,
                        video.url,
                        video.position,
                        video.planned_action.value,
                        video.skip_reason,
                        VideoStatus.PENDING.value
                        if video.planned_action == PlannedAction.PROCESS
                        else VideoStatus.SKIPPED.value,
                    )
                    for video in analysis.videos
                ],
            )
        self.add_event(job_id, "info", "analyze", f"Prepared analysis for {analysis.total_videos} video(s).")
        return job_id

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def list_recent_jobs(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def get_job_videos(self, job_id: int) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM job_videos
                WHERE job_id = ?
                ORDER BY position ASC, title ASC
                """,
                (job_id,),
            ).fetchall()

    def get_job_events(self, job_id: int, limit: int = 200) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()

    def mark_job_started(self, job_id: int, error_log_path: str) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?, error_log_path = ?
                WHERE id = ?
                """,
                (JobStatus.RUNNING.value, utc_now(), error_log_path, job_id),
            )

    def complete_job(self, job_id: int, status: JobStatus) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, current_video_id = NULL, current_video_title = NULL
                WHERE id = ?
                """,
                (status.value, utc_now(), job_id),
            )

    def set_current_video(self, job_id: int, video_id: str | None, title: str | None) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET current_video_id = ?, current_video_title = ?
                WHERE id = ?
                """,
                (video_id, title, job_id),
            )

    def add_event(self, job_id: int, level: str, stage: str, message: str) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO job_events (job_id, created_at, level, stage, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, utc_now(), level, stage, message),
            )

    def get_video(self, video_id: str) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()

    def upsert_channel(self, channel_id: str | None, channel_name: str | None, channel_url: str | None, folder_path: str | None) -> None:
        if not channel_id or not channel_name:
            return
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO channels (channel_id, channel_name, channel_url, folder_path, last_scanned_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    channel_name = excluded.channel_name,
                    channel_url = excluded.channel_url,
                    folder_path = excluded.folder_path,
                    last_scanned_at = excluded.last_scanned_at
                """,
                (channel_id, channel_name, channel_url, folder_path, utc_now()),
            )

    def upsert_video_stub(self, video: VideoCandidate) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO videos (
                    video_id, channel_id, playlist_id, title, url, publish_date, duration_seconds,
                    is_short, is_livestream, is_members_only_or_unavailable, content_hash, last_checked_at,
                    processing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    playlist_id = excluded.playlist_id,
                    title = excluded.title,
                    url = excluded.url,
                    publish_date = excluded.publish_date,
                    duration_seconds = excluded.duration_seconds,
                    is_short = excluded.is_short,
                    is_livestream = excluded.is_livestream,
                    is_members_only_or_unavailable = excluded.is_members_only_or_unavailable,
                    content_hash = excluded.content_hash,
                    last_checked_at = excluded.last_checked_at
                """,
                (
                    video.video_id,
                    video.channel_id,
                    video.playlist_id,
                    video.title,
                    video.url,
                    video.publish_date,
                    video.duration_seconds,
                    int(video.is_short),
                    int(video.is_livestream),
                    int(video.is_members_only_or_unavailable),
                    video.content_signature,
                    utc_now(),
                    VideoStatus.PENDING.value,
                ),
            )

    def mark_job_video_started(self, job_id: int, video_id: str) -> None:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE job_videos
                SET status = ?, started_at = ?
                WHERE job_id = ? AND video_id = ?
                """,
                (VideoStatus.PROCESSING.value, now, job_id, video_id),
            )
            conn.execute(
                """
                UPDATE videos
                SET processing_status = ?, last_checked_at = ?
                WHERE video_id = ?
                """,
                (VideoStatus.PROCESSING.value, now, video_id),
            )

    def mark_job_video_complete(
        self,
        job_id: int,
        video_id: str,
        *,
        source_type: str,
        transcript_file_path: str,
        summary: str,
        tags: list[str],
        content_hash: str,
    ) -> None:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE job_videos
                SET status = ?, completed_at = ?, error_message = NULL
                WHERE job_id = ? AND video_id = ?
                """,
                (VideoStatus.COMPLETED.value, now, job_id, video_id),
            )
            conn.execute(
                """
                UPDATE videos
                SET summary = ?, tags_json = ?, source_type = ?, transcript_file_path = ?,
                    content_hash = ?, last_checked_at = ?, last_processed_at = ?,
                    processing_status = ?, error_message = NULL
                WHERE video_id = ?
                """,
                (
                    summary,
                    json.dumps(tags),
                    source_type,
                    transcript_file_path,
                    content_hash,
                    now,
                    now,
                    VideoStatus.COMPLETED.value,
                    video_id,
                ),
            )
            conn.execute(
                """
                UPDATE jobs
                SET completed_videos = completed_videos + 1
                WHERE id = ?
                """,
                (job_id,),
            )

    def mark_job_video_skipped(self, job_id: int, video_id: str, reason: str) -> None:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE job_videos
                SET status = ?, completed_at = ?, error_message = ?
                WHERE job_id = ? AND video_id = ?
                """,
                (VideoStatus.SKIPPED.value, now, reason, job_id, video_id),
            )
            conn.execute(
                """
                UPDATE videos
                SET last_checked_at = ?, processing_status = ?, error_message = ?
                WHERE video_id = ?
                """,
                (now, VideoStatus.SKIPPED.value, reason, video_id),
            )
            conn.execute(
                """
                UPDATE jobs
                SET skipped_videos = skipped_videos + 1
                WHERE id = ?
                """,
                (job_id,),
            )

    def mark_job_video_failed(self, job_id: int, video_id: str, message: str) -> None:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE job_videos
                SET status = ?, completed_at = ?, error_message = ?
                WHERE job_id = ? AND video_id = ?
                """,
                (VideoStatus.FAILED.value, now, message, job_id, video_id),
            )
            conn.execute(
                """
                UPDATE videos
                SET last_checked_at = ?, processing_status = ?, error_message = ?
                WHERE video_id = ?
                """,
                (now, VideoStatus.FAILED.value, message, video_id),
            )
            conn.execute(
                """
                UPDATE jobs
                SET failed_videos = failed_videos + 1
                WHERE id = ?
                """,
                (job_id,),
            )

    def replace_transcript_chunks(self, video_id: str, chunks: list[dict[str, Any]]) -> None:
        with self._lock, self.connection() as conn:
            conn.execute("DELETE FROM transcript_chunks WHERE video_id = ?", (video_id,))
            conn.executemany(
                """
                INSERT INTO transcript_chunks (
                    video_id, chunk_index, chunk_text, chunk_word_count, chunk_start_time, chunk_end_time
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        video_id,
                        chunk["chunk_index"],
                        chunk["chunk_text"],
                        chunk["chunk_word_count"],
                        chunk.get("chunk_start_time"),
                        chunk.get("chunk_end_time"),
                    )
                    for chunk in chunks
                ],
            )

    def get_processing_queue(self, job_id: int) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM job_videos
                WHERE job_id = ? AND planned_action = ?
                  AND status IN (?, ?)
                ORDER BY position ASC, title ASC
                """,
                (
                    job_id,
                    PlannedAction.PROCESS.value,
                    VideoStatus.PENDING.value,
                    VideoStatus.FAILED.value,
                ),
            ).fetchall()

    def hydrate_analysis(self, job_id: int) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        return {
            "job": job,
            "videos": self.get_job_videos(job_id),
            "events": self.get_job_events(job_id),
        }

    def get_options(self, job_id: int) -> ProcessingOptions:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        payload = json.loads(job["settings_json"])
        payload.setdefault("force_reprocess", False)
        return ProcessingOptions(**payload)
