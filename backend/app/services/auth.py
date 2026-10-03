"""JWT and authentication service helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.services.password import verify_password


def create_access_token(user_id: int) -> str:
    """Create a signed JWT for a user identifier."""
    settings = get_settings()
    if not settings.jwt_secret or settings.jwt_secret == "change_this_in_development":
        raise ValueError("JWT_SECRET must be set to a secure value outside development.")

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:  # pragma: no cover - exercised through API tests
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        ) from exc


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    """Authenticate a user by email and password, using the database as the source of truth."""
    normalized_email = email.strip().lower()
    result = await session.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
