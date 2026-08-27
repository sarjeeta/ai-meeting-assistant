"""
Celery tasks for the meeting-processing pipeline.

Day 1 scope: everything up through audio download + validation. This task
owns the full "transcribing" pipeline stage; the actual speech-to-text call
(faster-whisper) is added inside this same task starting Day 2 -- the
download/validate/status-tracking scaffolding built today doesn't change.
"""

import json
import os
import subprocess
import tempfile
from dataclasses import asdict

from celery.utils.log import get_task_logger

from app.db.models import Meeting
from app.db.sync_session import SyncSessionLocal
from app.services.chunking_service import chunk_transcript
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService, LLMServiceError
from app.services.s3_service import S3Service, S3ServiceError
from app.services.transcription_service import TranscriptionError, TranscriptionService
from app.services.vector_service import VectorService, VectorServiceError
from workers.celery_app import celery_app
logger = get_task_logger(__name__)


class AudioValidationError(Exception):
    """
    Raised when the uploaded file can't be decoded as audio (corrupt upload,
    wrong format despite extension, zero-byte file, etc). Not retryable --
    retrying won't fix a permanently invalid file.
    """


def _get_meeting_state(meeting_id: str) -> tuple[str, str, str] | None:
    with SyncSessionLocal() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            return None
        return meeting.status, meeting.s3_object_key, meeting.user_id


def _update_meeting(
    meeting_id: str,
    *,
    status: str | None = None,
    duration_seconds: float | None = None,
    transcript: str | None = None,
    summary: str | None = None,
    key_decisions: list | None = None,
    action_items: list | None = None,
    error_message: str | None = None,
) -> None:
    with SyncSessionLocal() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            logger.warning("meeting_not_found_for_update meeting_id=%s", meeting_id)
            return
        if status is not None:
            meeting.status = status
        if duration_seconds is not None:
            meeting.duration_seconds = duration_seconds
        if transcript is not None:
            meeting.transcript = transcript
        if summary is not None:
            meeting.summary = summary
        if key_decisions is not None:
            meeting.key_decisions = key_decisions
        if action_items is not None:
            meeting.action_items = action_items
        if error_message is not None:
            meeting.error_message = error_message
        session.commit()


