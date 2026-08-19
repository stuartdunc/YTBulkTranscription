from __future__ import annotations

import html
import re
from typing import Iterable

import requests
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi
from yt_dlp import YoutubeDL

from app.models import TranscriptResult, TranscriptSegment, VideoCandidate
from app.services.fallback_transcriber import FallbackTranscriber


class TranscriptService:
    def __init__(self, fallback_transcriber: FallbackTranscriber) -> None:
        self.fallback_transcriber = fallback_transcriber

    def collect(self, candidate: VideoCandidate, retries: int) -> TranscriptResult:
        last_error: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                return self._fetch_captions_youtube_transcript_api(candidate.video_id)
            except Exception as exc:
                last_error = exc

        ytdlp_error: Exception | None = None
        try:
            return self._fetch_captions_ytdlp(candidate.url)
        except Exception as exc:
            ytdlp_error = exc

        try:
            return self.fallback_transcriber.transcribe(candidate)
        except Exception as fallback_exc:
            message_parts: list[str] = []
            if last_error:
                message_parts.append(f"youtube-transcript-api failed: {last_error}")
            if ytdlp_error:
                message_parts.append(f"yt-dlp subtitles failed: {ytdlp_error}")
            message_parts.append(f"fallback failed: {fallback_exc}")
            raise RuntimeError("; ".join(message_parts)) from fallback_exc
            raise

    def _fetch_captions_youtube_transcript_api(self, video_id: str) -> TranscriptResult:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
        except NoTranscriptFound:
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
            except NoTranscriptFound as exc:
                raise RuntimeError("No English transcript available.") from exc

        raw_segments = transcript.fetch()
        segments = list(self._to_segments(raw_segments))
        text = " ".join(segment.text for segment in segments).strip()
        if not text:
            raise RuntimeError("Transcript text was empty.")
        source_type = "caption" if getattr(transcript, "is_generated", False) is False else "caption (auto-generated)"
        return TranscriptResult(source_type=source_type, text=text, segments=segments)

    def _fetch_captions_ytdlp(self, video_url: str) -> TranscriptResult:
        with YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
            }
        ) as ydl:
            info = ydl.extract_info(video_url, download=False)
        if not info:
            raise RuntimeError("yt-dlp could not extract video metadata.")

        subtitles = info.get("subtitles") or {}
        auto_captions = info.get("automatic_captions") or {}

        track, source_type = _pick_english_track(subtitles), "caption (yt-dlp subtitles)"
        if not track:
            track, source_type = _pick_english_track(auto_captions), "caption (yt-dlp auto captions)"
        if not track:
            raise RuntimeError("No English subtitle tracks found via yt-dlp.")

        content = _download_text(track["url"])
        segments = _parse_caption_payload(content, track.get("ext") or "")
        text = " ".join(segment.text for segment in segments).strip()
        if not text:
            raise RuntimeError("yt-dlp subtitle track was empty.")
        return TranscriptResult(source_type=source_type, text=text, segments=segments)

    @staticmethod
    def _to_segments(raw_segments: Iterable[dict]) -> Iterable[TranscriptSegment]:
        for segment in raw_segments:
            text = html.unescape(segment.get("text", "")).replace("\n", " ").strip()
            if not text:
                continue
            yield TranscriptSegment(
                text=text,
                start=float(segment["start"]) if "start" in segment else None,
                duration=float(segment["duration"]) if "duration" in segment else None,
            )


_VTT_TIMING_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+\s+-->\s+\d{2}:\d{2}:\d{2}\.\d+")
_VTT_TIMESTAMP_SHORT_RE = re.compile(r"^\d{1,2}:\d{2}\.\d+\s+-->\s+\d{1,2}:\d{2}\.\d+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _pick_english_track(tracks: dict) -> dict | None:
    if not tracks:
        return None
    preferred_langs = [key for key in ("en", "en-US", "en-GB") if key in tracks]
    if not preferred_langs:
        preferred_langs = sorted([key for key in tracks.keys() if str(key).lower().startswith("en")])
    if not preferred_langs:
        return None
    lang = preferred_langs[0]
    formats = tracks.get(lang) or []
    if not formats:
        return None
    preferred_exts = ("vtt", "srv1", "srv2", "srv3", "ttml", "json3")
    formats_sorted = sorted(
        formats,
        key=lambda item: preferred_exts.index(item.get("ext")) if item.get("ext") in preferred_exts else 999,
    )
    chosen = formats_sorted[0]
    if "url" not in chosen:
        return None
    return chosen


def _download_text(url: str) -> str:
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()
    return response.text


def _parse_caption_payload(payload: str, ext: str) -> list[TranscriptSegment]:
    ext = (ext or "").lower()
    if ext == "vtt":
        return _parse_vtt(payload)
    if ext.startswith("srv"):
        return _parse_youtube_srv(payload)
    return _parse_plain(payload)


def _strip_inline_markup(value: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", value)).replace("\n", " ").strip()


def _parse_vtt(payload: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for raw_line in payload.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        if _VTT_TIMING_RE.match(line) or _VTT_TIMESTAMP_SHORT_RE.match(line):
            continue
        if line.isdigit():
            continue
        text = _strip_inline_markup(line)
        if text:
            segments.append(TranscriptSegment(text=text))
    return segments


def _parse_youtube_srv(payload: str) -> list[TranscriptSegment]:
    # YouTube srv captions are XML with <text start=".." dur="..">..</text>
    try:
        from defusedxml import ElementTree as SafeET
    except Exception:
        import xml.etree.ElementTree as SafeET  # type: ignore[assignment]

    try:
        root = SafeET.fromstring(payload)
    except Exception as exc:
        raise RuntimeError(f"Unable to parse YouTube srv captions: {exc}") from exc

    segments: list[TranscriptSegment] = []
    for node in root.iter("text"):
        text = _strip_inline_markup(node.text or "")
        if not text:
            continue
        start = node.attrib.get("start")
        dur = node.attrib.get("dur")
        try:
            start_f = float(start) if start is not None else None
        except ValueError:
            start_f = None
        try:
            dur_f = float(dur) if dur is not None else None
        except ValueError:
            dur_f = None
        segments.append(TranscriptSegment(text=text, start=start_f, duration=dur_f))
    return segments


def _parse_plain(payload: str) -> list[TranscriptSegment]:
    text = _strip_inline_markup(payload)
    if not text:
        return []
    return [TranscriptSegment(text=text)]
