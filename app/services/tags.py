from __future__ import annotations

from collections import Counter

from app.models import VideoCandidate
from app.utils import flatten_tags, normalize_text


STOPWORDS = {
    "the",
    "and",
    "that",
    "with",
    "this",
    "from",
    "have",
    "your",
    "about",
    "there",
    "what",
    "when",
    "would",
    "their",
    "which",
    "will",
    "they",
    "them",
    "into",
    "were",
    "been",
    "than",
    "then",
    "just",
    "also",
    "because",
}


class TagService:
    def build(self, candidate: VideoCandidate, transcript_text: str) -> list[str]:
        keyword_counter: Counter[str] = Counter()
        for token in normalize_text(transcript_text).lower().split():
            cleaned = "".join(ch for ch in token if ch.isalnum() or ch == "-")
            if len(cleaned) < 4 or cleaned in STOPWORDS:
                continue
            keyword_counter[cleaned] += 1

        top_keywords = [word for word, _ in keyword_counter.most_common(5)]
        year = candidate.publish_date[:4] if candidate.publish_date else None
        tags = flatten_tags(
            [
                candidate.channel_name or "",
                candidate.playlist_name or "",
                year or "",
                *top_keywords,
            ]
        )
        return tags[:8]

