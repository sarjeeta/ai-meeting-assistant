"""
Vector store service wrapping Qdrant for meeting transcript chunk storage
and retrieval.

Why Qdrant instead of a managed service like Pinecone:
- Self-hostable for free (already running via docker-compose in this
  project), which matters for a portfolio project where ongoing SaaS cost
  isn't justified. A production deployment needing multi-region replication
  or fully managed ops might choose a managed vector DB instead -- swapping
  would mean implementing this same interface against another client, the
  same pattern used for the LLM provider abstraction.
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.config import get_settings
from app.core.logging_config import get_logger
from app.services.embedding_service import EMBEDDING_DIM

logger = get_logger(__name__)


class VectorServiceError(Exception):
    """Raised when Qdrant operations fail."""


class VectorService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = QdrantClient(url=settings.qdrant_url)
        self._collection = settings.qdrant_collection_name
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            existing = [c.name for c in self._client.get_collections().collections]
            if self._collection not in existing:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
                )
                logger.info("qdrant_collection_created", collection=self._collection)
        except Exception as exc:
            logger.error("qdrant_collection_setup_failed", error=str(exc))
            raise VectorServiceError(f"Failed to ensure Qdrant collection exists: {exc}") from exc

    def index_chunks(
        self,
        *,
        meeting_id: str,
        user_id: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise VectorServiceError("chunks and embeddings length mismatch")

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "meeting_id": meeting_id,
                    "user_id": user_id,
                    "chunk_index": idx,
                    "text": chunk,
                },
            )
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        try:
            self._client.upsert(collection_name=self._collection, points=points)
        except Exception as exc:
            logger.error("qdrant_upsert_failed", meeting_id=meeting_id, error=str(exc))
            raise VectorServiceError(f"Failed to index chunks: {exc}") from exc

        logger.info("chunks_indexed", meeting_id=meeting_id, chunk_count=len(chunks))

    def search(
        self,
        *,
        query_embedding: list[float],
        user_id: str,
        meeting_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        # Always scope by user_id -- without this filter, one user's question
        # could retrieve another user's meeting content. meeting_id narrows
        # further to a single meeting when the caller wants that.
        must_conditions = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        if meeting_id is not None:
            must_conditions.append(FieldCondition(key="meeting_id", match=MatchValue(value=meeting_id)))

        try:
            results = self._client.query_points(
                collection_name=self._collection,
                query=query_embedding,
                query_filter=Filter(must=must_conditions),
                limit=top_k,
            )
        except Exception as exc:
            logger.error("qdrant_search_failed", user_id=user_id, error=str(exc))
            raise VectorServiceError(f"Failed to search vector store: {exc}") from exc

        return [
            {
                "text": point.payload["text"],
                "meeting_id": point.payload["meeting_id"],
                "chunk_index": point.payload["chunk_index"],
                "score": point.score,
            }
            for point in results.points
        ]