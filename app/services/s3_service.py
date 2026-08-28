"""
S3 service: generates presigned URLs for direct client -> S3 uploads.

Why presigned URLs instead of uploading through our FastAPI server:
- A 200MB meeting recording routed through our API server ties up a worker
  process/connection for the entire upload duration -> kills throughput and
  costs us compute for pure byte-shuffling.
- With a presigned URL, the client (browser/mobile) uploads DIRECTLY to S3.
  Our API only ever handles small JSON payloads. This is the standard
  production pattern for large file uploads on AWS.
"""

import uuid
from dataclasses import dataclass

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PresignedUploadResult:
    upload_url: str
    object_key: str
    expires_in_seconds: int


class S3ServiceError(Exception):
    """Raised when S3 operations fail after retries."""


class S3Service:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket_name
        self._expiry = settings.s3_presigned_url_expiry_seconds

        # In production (ECS Fargate), the task has an IAM role attached and
        # boto3's default credential chain picks up temporary credentials
        # from the container credential provider automatically -- no static
        # keys needed, nothing to leak, nothing to rotate. Locally (Docker
        # Compose has no IAM role to assume), we fall back to explicit keys
        # from .env. Passing empty strings to boto3 would be interpreted as
        # real (invalid) credentials, so they're only included when present.
        client_kwargs: dict = {
            "region_name": settings.aws_region,
            "config": BotoConfig(signature_version="s3v4"),
        }
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self._client = boto3.client("s3", **client_kwargs)

    def _build_object_key(self, user_id: str, filename: str) -> str:
        # Namespacing by user_id keeps per-user data logically partitioned,
        # which also makes IAM bucket policies / lifecycle rules easier later.
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
        return f"raw-audio/{user_id}/{uuid.uuid4()}.{ext}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def generate_presigned_upload_url(
        self, user_id: str, filename: str, content_type: str
    ) -> PresignedUploadResult:
        """
        Returns a presigned PUT URL the client can upload directly to.
        Retries transient AWS errors (throttling, network blips) with
        exponential backoff before giving up.
        """
        object_key = self._build_object_key(user_id, filename)
        try:
            url = self._client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=self._expiry,
            )
        except ClientError as exc:
            logger.error("s3_presign_failed", error=str(exc), object_key=object_key)
            raise S3ServiceError(f"Failed to generate presigned URL: {exc}") from exc

        logger.info("s3_presign_generated", object_key=object_key, user_id=user_id)
        return PresignedUploadResult(
            upload_url=url,
            object_key=object_key,
            expires_in_seconds=self._expiry,
        )

    def object_exists(self, object_key: str) -> bool:
        """
        Confirms the client actually completed the upload before we queue a
        transcription job for a file that doesn't exist yet.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            logger.error("s3_head_object_failed", error=str(exc), object_key=object_key)
            raise S3ServiceError(f"Failed to check object existence: {exc}") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def download_file(self, object_key: str, destination_path: str) -> None:
        """
        Downloads an object to a local path. Used by the worker to pull raw
        audio down before running ffprobe/transcription on it. Retries
        transient network errors -- a flaky connection shouldn't fail an
        entire meeting-processing job.
        """
        try:
            self._client.download_file(self._bucket, object_key, destination_path)
        except ClientError as exc:
            logger.error("s3_download_failed", error=str(exc), object_key=object_key)
            raise S3ServiceError(f"Failed to download object {object_key}: {exc}") from exc

    def generate_presigned_download_url(self, object_key: str) -> str:
        try:
            return self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=self._expiry,
            )
        except ClientError as exc:
            logger.error("s3_download_presign_failed", error=str(exc), object_key=object_key)
            raise S3ServiceError(f"Failed to generate download URL: {exc}") from exc
