"""
Speech-to-text service wrapping faster-whisper.

Why the model is loaded once per worker process (via lru_cache) instead of
once per task:
- Loading a Whisper model -- even "base" -- costs real time and memory.
  Paying that cost on every single task would mean meeting #50 takes just as
  long to start as meeting #1. Loading it once and reusing it across every
  task handled by that worker process is the standard pattern.
"""

from functools import lru_cache

from faster_whisper import WhisperModel

from app.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class TranscriptionError(Exception):
    """Raised when faster-whisper fails to produce a usable transcript."""


@lru_cache
def _get_model() -> WhisperModel:
    settings = get_settings()
    logger.info(
        "loading_whisper_model",
        model_size=settings.stt_model_size,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
    )
    return WhisperModel(
        settings.stt_model_size,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
    )


class TranscriptionService:
    def __init__(self) -> None:
        # _get_model() is lru_cache'd, so this is a no-op after the first call
        # in this process -- not a fresh load every time TranscriptionService()
        # is constructed.
        self._model = _get_model()

    def transcribe(self, audio_path: str) -> str:
        """
        Runs faster-whisper over the audio file and returns the transcript as
        plain text. faster-whisper yields a generator of segments lazily --
        we materialize it fully here since we need the complete transcript
        before handing it to summarization (Day 3), not a streaming result.
        """
        try:
            segments, info = self._model.transcribe(audio_path, beam_size=5)
            text_parts = [segment.text.strip() for segment in segments]
        except Exception as exc:
            logger.error("whisper_transcription_failed", error=str(exc))
            raise TranscriptionError(f"faster-whisper failed to transcribe audio: {exc}") from exc

        transcript = " ".join(part for part in text_parts if part)
        if not transcript:
            raise TranscriptionError(
                "Transcription produced empty output -- audio may be silent or non-speech"
            )

        logger.info(
            "transcription_complete",
            detected_language=info.language,
            language_probability=round(info.language_probability, 3),
            transcript_length=len(transcript),
        )
        return transcript