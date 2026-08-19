from __future__ import annotations

from app.utils import pick_summary_sentences


class SummaryService:
    def build(self, title: str, transcript_text: str) -> str:
        base_summary = pick_summary_sentences(transcript_text, max_sentences=3)
        if title and title.lower() not in base_summary.lower():
            return f"{title}. {base_summary}"
        return base_summary

