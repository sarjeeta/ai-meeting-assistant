"""
Shared FastAPI dependencies.

get_current_user_id now verifies a JWT bearer token instead of trusting an
X-User-Id header. Every caller of this dependency (meetings routes, qa
routes) is unchanged -- they only ever depended on getting back a user_id
string, never on how it was obtained. That's exactly the swap the Day 0
comment promised.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth_service import AuthError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header (expected 'Bearer <token>')",
        )
    try:
        return decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc