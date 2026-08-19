from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class InputType(str, Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    ANALYZED = "analyzed"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class VideoStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlannedAction(str, Enum):
    PROCESS = "process"
    SKIP_FILTER = "skip_filter"
    SKIP_UNCHANGED = "skip_unchanged"
    SKIP_UNAVAILABLE = "skip_unavailable"


@dataclass(slots=True)
class ProcessingOptions:
    output_path: str
    skip_shorts: bool = True
    skip_livestreams: bool = True
    skip_members_only: bool = True
    transcript_retries: int = 3
    force_reprocess: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VideoCandidate:
    video_id: str
    title: str
    url: str
    channel_id: str | None = None
    channel_name: str | None = None
    channel_url: str | None = None
    playlist_id: str | None = None
    playlist_name: str | None = None
    publish_date: str | None = None
    duration_seconds: int | None = None
    is_short: bool = False
    is_livestream: bool = False
    is_members_only_or_unavailable: bool = False
    position: int = 0
    content_signature: str = ""
    planned_action: PlannedAction = PlannedAction.PROCESS
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["planned_action"] = self.planned_action.value
        return data


@dataclass(slots=True)
class AnalysisResult:
    input_url: str
    canonical_url: str
    input_type: InputType
    source_title: str
    source_channel_name: str | None
    total_videos: int
    videos_to_process: int
    skipped_videos: int
    estimated_seconds: int
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    videos: list[VideoCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_url": self.input_url,
            "canonical_url": self.canonical_url,
            "input_type": self.input_type.value,
            "source_title": self.source_title,
            "source_channel_name": self.source_channel_name,
            "total_videos": self.total_videos,
            "videos_to_process": self.videos_to_process,
            "skipped_videos": self.skipped_videos,
            "estimated_seconds": self.estimated_seconds,
            "created_at": self.created_at,
            "videos": [video.to_dict() for video in self.videos],
        }


@dataclass(slots=True)
class TranscriptSegment:
    text: str
    start: float | None = None
    duration: float | None = None


@dataclass(slots=True)
class TranscriptResult:
    source_type: str
    text: str
    segments: list[TranscriptSegment]
