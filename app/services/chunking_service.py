"""
Transcript chunking for RAG indexing.

Why sentence-aware chunking with overlap instead of naive fixed-size
character slicing:
- Cutting mid-sentence produces chunks that read as garbled fragments, which
  both hurts embedding quality (the vector represents a broken thought) and
  makes retrieved context confusing to the LLM at answer time.
- Overlap between consecutive chunks means a fact stated right at a chunk
  boundary isn't lost to only one side of the split -- it appears whole in
  at least one chunk.
"""

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_transcript(text: str, *, max_chars: int = 1000, overlap_sentences: int = 2) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        if current_len + len(sentence) > max_chars and current:
            chunks.append(" ".join(current))
            # Carry the last N sentences into the next chunk so context
            # spanning a chunk boundary isn't lost to only one side.
            current = current[-overlap_sentences:] if overlap_sentences else []
            current_len = sum(len(s) for s in current)

        current.append(sentence)
        current_len += len(sentence)

    if current:
        chunks.append(" ".join(current))

    return chunks