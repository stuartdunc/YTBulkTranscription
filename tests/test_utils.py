from app.utils import chunk_text, sanitize_filename


def test_sanitize_filename_removes_windows_invalid_characters() -> None:
    assert sanitize_filename('Bad:/Name*?"') == "Bad Name"


def test_chunk_text_keeps_short_text_whole() -> None:
    text = "This is a short transcript. It should stay in one chunk."
    assert chunk_text(text, target_words=20) == [text]


def test_chunk_text_splits_longer_text() -> None:
    sentence = "This sentence contains enough words to build a transcript chunk for testing. "
    text = sentence * 120
    chunks = chunk_text(text, target_words=80, min_words=40)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
