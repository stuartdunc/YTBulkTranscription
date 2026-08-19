from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from yt_dlp import YoutubeDL

from app.database import Database
from app.models import AnalysisResult, InputType, PlannedAction, ProcessingOptions, VideoCandidate
from app.utils import estimate_processing_seconds, slug_hash


def infer_input_type(url: str) -> InputType:
    parsed = urlparse(url)
    if "playlist" in parsed.path:
        return InputType.PLAYLIST
    if parsed.query:
        query = parse_qs(parsed.query)
        if "list" in query and "v" not in query:
            return InputType.PLAYLIST
    if any(token in parsed.path for token in ("/channel/", "/c/", "/@", "/user/")):
        return InputType.CHANNEL
    return InputType.VIDEO


class DiscoveryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _base_opts(flat: bool = False) -> dict[str, Any]:
        return {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True if flat else False,
            "ignoreerrors": True,
            "noplaylist": False,
        }

    def analyze(self, url: str, options: ProcessingOptions) -> AnalysisResult:
        requested_type = infer_input_type(url)
        if requested_type == InputType.VIDEO:
            candidate = self.fetch_video_details(url)
            candidate.planned_action, candidate.skip_reason = self._plan_candidate(candidate, options)
            existing = self.database.get_video(candidate.video_id)
            if not options.force_reprocess and self._is_unchanged(existing, candidate):
                candidate.planned_action = PlannedAction.SKIP_UNCHANGED
                candidate.skip_reason = "Already collected and unchanged."
            self.database.upsert_video_stub(candidate)
            return AnalysisResult(
                input_url=url,
                canonical_url=candidate.url,
                input_type=InputType.VIDEO,
                source_title=candidate.title,
                source_channel_name=candidate.channel_name,
                total_videos=1,
                videos_to_process=1 if candidate.planned_action == PlannedAction.PROCESS else 0,
                skipped_videos=0 if candidate.planned_action == PlannedAction.PROCESS else 1,
                estimated_seconds=estimate_processing_seconds(candidate.duration_seconds),
                videos=[candidate],
            )

        collection_url = self._normalize_collection_url(url, requested_type)
        info = self._extract_collection(collection_url)
        if requested_type == InputType.CHANNEL and self._looks_like_channel_tab_stub(info):
            fallback_url = self._channel_videos_tab_url(info.get("webpage_url") or collection_url)
            if fallback_url != collection_url:
                info = self._extract_collection(fallback_url)
        entries = info.get("entries") or []
        source_title = info.get("title") or info.get("channel") or "YouTube Collection"
        source_channel_name = info.get("channel") or info.get("uploader")
        candidates_by_id: dict[str, VideoCandidate] = {}

        for position, entry in enumerate(entries, start=1):
            if not entry:
                continue
            video_id = entry.get("id")
            if not video_id:
                continue
            candidate = VideoCandidate(
                video_id=video_id,
                title=entry.get("title") or f"Video {position}",
                url=entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                channel_id=entry.get("channel_id") or info.get("channel_id"),
                channel_name=entry.get("channel") or entry.get("uploader") or source_channel_name,
                channel_url=entry.get("channel_url"),
                playlist_id=info.get("id") if requested_type == InputType.PLAYLIST else None,
                playlist_name=info.get("title") if requested_type == InputType.PLAYLIST else None,
                publish_date=entry.get("upload_date"),
                duration_seconds=entry.get("duration"),
                is_short=(entry.get("duration") or 0) > 0 and (entry.get("duration") or 0) <= 60,
                is_livestream=bool(entry.get("live_status") in {"is_live", "was_live"}),
                is_members_only_or_unavailable=entry.get("availability") in {"subscriber_only", "needs_auth", "private"},
                position=position,
                content_signature=slug_hash(
                    {
                        "video_id": video_id,
                        "title": entry.get("title"),
                        "duration": entry.get("duration"),
                        "upload_date": entry.get("upload_date"),
                        "channel_id": entry.get("channel_id") or info.get("channel_id"),
                    }
                ),
            )
            planned_action, skip_reason = self._plan_candidate(candidate, options)
            existing = self.database.get_video(video_id)
            if planned_action == PlannedAction.PROCESS and (not options.force_reprocess) and self._is_unchanged(existing, candidate):
                planned_action = PlannedAction.SKIP_UNCHANGED
                skip_reason = "Already collected and unchanged."
            candidate.planned_action = planned_action
            candidate.skip_reason = skip_reason
            if video_id in candidates_by_id:
                candidates_by_id[video_id] = self._merge_duplicate_candidate(candidates_by_id[video_id], candidate)
                continue
            candidates_by_id[video_id] = candidate
            self.database.upsert_video_stub(candidate)

        candidates = list(candidates_by_id.values())
        estimated_seconds = sum(
            estimate_processing_seconds(candidate.duration_seconds)
            for candidate in candidates
            if candidate.planned_action == PlannedAction.PROCESS
        )
        videos_to_process = sum(1 for candidate in candidates if candidate.planned_action == PlannedAction.PROCESS)
        skipped_videos = len(candidates) - videos_to_process
        actual_input_type = InputType.PLAYLIST if info.get("_type") == "playlist" and requested_type != InputType.CHANNEL else requested_type

        return AnalysisResult(
            input_url=url,
            canonical_url=info.get("webpage_url") or url,
            input_type=actual_input_type,
            source_title=source_title,
            source_channel_name=source_channel_name,
            total_videos=len(candidates),
            videos_to_process=videos_to_process,
            skipped_videos=skipped_videos,
            estimated_seconds=estimated_seconds,
            videos=candidates,
        )

    def fetch_video_details(self, url_or_id: str) -> VideoCandidate:
        target = url_or_id if url_or_id.startswith("http") else f"https://www.youtube.com/watch?v={url_or_id}"
        with YoutubeDL(self._base_opts(flat=False)) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            raise RuntimeError(f"Unable to inspect {target}")

        duration = info.get("duration")
        return VideoCandidate(
            video_id=info["id"],
            title=info.get("title") or info["id"],
            url=info.get("webpage_url") or target,
            channel_id=info.get("channel_id"),
            channel_name=info.get("channel") or info.get("uploader"),
            channel_url=info.get("channel_url"),
            playlist_id=info.get("playlist_id"),
            playlist_name=info.get("playlist_title"),
            publish_date=info.get("upload_date"),
            duration_seconds=duration,
            is_short=bool(duration and duration <= 60),
            is_livestream=bool(info.get("live_status") in {"is_live", "was_live"}),
            is_members_only_or_unavailable=info.get("availability") in {"subscriber_only", "needs_auth", "private"},
            content_signature=slug_hash(
                {
                    "video_id": info["id"],
                    "title": info.get("title"),
                    "duration": duration,
                    "upload_date": info.get("upload_date"),
                    "channel_id": info.get("channel_id"),
                }
            ),
        )

    def _extract_collection(self, url: str) -> dict[str, Any]:
        with YoutubeDL(self._base_opts(flat=True)) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError(f"Unable to inspect {url}")
        return info

    @staticmethod
    def _normalize_collection_url(url: str, requested_type: InputType) -> str:
        if requested_type != InputType.CHANNEL:
            return url
        return DiscoveryService._channel_videos_tab_url(url)

    @staticmethod
    def _channel_videos_tab_url(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path.endswith("/videos"):
            return url
        if any(path.endswith(suffix) for suffix in ("/shorts", "/streams", "/featured")):
            return url
        new_path = f"{path}/videos" if path else "/videos"
        return urlunparse(parsed._replace(path=new_path))

    @staticmethod
    def _looks_like_channel_tab_stub(info: dict[str, Any]) -> bool:
        entries = info.get("entries") or []
        if len(entries) != 1:
            return False
        entry = entries[0] or {}
        entry_id = entry.get("id")
        if not entry_id:
            return False
        if entry.get("duration") is not None:
            return False
        title = (entry.get("title") or "").strip().lower()
        source_title = (info.get("title") or info.get("channel") or "").strip().lower()
        if source_title and title in {source_title, f"{source_title} - videos"}:
            return True
        return entry_id == info.get("channel_id")

    @staticmethod
    def _merge_duplicate_candidate(original: VideoCandidate, duplicate: VideoCandidate) -> VideoCandidate:
        original.title = original.title or duplicate.title
        original.url = original.url or duplicate.url
        original.channel_id = original.channel_id or duplicate.channel_id
        original.channel_name = original.channel_name or duplicate.channel_name
        original.channel_url = original.channel_url or duplicate.channel_url
        original.playlist_id = original.playlist_id or duplicate.playlist_id
        original.playlist_name = original.playlist_name or duplicate.playlist_name
        original.publish_date = original.publish_date or duplicate.publish_date
        original.duration_seconds = original.duration_seconds or duplicate.duration_seconds
        original.is_short = original.is_short or duplicate.is_short
        original.is_livestream = original.is_livestream or duplicate.is_livestream
        original.is_members_only_or_unavailable = (
            original.is_members_only_or_unavailable or duplicate.is_members_only_or_unavailable
        )
        if original.planned_action != PlannedAction.PROCESS and duplicate.planned_action == PlannedAction.PROCESS:
            original.planned_action = duplicate.planned_action
            original.skip_reason = duplicate.skip_reason
        if duplicate.position and (original.position <= 0 or duplicate.position < original.position):
            original.position = duplicate.position
        if not original.content_signature:
            original.content_signature = duplicate.content_signature
        return original

    @staticmethod
    def _plan_candidate(candidate: VideoCandidate, options: ProcessingOptions) -> tuple[PlannedAction, str | None]:
        if candidate.is_members_only_or_unavailable:
            return PlannedAction.SKIP_UNAVAILABLE, "Members-only, private, or unavailable."
        if options.skip_shorts and candidate.is_short:
            return PlannedAction.SKIP_FILTER, "Filtered out as a Short."
        if options.skip_livestreams and candidate.is_livestream:
            return PlannedAction.SKIP_FILTER, "Filtered out as a livestream."
        return PlannedAction.PROCESS, None

    @staticmethod
    def _is_unchanged(existing: Any, candidate: VideoCandidate) -> bool:
        return bool(
            existing
            and existing["processing_status"] == "completed"
            and existing["content_hash"] == candidate.content_signature
            and existing["transcript_file_path"]
        )
