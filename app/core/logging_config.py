"""
Structured (JSON) logging setup using structlog.

Why not just `print()` or basic logging:
- In production (CloudWatch), you need machine-parseable JSON logs so you can
  query "all errors for meeting_id=X" instead of grepping text blobs.
- structlog lets us bind context (request_id, meeting_id, user_id) once and
  have it automatically attached to every subsequent log line in that scope.
"""

import logging
import sys

import structlog

from app.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        # JSON in prod so CloudWatch/ELK can parse it.
        renderer = structlog.processors.JSONRenderer()
    else:
        # Pretty colored console output for local dev.
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