def _probe_audio_duration(file_path: str) -> float:
    """
    Uses ffprobe to confirm the file is decodable media and extract its
    duration. This is our validation step: if ffprobe can't parse it,
    faster-whisper won't be able to either, so we fail fast here rather
    than burning worker time on a doomed transcription later.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise AudioValidationError(f"ffprobe timed out inspecting file: {exc}") from exc
    except FileNotFoundError as exc:
        # ffmpeg/ffprobe not installed in this environment -- a config bug, not a bad file.
        raise RuntimeError("ffprobe binary not found; is ffmpeg installed in this image?") from exc

    if result.returncode != 0:
        raise AudioValidationError(f"ffprobe could not read file: {result.stderr.strip()[:500]}")

    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AudioValidationError(f"Could not parse duration from ffprobe output: {exc}") from exc

    if duration <= 0:
        raise AudioValidationError("Probed duration was zero or negative -- file has no audio content")

    return duration


@celery_app.task(
    bind=True,
    name="workers.tasks.prepare_audio_for_transcription",
    autoretry_for=(S3ServiceError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def prepare_audio_for_transcription(self, meeting_id: str) -> None:
    state = _get_meeting_state(meeting_id)
    if state is None:
        logger.warning("meeting_not_found meeting_id=%s", meeting_id)
        return

    status, object_key, user_id = state
    if status != "queued":
        # Idempotency guard: Celery's at-least-once delivery (task_acks_late) means
        # this task can be redelivered after a worker crash even if it already ran
        # partway through. If the meeting has already moved past 'queued', another
        # delivery is already handling it (or it's done) -- don't double-process.
        logger.info(
            "skipping_meeting_not_in_queued_state meeting_id=%s status=%s", meeting_id, status
        )
        return

    _update_meeting(meeting_id, status="transcribing")

    s3_service = S3Service()
    tmp_path = None
    try:
        suffix = os.path.splitext(object_key)[1] or ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_path = tmp_file.name

        s3_service.download_file(object_key, tmp_path)
        duration = _probe_audio_duration(tmp_path)
        _update_meeting(meeting_id, duration_seconds=duration)
        logger.info(
            "audio_validated_and_downloaded meeting_id=%s duration_seconds=%.2f",
            meeting_id,
            duration,
        )

        transcription_service = TranscriptionService()
        try:
            transcript = transcription_service.transcribe(tmp_path)
        except TranscriptionError as exc:
            # ffprobe already confirmed this is decodable media, so a
            # transcription-level failure here is unusual (e.g. pure silence,
            # non-speech audio) rather than a transient one -- don't retry.
            logger.error("transcription_failed meeting_id=%s error=%s", meeting_id, str(exc))
            _update_meeting(meeting_id, status="failed", error_message=str(exc))
            return

        # 'summarizing' signals this meeting is ready for the LLM
        # summarization step -- transcription is complete.
        _update_meeting(meeting_id, status="summarizing", transcript=transcript)
        logger.info(
            "meeting_transcribed meeting_id=%s transcript_length=%d",
            meeting_id,
            len(transcript),
        )

        # Index for RAG Q&A. Deliberately non-fatal: the transcript and
        # upcoming summary are already fully useful on their own, so a
        # vector-store hiccup shouldn't fail the whole meeting -- it should
        # just mean Q&A isn't available for this meeting until re-indexed.
        try:
            chunks = chunk_transcript(transcript)
            if chunks:
                embedding_service = EmbeddingService()
                embeddings = embedding_service.embed(chunks)
                vector_service = VectorService()
                vector_service.index_chunks(
                    meeting_id=meeting_id,
                    user_id=user_id,
                    chunks=chunks,
                    embeddings=embeddings,
                )
                logger.info(
                    "meeting_indexed_for_rag meeting_id=%s chunk_count=%d",
                    meeting_id,
                    len(chunks),
                )
        except VectorServiceError as exc:
            logger.error("rag_indexing_failed meeting_id=%s error=%s", meeting_id, str(exc))

        llm_service = LLMService()
        
        try:
            meeting_summary = llm_service.summarize(transcript)
        except LLMServiceError as exc:
            # LLMService already retries transient API errors internally
            # (tenacity) before raising -- by the time we see this, retrying
            # again at the Celery level is unlikely to help, so we fail the
            # meeting rather than loop.
            logger.error("summarization_failed meeting_id=%s error=%s", meeting_id, str(exc))
            _update_meeting(meeting_id, status="failed", error_message=str(exc))
            return

        _update_meeting(
            meeting_id,
            status="completed",
            summary=meeting_summary.summary,
            key_decisions=meeting_summary.key_decisions,
            action_items=[asdict(item) for item in meeting_summary.action_items],
        )
        logger.info(
            "meeting_completed meeting_id=%s action_items_count=%d",
            meeting_id,
            len(meeting_summary.action_items),
        )

    except AudioValidationError as exc:
        logger.error("audio_validation_failed meeting_id=%s error=%s", meeting_id, str(exc))
        _update_meeting(meeting_id, status="failed", error_message=str(exc))
        # Deliberately not re-raised: this is a permanent failure, and re-raising
        # would trigger Celery's retry logic for an error that will never resolve.

    except S3ServiceError as exc:
        logger.warning(
            "s3_transient_error meeting_id=%s attempt=%s error=%s",
            meeting_id,
            self.request.retries,
            str(exc),
        )
        raise  # autoretry_for catches this and reschedules with backoff

    except Exception as exc:
        logger.error("unexpected_task_failure meeting_id=%s error=%s", meeting_id, str(exc))
        _update_meeting(meeting_id, status="failed", error_message="Internal processing error")
        raise

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
