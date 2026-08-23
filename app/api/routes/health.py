"""
Health check endpoint. ECS/ALB target groups poll this to decide whether to
route traffic to a container and whether to restart unhealthy ones.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def liveness() -> dict:
    """Liveness: is the process up? No dependency checks -- keep this cheap/fast."""
    return {"status": "ok"}


@router.get("/readyz", status_code=status.HTTP_200_OK)
async def readiness(db: AsyncSession = Depends(get_db_session)) -> dict:
    """Readiness: can we actually serve traffic? Checks the DB connection."""
    await db.execute(text("SELECT 1"))
    return {"status": "ready"}
