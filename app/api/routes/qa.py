"""
Q&A (RAG) endpoint: answers questions about a specific meeting by embedding
the question, retrieving the most relevant transcript chunks from Qdrant,
and asking the LLM to answer using only that retrieved context.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.logging_config import get_logger
from app.db import crud
from app.db.session import get_db_session
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService, LLMServiceError
from app.services.vector_service import VectorService, VectorServiceError

router = APIRouter(prefix="/meetings", tags=["qa"])
logger = get_logger(__name__)


class AskQuestionRequest(BaseModel):
    question: str


class AskQuestionResponse(BaseModel):
    answer: str
    source_chunks: list[str]


@router.post("/{meeting_id}/ask", response_model=AskQuestionResponse)
async def ask_question(
    meeting_id: str,
    payload: AskQuestionRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> AskQuestionResponse:
    meeting = await crud.get_meeting(db, meeting_id)
    if meeting is None or meeting.user_id != user_id:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Meeting is not ready for questions yet (status: {meeting.status})",
        )

    try:
        embedding_service = EmbeddingService()
        query_vector = embedding_service.embed([payload.question])[0]

        vector_service = VectorService()
        matches = vector_service.search(
            query_embedding=query_vector,
            user_id=user_id,
            meeting_id=meeting_id,
            top_k=5,
        )
    except VectorServiceError as exc:
        logger.error("qa_retrieval_failed", meeting_id=meeting_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve relevant context for this question.",
        ) from exc

    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No indexed transcript content found for this meeting. "
                "It may have completed before RAG indexing was enabled, or indexing failed."
            ),
        )

    context_chunks = [m["text"] for m in matches]

    try:
        llm_service = LLMService()
        answer = llm_service.answer_question(payload.question, context_chunks)
    except LLMServiceError as exc:
        logger.error("qa_answer_generation_failed", meeting_id=meeting_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate an answer. Please try again.",
        ) from exc

    return AskQuestionResponse(answer=answer, source_chunks=context_chunks)