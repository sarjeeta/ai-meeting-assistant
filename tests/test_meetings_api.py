"""
Integration tests for the meetings upload-url flow. S3 is faked out
(FakeS3Service in conftest.py) -- these tests never touch real AWS.
"""

import pytest

from app.api.routes.meetings import get_s3_service
from app.main import app
from app.services.auth_service import create_access_token
from tests.conftest import FakeS3Service


@pytest.fixture(autouse=True)
def override_s3_service():
    app.dependency_overrides[get_s3_service] = lambda: FakeS3Service()
    yield
    app.dependency_overrides.pop(get_s3_service, None)


@pytest.mark.asyncio
async def test_create_upload_url_success(client, auth_headers):
    response = await client.post(
        "/api/v1/meetings/upload-url",
        headers=auth_headers,
        json={"filename": "standup.mp3", "content_type": "audio/mpeg", "title": "Standup"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "upload_url" in body
    assert "meeting_id" in body


@pytest.mark.asyncio
async def test_create_upload_url_rejects_bad_extension(client, auth_headers):
    response = await client.post(
        "/api/v1/meetings/upload-url",
        headers=auth_headers,
        json={"filename": "standup.exe", "content_type": "audio/mpeg", "title": "Standup"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_upload_url_requires_auth(client):
    response = await client.post(
        "/api/v1/meetings/upload-url",
        json={"filename": "standup.mp3", "content_type": "audio/mpeg", "title": "Standup"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_nonexistent_meeting_returns_404(client, auth_headers):
    response = await client.get("/api/v1/meetings/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_users_cannot_see_each_others_meetings(client, auth_headers):
    await client.post(
        "/api/v1/meetings/upload-url",
        headers=auth_headers,
        json={"filename": "standup.mp3", "content_type": "audio/mpeg", "title": "Standup"},
    )

    other_user_headers = {"Authorization": f"Bearer {create_access_token('a-different-user')}"}
    other_users_view = await client.get("/api/v1/meetings", headers=other_user_headers)
    assert other_users_view.status_code == 200
    assert other_users_view.json() == []

    own_view = await client.get("/api/v1/meetings", headers=auth_headers)
    assert own_view.status_code == 200
    assert len(own_view.json()) == 1