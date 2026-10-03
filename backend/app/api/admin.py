"""Admin-only API endpoints for user and capability visibility."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.user import User
from app.models.user_capability import UserCapability
from app.schemas.auth import AdminUserResponse
from app.services.authorization import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminUserResponse]:
    """Return user summaries for administrators only."""
    users = (await session.execute(select(User))).scalars().all()
    response: list[AdminUserResponse] = []

    for user in users:
        capability_rows = await session.execute(
            select(UserCapability.capability).where(UserCapability.user_id == user.id)
        )
        caps = sorted({row[0] for row in capability_rows.fetchall()})
        response.append(
            AdminUserResponse(
                id=user.id,
                email=user.email,
                is_admin=user.is_admin,
                is_active=user.is_active,
                capabilities=caps,
            )
        )

    return response
