"""Unit tests for sentence-aware transcript chunking."""

from app.services.chunking_service import chunk_transcript


def test_empty_text_returns_no_chunks():
    assert chunk_transcript("") == []


def test_short_text_returns_single_chunk():
    text = "This is one sentence. This is another."
    chunks = chunk_transcript(text, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_text_splits_into_multiple_chunks():
    sentences = [f"This is sentence number {i}." for i in range(1, 50)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, max_chars=200, overlap_sentences=2)
    assert len(chunks) > 1


def test_consecutive_chunks_overlap():
    sentences = [f"This is sentence number {i}." for i in range(1, 20)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, max_chars=150, overlap_sentences=2)

    assert len(chunks) > 1
    for i in range(len(chunks) - 1):
        last_sentence_of_current = chunks[i].split(". ")[-1]
        assert last_sentence_of_current.rstrip(".") in chunks[i + 1]


def test_no_sentence_is_lost_across_chunk_boundaries():
    sentences = [f"Sentence {i} content here." for i in range(1, 30)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, max_chars=150, overlap_sentences=1)
    combined = " ".join(chunks)
    for i in range(1, 30):
        assert f"Sentence {i} content here." in combined


def test_zero_overlap_still_covers_all_sentences():
    sentences = [f"Item {i}." for i in range(1, 20)]
    text = " ".join(sentences)
    chunks = chunk_transcript(text, max_chars=50, overlap_sentences=0)
    combined = " ".join(chunks)
    for i in range(1, 20):
        assert f"Item {i}." in combined