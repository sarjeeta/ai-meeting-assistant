"""Unit tests for password hashing and JWT issuance/verification."""

import time

import pytest
from jose import jwt

from app.config import get_settings
from app.services.auth_service import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_does_not_return_plaintext():
    hashed = hash_password("my-secret-password")
    assert hashed != "my-secret-password"


def test_verify_password_accepts_correct_password():
    hashed = hash_password("my-secret-password")
    assert verify_password("my-secret-password", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("my-secret-password")
    assert verify_password("a-different-password", hashed) is False


def test_access_token_round_trip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_decode_rejects_tampered_token():
    token = create_access_token("user-123")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(AuthError):
        decode_access_token(tampered)


def test_decode_rejects_expired_token():
    settings = get_settings()
    expired_payload = {"sub": "user-123", "exp": int(time.time()) - 1}
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(AuthError):
        decode_access_token(expired_token)


def test_decode_rejects_token_missing_sub_claim():
    settings = get_settings()
    payload = {"exp": int(time.time()) + 3600}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(AuthError):
        decode_access_token(token)