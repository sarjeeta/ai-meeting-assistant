"""
Password hashing and JWT issuance/verification.

Why bcrypt via passlib instead of a faster hash like SHA-256:
- Password hashing needs to be deliberately slow -- that's what defends
  against offline brute-force cracking if the DB ever leaks. bcrypt's cost
  factor is exactly that dial. Using a fast general-purpose hash here would
  be a real vulnerability, not a style preference.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Raised for invalid credentials or an invalid/expired token."""


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Returns the user_id encoded in the token's 'sub' claim, or raises AuthError."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AuthError(f"Invalid or expired token: {exc}") from exc

    user_id = payload.get("sub")
    if user_id is None:
        raise AuthError("Token missing 'sub' claim")
    return user_id