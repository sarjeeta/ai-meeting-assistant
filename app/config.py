"""
Centralized application configuration.

Why pydantic-settings instead of os.environ everywhere:
- Fails fast at startup if a required env var is missing/malformed, instead of
  crashing deep inside a request handler at 2am in prod.
- Gives us typed, autocompleted config objects instead of stringly-typed lookups.
- Single source of truth that's trivially mockable in tests (override Settings()).
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_env: str = "local"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # --- AWS / S3 ---
    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_bucket_name: str
    s3_presigned_url_expiry_seconds: int = 900

    # --- Postgres ---
    database_url: str

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Vector DB ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "meeting_chunks"

    # --- LLM ---
    # LLM_PROVIDER selects which vendor workers/tasks.py's LLMService talks to.
    # Set to "gemini" if Anthropic credits run out -- no other code changes needed.
    llm_provider: str = "gemini"
    anthropic_api_key: str
    llm_model: str = "claude-sonnet-4-6"
    gemini_api_key: str
    gemini_model: str = "gemini-3.6-flash"



    # --- Speech-to-Text (faster-whisper) ---
    # "base" is a reasonable CPU-speed/accuracy tradeoff for a resume project;
    # drop to "tiny" for faster local iteration, or "small"/"medium" if you
    # have a GPU worker in production. int8 compute_type keeps CPU inference
    # fast at a small accuracy cost -- fine for meeting audio, not medical transcription.
    stt_model_size: str = "base"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"

    # --- Auth ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # --- Uploads ---
    max_upload_size_mb: int = 500
    allowed_audio_extensions: str = ".mp3,.wav,.m4a,.mp4"

    @property
    def allowed_extensions_list(self) -> List[str]:
        return [ext.strip().lower() for ext in self.allowed_audio_extensions.split(",")]

    @property
    def sync_database_url(self) -> str:
        """
        Alembic and Celery workers use a sync engine (psycopg2), not asyncpg.
        Rather than maintain two separate env vars that can drift out of sync,
        derive the sync URL from the async one.
        """
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings singleton. lru_cache means Settings() is only constructed
    once per process instead of re-parsing env vars on every request.
    """
    return Settings()
