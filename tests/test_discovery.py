from pathlib import Path

from app.database import Database
from app.models import InputType, ProcessingOptions
from app.services.discovery import DiscoveryService


def test_channel_root_url_is_normalized_to_videos_tab() -> None:
    normalized = DiscoveryService._normalize_collection_url(
        "https://www.youtube.com/@Michael-Girdley",
        InputType.CHANNEL,
    )
    assert normalized == "https://www.youtube.com/@Michael-Girdley/videos"


def test_channel_videos_url_is_left_unchanged() -> None:
    normalized = DiscoveryService._normalize_collection_url(
        "https://www.youtube.com/@Michael-Girdley/videos",
        InputType.CHANNEL,
    )
    assert normalized == "https://www.youtube.com/@Michael-Girdley/videos"


def test_channel_tab_stub_triggers_fallback_extract(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    service = DiscoveryService(database)
    requested_urls: list[str] = []

    def fake_extract(url: str) -> dict[str, object]:
        requested_urls.append(url)
        if url.endswith("/videos"):
            return {
                "_type": "playlist",
                "title": "Michael Girdley - Videos",
                "channel": "Michael Girdley",
                "channel_id": "UC-mfn4ibOC5ewLcpmgl0C4g",
                "webpage_url": url,
                "entries": [
                    {
                        "id": "video-1",
                        "title": "One",
                        "url": "https://www.youtube.com/watch?v=video-1",
                        "duration": 120,
                    },
                    {
                        "id": "video-2",
                        "title": "Two",
                        "url": "https://www.youtube.com/watch?v=video-2",
                        "duration": 180,
                    },
                ],
            }
        return {
            "_type": "playlist",
            "title": "Michael Girdley",
            "channel": "Michael Girdley",
            "channel_id": "UC-mfn4ibOC5ewLcpmgl0C4g",
            "webpage_url": url,
            "entries": [
                {
                    "id": "UC-mfn4ibOC5ewLcpmgl0C4g",
                    "title": "Michael Girdley - Videos",
                }
            ],
        }

    service._extract_collection = fake_extract  # type: ignore[method-assign]

    analysis = service.analyze(
        "https://www.youtube.com/@Michael-Girdley",
        ProcessingOptions(output_path=str(tmp_path / "output")),
    )

    assert requested_urls == ["https://www.youtube.com/@Michael-Girdley/videos"]
    assert analysis.total_videos == 2
    assert [video.video_id for video in analysis.videos] == ["video-1", "video-2"]


def test_channel_analysis_dedupes_duplicate_video_entries(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    service = DiscoveryService(database)
    service._extract_collection = lambda _url: {  # type: ignore[method-assign]
        "_type": "playlist",
        "title": "Example Channel",
        "channel": "Example Channel",
        "channel_id": "channel-1",
        "entries": [
            {
                "id": "video-1",
                "title": "First copy",
                "url": "https://www.youtube.com/watch?v=video-1",
                "duration": 120,
                "upload_date": "20260101",
            },
            {
                "id": "video-1",
                "title": "Second copy",
                "url": "https://www.youtube.com/watch?v=video-1",
                "duration": 120,
                "upload_date": "20260101",
            },
            {
                "id": "video-2",
                "title": "Unique video",
                "url": "https://www.youtube.com/watch?v=video-2",
                "duration": 180,
                "upload_date": "20260102",
            },
        ],
    }

    analysis = service.analyze(
        "https://www.youtube.com/@example",
        ProcessingOptions(output_path=str(tmp_path / "output")),
    )

    assert analysis.input_type == InputType.CHANNEL
    assert analysis.total_videos == 2
    assert analysis.videos_to_process == 2
    assert [video.video_id for video in analysis.videos] == ["video-1", "video-2"]


def test_create_analyzed_job_ignores_duplicate_job_videos(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    service = DiscoveryService(database)
    service._extract_collection = lambda _url: {  # type: ignore[method-assign]
        "_type": "playlist",
        "title": "Example Channel",
        "channel": "Example Channel",
        "channel_id": "channel-1",
        "entries": [
            {"id": "video-1", "title": "First", "url": "https://www.youtube.com/watch?v=video-1", "duration": 120},
            {"id": "video-1", "title": "First duplicate", "url": "https://www.youtube.com/watch?v=video-1", "duration": 120},
        ],
    }
    options = ProcessingOptions(output_path=str(tmp_path / "output"))

    analysis = service.analyze("https://www.youtube.com/@example", options)
    job_id = database.create_analyzed_job(analysis, options)

    rows = database.get_job_videos(job_id)
    assert len(rows) == 1
    assert rows[0]["video_id"] == "video-1"
