from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_OUTPUT_ROOT_WINDOWS = r"G:\My Drive\Business Stuff\Youtube\Transcripts"


def _default_local_appdata() -> Path:
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata)
    return Path.home() / "AppData" / "Local"


@dataclass(slots=True)
class AppPaths:
    root: Path
    state_dir: Path
    temp_dir: Path
    db_path: Path
    logs_dir: Path
    default_output_root: Path

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.default_output_root.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class Settings:
    app_name: str
    app_paths: AppPaths
    transcript_retries: int = 3
    progress_poll_ms: int = 2500
    default_chunk_target_words: int = 1000
    fallback_model_size: str = "small.en"
    fallback_compute_type: str = "int8"


def _is_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    override_root = os.getenv("YTBT_APP_DATA_DIR")
    if override_root:
        app_root = Path(override_root)
    else:
        app_root = _default_local_appdata() / "YTBulkTranscription"

    # If the default location isn't writable (common in restricted sandboxes),
    # fall back to a repo-local folder so the app still runs.
    if not _is_dir_writable(app_root):
        repo_root = Path(__file__).resolve().parents[1]
        app_root = repo_root / "app_data"
        app_root.mkdir(parents=True, exist_ok=True)

    default_output_override = os.getenv("YTBT_DEFAULT_OUTPUT_ROOT")
    default_output_root = Path(default_output_override) if default_output_override else Path(DEFAULT_OUTPUT_ROOT_WINDOWS)
    try:
        default_output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        default_output_root = Path.home() / "Documents" / "YTBulkTranscription Output"
        default_output_root.mkdir(parents=True, exist_ok=True)

    app_paths = AppPaths(
        root=app_root,
        state_dir=app_root / "state",
        temp_dir=app_root / "temp",
        db_path=app_root / "state" / "ytbulktranscription.sqlite3",
        logs_dir=app_root / "logs",
        default_output_root=default_output_root,
    )
    app_paths.ensure()
    return Settings(
        app_name="YTBulkTranscription",
        app_paths=app_paths,
        transcript_retries=int(os.getenv("YTBT_TRANSCRIPT_RETRIES", "3")),
        progress_poll_ms=int(os.getenv("YTBT_PROGRESS_POLL_MS", "2500")),
        default_chunk_target_words=int(os.getenv("YTBT_CHUNK_TARGET_WORDS", "1000")),
        fallback_model_size=os.getenv("YTBT_FALLBACK_MODEL", "small.en"),
        fallback_compute_type=os.getenv("YTBT_FALLBACK_COMPUTE_TYPE", "int8"),
    )
