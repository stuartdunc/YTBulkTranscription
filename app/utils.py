from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Iterable


INVALID_FILENAME_CHARS = r'[<>:"/\\|?*\x00-\x1F]'
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(INVALID_FILENAME_CHARS, " ", value).strip().rstrip(".")
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    return cleaned or fallback


def slug_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value.replace("\n", " ")).strip()


def chunk_text(text: str, target_words: int = 1000, min_words: int = 800) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    words = normalized.split()
    if len(words) <= target_words:
        return [normalized]

    sentences = SENTENCE_SPLIT_RE.split(normalized)
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and current_words >= min_words and current_words + sentence_words > target_words:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_words = sentence_words
            continue
        current.append(sentence)
        current_words += sentence_words

    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def estimate_processing_seconds(duration_seconds: int | None, captions_first: bool = True) -> int:
    if not duration_seconds:
        return 45
    caption_seconds = max(20, math.ceil(duration_seconds * 0.08)) if captions_first else duration_seconds
    fallback_budget = max(60, math.ceil(duration_seconds * 0.6))
    return min(caption_seconds + fallback_budget // 4, duration_seconds + 120)


def ensure_within(parent: Path, child: Path) -> Path:
    resolved_parent = parent.resolve()
    resolved_child = child.resolve()
    if resolved_parent not in resolved_child.parents and resolved_parent != resolved_child:
        raise ValueError(f"Path '{resolved_child}' is outside '{resolved_parent}'")
    return resolved_child


def word_count(text: str) -> int:
    return len(normalize_text(text).split())


def pick_summary_sentences(text: str, max_sentences: int = 3) -> str:
    sentences = [segment.strip() for segment in SENTENCE_SPLIT_RE.split(normalize_text(text)) if segment.strip()]
    if not sentences:
        return "Summary unavailable."
    shortlist = sentences[:max_sentences]
    return " ".join(shortlist)


def flatten_tags(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for value in values:
        normalized = normalize_text(value).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tags.append(normalized)
    return tags
