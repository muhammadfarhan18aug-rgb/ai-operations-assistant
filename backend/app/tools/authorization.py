"""Backend-authoritative authorization boundary for operational tools."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import Thread
from app.models.user import User
from app.models.user_capability import UserCapability
from app.tools.context import ToolContext


class ToolAuthorizationError(RuntimeError):
    """Raised when a tool call is not authorized by the database-backed capability state."""


class ToolValidationError(ValueError):
    """Raised for invalid tool input."""


class ToolNotFoundError(LookupError):
    """Raised when a required business record cannot be found."""


class ToolConflictError(RuntimeError):
    """Raised for duplicate or conflicting business operations."""


async def authorize_tool(session: AsyncSession, context: ToolContext, required_capability: str) -> User:
    """Load the active authenticated user and verify the required DB capability."""
    if context.authenticated_user_id is None:
        raise ToolAuthorizationError("Authenticated user context is required.")

    user = await session.get(User, context.authenticated_user_id)
    if user is None or not user.is_active:
        raise ToolAuthorizationError("Authenticated user is not active.")

    result = await session.execute(
        select(UserCapability.id)
        .where(UserCapability.user_id == user.id)
        .where(UserCapability.capability == required_capability)
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise ToolAuthorizationError(f"User does not have the '{required_capability}' capability.")

    return user


async def ensure_thread_for_context(session: AsyncSession, context: ToolContext, user_id: int, title: str) -> Thread:
    """Ensure a valid thread exists for an authenticated tool execution."""
    if context.thread_id is None:
        thread = Thread(owner_user_id=user_id, title=title[:80])
        session.add(thread)
        await session.flush()
        return thread

    thread = await session.get(Thread, context.thread_id)
    if thread is None:
        raise ToolNotFoundError("Thread not found.")
    if thread.owner_user_id != user_id:
        raise ToolAuthorizationError("Thread does not belong to the authenticated user.")
    return thread
