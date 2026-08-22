"""
Pydantic schemas: the contract between clients and our API.

Kept separate from db/models.py (SQLAlchemy) deliberately -- API shape and
DB shape drift over time (e.g. we may not want to expose internal columns
like `s3_object_key` raw, or we compute derived fields for the response).
Conflating them is a common junior mistake that bites you later.
"""

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class MeetingStatus(str, Enum):
    PENDING_UPLOAD = "pending_upload"
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"


class PresignedUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., examples=["audio/mpeg", "audio/wav"])
    title: str = Field(..., min_length=1, max_length=200)

    @field_validator("filename")
    @classmethod
    def validate_extension(cls, value: str) -> str:
        settings = get_settings()
        if not re.search(r"\.[a-zA-Z0-9]+$", value):
            raise ValueError("Filename must include a file extension")
        ext = "." + value.rsplit(".", 1)[-1].lower()
        if ext not in settings.allowed_extensions_list:
            raise ValueError(
                f"Unsupported file extension '{ext}'. "
                f"Allowed: {', '.join(settings.allowed_extensions_list)}"
            )
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        if not value.startswith("audio/") and not value.startswith("video/"):
            raise ValueError("content_type must be an audio/* or video/* MIME type")
        return value


class PresignedUploadResponse(BaseModel):
    meeting_id: str
    upload_url: str
    object_key: str
    expires_in_seconds: int


class MeetingConfirmRequest(BaseModel):
    meeting_id: str


class MeetingResponse(BaseModel):
    id: str
    title: str
    status: MeetingStatus
    created_at: str
    duration_seconds: float | None = None
    summary: str | None = None

    model_config = {"from_attributes": True}
