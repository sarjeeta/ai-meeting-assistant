"""
Sync SQLAlchemy engine/session for use inside Celery workers.

Why a separate engine from app/db/session.py's async one:
- Celery tasks run in worker processes with no event loop. Forcing async
  SQLAlchemy in there means either running a throwaway event loop per task
  (messy, error-prone) or using asyncio.run() everywhere. A plain sync
  session is simpler and correct for this execution model.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()

sync_engine = create_engine(
    settings.sync_database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)
