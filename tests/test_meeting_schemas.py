"""Unit tests for meeting request/response schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas.meeting import PresignedUploadRequest


def test_valid_upload_request_passes():
    req = PresignedUploadRequest(filename="standup.mp3", content_type="audio/mpeg", title="Standup")
    assert req.filename == "standup.mp3"


def test_rejects_unsupported_extension():
    with pytest.raises(ValidationError):
        PresignedUploadRequest(filename="standup.exe", content_type="audio/mpeg", title="Standup")


def test_rejects_missing_extension():
    with pytest.raises(ValidationError):
        PresignedUploadRequest(filename="standup", content_type="audio/mpeg", title="Standup")


def test_rejects_non_audio_video_content_type():
    with pytest.raises(ValidationError):
        PresignedUploadRequest(filename="standup.mp3", content_type="application/json", title="Standup")


def test_accepts_video_content_type_for_video_extension():
    req = PresignedUploadRequest(filename="standup.mp4", content_type="video/mp4", title="Standup")
    assert req.content_type == "video/mp4"


def test_rejects_empty_title():
    with pytest.raises(ValidationError):
        PresignedUploadRequest(filename="standup.mp3", content_type="audio/mpeg", title="")