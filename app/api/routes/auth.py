"""
Authentication endpoints: register and login.

This replaces the temporary X-User-Id header used since Day 0 to unblock
every other layer (S3 key namespacing, DB ownership checks, RAG scoping)
before real auth existed. Everything downstream already expects a user_id
string -- only app/api/deps.py needed to change to swap the source of that
user_id from a trusted header to a verified JWT.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit
from app.db import crud
from app.db.session import get_db_session
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(key_prefix="register", max_requests=5, window_seconds=60))],
)
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db_session)
) -> TokenResponse:
    existing = await crud.get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = await crud.create_user(
        db, email=payload.email, hashed_password=hash_password(payload.password)
    )
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(key_prefix="login", max_requests=5, window_seconds=60))],
)
async def login(
    payload: LoginRequest, db: AsyncSession = Depends(get_db_session)
) -> TokenResponse:
    user = await crud.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Deliberately identical error for "no such user" and "wrong password" --
        # distinguishing them would let an attacker enumerate registered emails.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)