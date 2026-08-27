"""
LLM service: summarizes meeting transcripts, extracts structured action
items, and answers questions about a meeting using retrieved transcript
context (RAG). Supports two interchangeable providers -- Anthropic (Claude)
and Google (Gemini) -- selected via the LLM_PROVIDER setting.

Why an abstraction instead of hardcoding one vendor:
- API credits/quotas run out, pricing changes, and different vendors suit
  different budgets. Swapping providers should be a one-line config change
  (LLM_PROVIDER=gemini), not a rewrite of every call site.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class LLMServiceError(Exception):
    """Raised when the LLM fails to produce a usable result."""


class LLMConfigError(LLMServiceError):
    """
    Raised for permanent, account-level API errors: insufficient credits,
    invalid API key, malformed request. Retrying these does nothing until a
    human fixes the underlying account/config issue.
    """


@dataclass
class ActionItem:
    description: str
    owner: str | None = None
    due_date: str | None = None


@dataclass
class MeetingSummary:
    summary: str
    key_decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)


MAX_TRANSCRIPT_CHARS = 100_000

_SUMMARY_PROMPT = (
    "Here is a meeting transcript. Extract a concise summary, the key "
    "decisions explicitly made, and any action items assigned.\n\nTranscript:\n{transcript}"
)


def _build_qa_prompt(question: str, context_chunks: list[str]) -> str:
    numbered_context = "\n\n".join(f"[{i + 1}] {chunk}" for i, chunk in enumerate(context_chunks))
    return (
        "Answer the question using ONLY the meeting transcript excerpts below. "
        "Cite which excerpt(s) support your answer using their bracketed numbers, "
        "e.g. [1]. If the excerpts don't contain the answer, say so plainly "
        "instead of guessing.\n\n"
        f"Transcript excerpts:\n{numbered_context}\n\nQuestion: {question}"
    )


class _Summarizer(Protocol):
    def summarize(self, transcript: str) -> MeetingSummary: ...
    def answer(self, question: str, context_chunks: list[str]) -> str: ...


def _truncate(transcript: str) -> str:
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        logger.warning(
            "transcript_truncated_for_llm",
            original_length=len(transcript),
            truncated_to=MAX_TRANSCRIPT_CHARS,
        )
        return transcript[:MAX_TRANSCRIPT_CHARS]
    return transcript


# --------------------------------------------------------------------------
# Anthropic provider
# --------------------------------------------------------------------------

_ANTHROPIC_EXTRACTION_TOOL = {
    "name": "record_meeting_summary",
    "description": (
        "Records a structured summary of a meeting transcript, including "
        "key decisions made and action items assigned."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A concise 3-5 sentence summary of what was discussed and decided.",
            },
            "key_decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Distinct decisions explicitly made during the meeting.",
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "owner": {
                            "type": ["string", "null"],
                            "description": "Person responsible, if mentioned. null if unclear.",
                        },
                        "due_date": {
                            "type": ["string", "null"],
                            "description": "Due date in the transcript's own wording, e.g. 'next Friday'. null if not mentioned.",
                        },
                    },
                    "required": ["description"],
                },
            },
        },
        "required": ["summary", "key_decisions", "action_items"],
    },
}


class _AnthropicSummarizer:
    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model

    def _create(self, **kwargs):
        from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

        anthropic = self._anthropic

        @retry(
            retry=retry_if_exception_type(
                (
                    anthropic.RateLimitError,
                    anthropic.APIConnectionError,
                    anthropic.APITimeoutError,
                    anthropic.InternalServerError,
                )
            ),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        )
        def _do_call():
            return self._client.messages.create(model=self._model, **kwargs)

        return _do_call()

    def _run(self, **kwargs):
        anthropic = self._anthropic
        try:
            return self._create(**kwargs)
        except (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        ) as exc:
            logger.error("llm_api_call_failed_after_retries", provider="anthropic", error=str(exc))
            raise LLMServiceError(f"Anthropic API call failed after retries: {exc}") from exc
        except anthropic.APIError as exc:
            logger.error("llm_permanent_api_error", provider="anthropic", error=str(exc))
            raise LLMConfigError(f"Anthropic API rejected the request (non-retryable): {exc}") from exc

    def summarize(self, transcript: str) -> MeetingSummary:
        transcript = _truncate(transcript)
        response = self._run(
            max_tokens=2048,
            tools=[_ANTHROPIC_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_meeting_summary"},
            messages=[{"role": "user", "content": _SUMMARY_PROMPT.format(transcript=transcript)}],
        )
        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            raise LLMServiceError("Anthropic response did not include the expected tool_use block")
        return _parse_summary_dict(tool_use_block.input)

    def answer(self, question: str, context_chunks: list[str]) -> str:
        response = self._run(
            max_tokens=1024,
            messages=[{"role": "user", "content": _build_qa_prompt(question, context_chunks)}],
        )
        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise LLMServiceError("Anthropic response did not include a text block")
        return text_block.text.strip()


# --------------------------------------------------------------------------
# Gemini provider
# --------------------------------------------------------------------------


class _GeminiSummarizer:
    def __init__(self) -> None:
        from google import genai
        from pydantic import BaseModel

        class _GeminiActionItem(BaseModel):
            description: str
            owner: str | None = None
            due_date: str | None = None

        class _GeminiMeetingSummary(BaseModel):
            summary: str
            key_decisions: list[str] = []
            action_items: list[_GeminiActionItem] = []

        settings = get_settings()
        self._genai = genai
        self._schema = _GeminiMeetingSummary
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def _run(self, contents: str, config=None):
        from google.genai import errors

        try:
            return self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.ClientError as exc:
            # The SDK already auto-retries 429s internally before raising.
            # Non-429 client errors (400/401/403) are permanent config problems.
            code = getattr(exc, "code", None)
            logger.error("llm_client_error", provider="gemini", code=code, error=str(exc))
            if code == 429:
                raise LLMServiceError(f"Gemini rate limit exceeded: {exc}") from exc
            raise LLMConfigError(f"Gemini API rejected the request (non-retryable): {exc}") from exc
        except errors.ServerError as exc:
            logger.error("llm_server_error_after_retries", provider="gemini", error=str(exc))
            raise LLMServiceError(f"Gemini API call failed after retries: {exc}") from exc
        except errors.APIError as exc:
            logger.error("llm_api_error", provider="gemini", error=str(exc))
            raise LLMServiceError(f"Gemini API call failed: {exc}") from exc

    def summarize(self, transcript: str) -> MeetingSummary:
        from google.genai import types

        transcript = _truncate(transcript)
        response = self._run(
            _SUMMARY_PROMPT.format(transcript=transcript),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self._schema,
            ),
        )
        parsed = response.parsed
        if parsed is None:
            raise LLMServiceError("Gemini response could not be parsed against the expected schema")

        action_items = [
            ActionItem(description=item.description, owner=item.owner, due_date=item.due_date)
            for item in parsed.action_items
        ]
        return MeetingSummary(
            summary=parsed.summary, key_decisions=parsed.key_decisions, action_items=action_items
        )

    def answer(self, question: str, context_chunks: list[str]) -> str:
        response = self._run(_build_qa_prompt(question, context_chunks))
        if not response.text:
            raise LLMServiceError("Gemini response contained no text")
        return response.text.strip()


# --------------------------------------------------------------------------
# Shared parsing + public facade
# --------------------------------------------------------------------------


def _parse_summary_dict(data: dict) -> MeetingSummary:
    if "summary" not in data:
        raise LLMServiceError("LLM response missing required 'summary' field")
    try:
        action_items = [
            ActionItem(
                description=item["description"],
                owner=item.get("owner"),
                due_date=item.get("due_date"),
            )
            for item in data.get("action_items", [])
        ]
    except (KeyError, TypeError) as exc:
        raise LLMServiceError(f"Malformed action_items in LLM response: {exc}") from exc

    return MeetingSummary(
        summary=data["summary"],
        key_decisions=data.get("key_decisions", []),
        action_items=action_items,
    )


class LLMService:
    """
    Public facade used by callers (workers/tasks.py, the Q&A route). Picks
    the configured provider once at construction time; callers never branch
    on provider.
    """

    def __init__(self) -> None:
        settings = get_settings()
        provider = settings.llm_provider.lower()
        if provider == "gemini":
            self._impl: _Summarizer = _GeminiSummarizer()
        elif provider == "anthropic":
            self._impl = _AnthropicSummarizer()
        else:
            raise LLMConfigError(
                f"Unknown LLM_PROVIDER '{settings.llm_provider}' -- expected 'anthropic' or 'gemini'"
            )

    def summarize(self, transcript: str) -> MeetingSummary:
        summary = self._impl.summarize(transcript)
        logger.info(
            "llm_summary_generated",
            key_decisions_count=len(summary.key_decisions),
            action_items_count=len(summary.action_items),
        )
        return summary

    def answer_question(self, question: str, context_chunks: list[str]) -> str:
        answer = self._impl.answer(question, context_chunks)
        logger.info("llm_qa_answer_generated", context_chunk_count=len(context_chunks))
        return answer