"""Backend authorization helpers that rely on the database."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.models.user_capability import UserCapability


def require_capability(capability: str) -> Callable[..., User]:
    """Require an authenticated user to hold a specific capability from the database."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        result = await session.execute(
            select(UserCapability.id)
            .where(UserCapability.user_id == current_user.id)
            .where(UserCapability.capability == capability)
            .limit(1)
        )

        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient capability.",
            )

        return current_user

    return dependency


def require_admin() -> Callable[..., User]:
    """Require an authenticated user whose admin flag is stored in PostgreSQL."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        refreshed_user = await session.get(User, current_user.id)
        if refreshed_user is None or not refreshed_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator access required.",
            )
        return refreshed_user

    return dependency
