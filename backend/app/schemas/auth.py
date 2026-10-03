"""Authentication request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.email import EmailAddress


class LoginRequest(BaseModel):
    """Authentication payload for a user login request."""

    email: EmailAddress
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """JWT payload returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    """Safe user identity information returned to the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_admin: bool
    is_active: bool
    capabilities: list[str]


class AdminUserResponse(CurrentUserResponse):
    """User summary returned from the admin user-list endpoint."""

    pass
