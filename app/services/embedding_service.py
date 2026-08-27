"""
Embedding service wrapping fastembed for turning transcript chunks (and
user questions) into vectors for Qdrant.

Why fastembed instead of an API-based embedding model (OpenAI, Cohere, etc.):
- Runs locally via ONNX Runtime -- no GPU, no PyTorch dependency, small
  image footprint. No per-call cost and no external network dependency
  during indexing, which matters directly given API credits are already a
  constrained resource elsewhere in this project.
"""

from functools import lru_cache

from fastembed import TextEmbedding

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# 384-dim, fastembed's default model -- small, fast, CPU-friendly, no GPU needed.
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


@lru_cache
def _get_model() -> TextEmbedding:
    # Cached at process level for the same reason as the Whisper model in
    # transcription_service.py: loading it per-call would pay real fixed
    # cost on every single request instead of once per worker/API process.
    logger.info("loading_embedding_model", model_name=_MODEL_NAME)
    return TextEmbedding(model_name=_MODEL_NAME)


class EmbeddingService:
    def __init__(self) -> None:
        self._model = _get_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of texts (transcript chunks, or a single question) into vectors."""
        if not texts:
            return []
        embeddings = list(self._model.embed(texts))
        return [vec.tolist() for vec in embeddings]