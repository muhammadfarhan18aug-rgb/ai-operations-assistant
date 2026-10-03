"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.models.user_capability import UserCapability
from app.schemas.auth import CurrentUserResponse, LoginRequest, LoginResponse
from app.services.auth import authenticate_user, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """Authenticate a user and return a JWT token."""
    user = await authenticate_user(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    token = create_access_token(user.id)
    return LoginResponse(access_token=token, token_type="bearer")


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user_summary(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CurrentUserResponse:
    """Return the authenticated user's safe identity and capabilities from PostgreSQL."""
    result = await session.execute(
        select(UserCapability.capability).where(UserCapability.user_id == current_user.id)
    )
    capabilities = sorted({row[0] for row in result.fetchall()})
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        is_admin=current_user.is_admin,
        is_active=current_user.is_active,
        capabilities=capabilities,
    )
