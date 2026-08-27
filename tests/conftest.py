"""
Shared pytest fixtures.

Sets required env vars before any app module is imported, since Settings()
validates required fields at import time and there's no .env file in CI.
Real AWS/Anthropic/Gemini credentials are never needed for the test suite --
external services (S3, the vector store, the LLM) are faked out or simply
never exercised by these tests.
"""

import os

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-tests-only-do-not-use-in-prod")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db_session
from app.main import app
from app.services.auth_service import create_access_token
from app.services.s3_service import PresignedUploadResult

# In-memory SQLite, shared across the whole test via StaticPool -- without
# StaticPool, an in-memory SQLite DB is per-connection, and the async pool
# would hand different tests different (empty) databases.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(loop_scope="function")
async def db_session_factory():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_factory

    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def client(db_session_factory):
    """An httpx client wired to the real FastAPI app, with the DB swapped for SQLite."""

    async def _override_get_db_session():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


class FakeS3Service:
    """Stands in for S3Service in tests -- makes no real AWS calls."""

    def generate_presigned_upload_url(self, *, user_id: str, filename: str, content_type: str):
        return PresignedUploadResult(
            upload_url=f"https://fake-s3.test/{user_id}/{filename}",
            object_key=f"raw-audio/{user_id}/fake-object-key",
            expires_in_seconds=900,
        )

    def object_exists(self, object_key: str) -> bool:
        return True

    def generate_presigned_download_url(self, object_key: str) -> str:
        return f"https://fake-s3.test/download/{object_key}"


@pytest.fixture
def auth_headers() -> dict:
    token = create_access_token("test-user-id")
    return {"Authorization": f"Bearer {token}"}
