"""
Data-access layer. Routes never touch SQLAlchemy queries directly --
this keeps query logic testable/reusable and routes thin.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Meeting


async def create_meeting(
    session: AsyncSession, *, meeting_id: str, user_id: str, title: str, s3_object_key: str
) -> Meeting:
    meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title=title,
        s3_object_key=s3_object_key,
        status="pending_upload",
    )
    session.add(meeting)
    await session.commit()
    await session.refresh(meeting)
    return meeting


async def get_meeting(session: AsyncSession, meeting_id: str) -> Meeting | None:
    result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
    return result.scalar_one_or_none()


async def update_meeting_status(
    session: AsyncSession, meeting_id: str, status: str, error_message: str | None = None
) -> Meeting | None:
    meeting = await get_meeting(session, meeting_id)
    if meeting is None:
        return None
    meeting.status = status
    if error_message is not None:
        meeting.error_message = error_message
    await session.commit()
    await session.refresh(meeting)
    return meeting


async def list_meetings_for_user(
    session: AsyncSession, user_id: str, limit: int = 50, offset: int = 0
) -> list[Meeting]:
    result = await session.execute(
        select(Meeting)
        .where(Meeting.user_id == user_id)
        .order_by(Meeting.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
