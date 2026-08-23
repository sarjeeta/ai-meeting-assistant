"""
Meetings API.

Flow implemented today (Day 0):
  1. POST /meetings/upload-url  -> client gets a presigned S3 URL + meeting_id
  2. Client PUTs the audio file directly to S3 using that URL
  3. POST /meetings/{id}/confirm -> we verify the object landed in S3, flip
     status to QUEUED, and (from Day 1 onward) enqueue the Celery task
  4. GET /meetings/{id} -> poll for status/result
  5. GET /meetings -> list caller's meetings

Enqueueing the actual Celery transcription task is wired in on Day 1.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.logging_config import get_logger
from app.db import crud
from app.db.session import get_db_session
from app.schemas.meeting import (
    MeetingResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from app.services.s3_service import S3Service, S3ServiceError
from workers.tasks import prepare_audio_for_transcription

router = APIRouter(prefix="/meetings", tags=["meetings"])
logger = get_logger(__name__)


def get_s3_service() -> S3Service:
    return S3Service()


@router.post(
    "/upload-url",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_url(
    payload: PresignedUploadRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    s3_service: S3Service = Depends(get_s3_service),
) -> PresignedUploadResponse:
    meeting_id = str(uuid.uuid4())

    try:
        presigned = s3_service.generate_presigned_upload_url(
            user_id=user_id,
            filename=payload.filename,
            content_type=payload.content_type,
        )
    except S3ServiceError as exc:
        logger.error("upload_url_generation_failed", user_id=user_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate upload URL. Please try again.",
        ) from exc

    await crud.create_meeting(
        db,
        meeting_id=meeting_id,
        user_id=user_id,
        title=payload.title,
        s3_object_key=presigned.object_key,
    )

    logger.info("meeting_created", meeting_id=meeting_id, user_id=user_id)

    return PresignedUploadResponse(
        meeting_id=meeting_id,
        upload_url=presigned.upload_url,
        object_key=presigned.object_key,
        expires_in_seconds=presigned.expires_in_seconds,
    )


@router.post("/{meeting_id}/confirm", response_model=MeetingResponse)
async def confirm_upload(
    meeting_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    s3_service: S3Service = Depends(get_s3_service),
) -> MeetingResponse:
    meeting = await crud.get_meeting(db, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.user_id != user_id:
        # Return 404, not 403, to avoid leaking existence of other users' resources.
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        exists = s3_service.object_exists(meeting.s3_object_key)
    except S3ServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify upload with storage provider.",
        ) from exc

    if not exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload not found in storage yet. Ensure the PUT to upload_url completed.",
        )

    updated = await crud.update_meeting_status(db, meeting_id, status="queued")

    # Enqueue onto Redis for a Celery worker to pick up. .delay() only serializes
    # the call and pushes it to the broker -- it does not run the task inline,
    # so this returns immediately regardless of how long processing takes.
    task = prepare_audio_for_transcription.delay(meeting_id)
    logger.info("meeting_confirmed_queued", meeting_id=meeting_id, celery_task_id=task.id)

    return MeetingResponse(
        id=updated.id,
        title=updated.title,
        status=updated.status,
        created_at=updated.created_at.isoformat(),
        duration_seconds=updated.duration_seconds,
        summary=updated.summary,
    )


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingResponse:
    meeting = await crud.get_meeting(db, meeting_id)
    if meeting is None or meeting.user_id != user_id:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        status=meeting.status,
        created_at=meeting.created_at.isoformat(),
        duration_seconds=meeting.duration_seconds,
        summary=meeting.summary,
    )


@router.get("", response_model=list[MeetingResponse])
async def list_meetings(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
    limit: int = 50,
    offset: int = 0,
) -> list[MeetingResponse]:
    meetings = await crud.list_meetings_for_user(db, user_id, limit=limit, offset=offset)
    return [
        MeetingResponse(
            id=m.id,
            title=m.title,
            status=m.status,
            created_at=m.created_at.isoformat(),
            duration_seconds=m.duration_seconds,
            summary=m.summary,
        )
        for m in meetings
    ]
