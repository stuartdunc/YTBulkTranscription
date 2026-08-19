from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.models import TranscriptResult, VideoCandidate
from app.utils import chunk_text, sanitize_filename, word_count


class MarkdownWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write(
        self,
        output_root: Path,
        candidate: VideoCandidate,
        transcript: TranscriptResult,
        summary: str,
        tags: list[str],
        existing_file_path: str | None = None,
    ) -> tuple[Path, list[dict]]:
        channel_folder = output_root / sanitize_filename(candidate.channel_name or "Unknown Channel")
        channel_folder.mkdir(parents=True, exist_ok=True)

        publish_date = self._format_date(candidate.publish_date)
        file_name = sanitize_filename(f"{candidate.title} - {publish_date}")
        target_path = channel_folder / f"{file_name}.md"
        existing_path = Path(existing_file_path) if existing_file_path else None
        if existing_path and existing_path.exists() and existing_path.resolve() == target_path.resolve():
            existing_path.unlink()
        if target_path.exists():
            target_path = channel_folder / f"{file_name} - {candidate.video_id}.md"

        chunks = chunk_text(transcript.text, target_words=self.settings.default_chunk_target_words)
        chunk_rows = [
            {
                "chunk_index": index,
                "chunk_text": chunk,
                "chunk_word_count": word_count(chunk),
                "chunk_start_time": None,
                "chunk_end_time": None,
            }
            for index, chunk in enumerate(chunks, start=1)
        ]

        lines = [
            f"Title: {candidate.title}",
            f"Channel: {candidate.channel_name or 'Unknown Channel'}",
            f"URL: {candidate.url}",
            f"Publish Date: {publish_date}",
            f"Video ID: {candidate.video_id}",
            f"Source Type: {transcript.source_type}",
            f"Date Collected: {datetime.utcnow().replace(microsecond=0).isoformat()}",
            f"Duration: {candidate.duration_seconds or 'Unknown'}",
            f"Summary: {summary}",
            f"Tags: {', '.join(tags)}",
            "",
            "Transcript:",
            "",
        ]

        if len(chunk_rows) <= 1:
            lines.append(transcript.text.strip())
        else:
            for chunk in chunk_rows:
                lines.extend(
                    [
                        f"## Chunk {chunk['chunk_index']}",
                        "",
                        chunk["chunk_text"],
                        "",
                    ]
                )

        target_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return target_path, chunk_rows

    @staticmethod
    def _format_date(raw_date: str | None) -> str:
        if not raw_date:
            return "unknown-date"
        if len(raw_date) == 8 and raw_date.isdigit():
            return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        return raw_date
