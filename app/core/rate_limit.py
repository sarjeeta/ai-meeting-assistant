
"""
Simple fixed-window rate limiter backed by Redis.

Why Redis instead of an in-process counter:
- The API can run as multiple replicas in production (and even locally,
  multiple Uvicorn workers). An in-process dict would let each
  process/replica enforce its own separate limit, effectively multiplying
  the real limit by replica count. Redis gives one shared counter every
  replica sees.

Why a fixed window instead of a sliding one:
- A fixed window can let a burst right at the window boundary through at
  up to ~2x the stated limit briefly. A true sliding window avoids that but
  needs a sorted-set + timestamp cleanup dance. For abuse prevention on
  auth/upload endpoints (not billing-grade quota enforcement), that
  simplicity/precision tradeoff is the right one.
"""

import time

import redis.asyncio as redis
from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def _get_redis() -> redis.Redis:
    """
    Create a Redis client for the current event-loop context.

    The client is intentionally not stored in a module-level global because
    async Redis connections are tied to the event loop in which they are used.
    """
    settings = get_settings()
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )


def rate_limit(
    *,
    key_prefix: str,
    max_requests: int,
    window_seconds: int,
):
    """
    Returns a FastAPI dependency enforcing `max_requests` per
    `window_seconds` per client IP.
    """

    async def dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"

        window = int(time.time() // window_seconds)

        key = f"ratelimit:{key_prefix}:{client_ip}:{window}"

        redis_client = _get_redis()

        try:
            count = await redis_client.incr(key)

            if count == 1:
                await redis_client.expire(key, window_seconds)

        except redis.RedisError as exc:
            # Fail open: if Redis itself is unreachable, availability of the
            # protected endpoint matters more than strict rate-limit
            # enforcement.
            logger.warning(
                "rate_limiter_unavailable",
                key_prefix=key_prefix,
                error=str(exc),
            )
            return

        finally:
            await redis_client.aclose()

        if count > max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again shortly.",
            )

    return dependency