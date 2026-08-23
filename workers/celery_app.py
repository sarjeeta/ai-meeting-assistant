"""
Celery application instance.

Config choices explained:
- task_acks_late=True: the task is only ack'd (removed from the queue) after
  it finishes, not when the worker picks it up. If the worker process crashes
  mid-task, the job goes back on the queue instead of being silently lost.
- worker_prefetch_multiplier=1: prevents one worker from hoarding many long
  audio-processing jobs while other workers sit idle. Correct for long-running
  tasks; the Celery default (4) is tuned for short tasks.
- task_reject_on_worker_lost=True: complements acks_late -- if the worker is
  killed (OOM, deploy) while holding a task, requeue it rather than lose it.
- broker_connection_retry_on_startup=True: don't crash the worker if Redis
  isn't up yet at boot (common in docker-compose startup ordering).
"""

from celery import Celery

from app.config import get_settings
from app.core.logging_config import configure_logging

configure_logging()  # workers are a separate process from the API -- logging must be set up here too

settings = get_settings()

celery_app = Celery(
    "ai_meeting_assistant",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_default_queue="meeting_processing",
    # Long transcriptions of long meetings shouldn't be able to hang forever.
    task_time_limit=60 * 30,  # hard kill after 30 min
    task_soft_time_limit=60 * 25,  # raises SoftTimeLimitExceeded at 25 min for graceful cleanup
)
