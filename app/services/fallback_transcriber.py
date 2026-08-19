from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import mkdtemp

from yt_dlp import YoutubeDL

from app.config import Settings
from app.models import TranscriptResult, TranscriptSegment, VideoCandidate


class FallbackTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, candidate: VideoCandidate) -> TranscriptResult:
        audio_path = self._download_audio(candidate)
        try:
            segments = self._run_faster_whisper(audio_path)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            if not text:
                raise RuntimeError("Fallback transcription returned no text.")
            return TranscriptResult(source_type="speech-to-text fallback", text=text, segments=segments)
        finally:
            shutil.rmtree(audio_path.parent, ignore_errors=True)

    def _download_audio(self, candidate: VideoCandidate) -> Path:
        temp_dir = Path(mkdtemp(prefix="ytbt-audio-", dir=self.settings.app_paths.temp_dir))
        output_template = str(temp_dir / f"{candidate.video_id}.%(ext)s")
        with YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "160",
                    }
                ],
            }
        ) as ydl:
            ydl.download([candidate.url])
        matches = list(temp_dir.glob(f"{candidate.video_id}.*"))
        if not matches:
            raise RuntimeError("Audio download failed; ffmpeg may be missing.")
        return matches[0]

    def _run_faster_whisper(self, audio_path: Path) -> list[TranscriptSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Fallback transcription requires the optional faster-whisper dependency. "
                "Install it with: pip install \"faster-whisper>=1.1.0,<2.0\""
            ) from exc

        model = WhisperModel(
            self.settings.fallback_model_size,
            device="auto",
            compute_type=self.settings.fallback_compute_type,
        )
        segments, _ = model.transcribe(str(audio_path), language="en", vad_filter=True)
        return [
            TranscriptSegment(text=segment.text.strip(), start=float(segment.start), duration=float(segment.end - segment.start))
            for segment in segments
            if segment.text.strip()
        ]

