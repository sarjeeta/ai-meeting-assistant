"""
Shared FastAPI dependencies.

NOTE on get_current_user_id:
Real JWT-based auth lands on Day 5. Until then we identify the caller via an
explicit `X-User-Id` header. This is NOT a security placeholder pretending to
be auth -- it's a working, functional mechanism for local/dev use that lets
every other layer (DB rows, S3 key namespacing, ownership checks) be built
correctly from day one. Swapping it for `Depends(get_current_user_from_jwt)`
on Day 5 requires touching exactly one function.
"""

from fastapi import Header, HTTPException, status


async def get_current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header (temporary auth until Day 5 JWT auth lands)",
        )
    return x_user_id
