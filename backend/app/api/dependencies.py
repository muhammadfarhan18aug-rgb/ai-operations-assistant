"""FastAPI dependencies for authenticated access and authorization."""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.user import User
from app.services.auth import decode_access_token


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    access_token: str | None = Cookie(default=None, alias="access_token"),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Validate a JWT from the HttpOnly cookie or the Authorization header and return the active user."""
    token = access_token
    if token is None and authorization is not None:
        scheme, _, header_token = authorization.partition(" ")
        if scheme.lower() == "bearer" and header_token:
            token = header_token

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        ) from exc

    user = await session.get(User, user_id_int)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )

    return user
