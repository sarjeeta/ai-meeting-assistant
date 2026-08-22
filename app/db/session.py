"""
Async SQLAlchemy engine/session setup.

Why async engine (asyncpg) instead of sync psycopg2 in the API layer:
- FastAPI's whole value prop is handling concurrent I/O-bound requests on one
  event loop. A sync DB driver blocks that loop per query and defeats the
  purpose. Workers (Celery) use sync psycopg2 instead since Celery tasks run
  in separate worker processes, not on an event loop.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # detects stale connections (e.g. after DB failover) before using them
    echo=not settings.is_production,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session and guarantees cleanup/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
