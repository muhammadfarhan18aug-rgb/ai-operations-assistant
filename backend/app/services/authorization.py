"""Backend authorization helpers that rely on the database."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.models.user_capability import UserCapability, capability_matches


def require_capability(capability: str) -> Callable[..., User]:
    """Require an authenticated user to hold a specific capability from the database."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        result = await session.execute(
            select(UserCapability.capability)
            .where(UserCapability.user_id == current_user.id)
            .limit(100)
        )
        stored_capabilities = {row[0] for row in result.fetchall()}

        if not any(capability_matches(value, capability) for value in stored_capabilities):
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
