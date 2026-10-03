"""Seed command for the four demo users and their capabilities."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_session
from app.models.user import User
from app.models.user_capability import UserCapability
from app.services.password import hash_password

SEED_USERS: list[dict[str, Any]] = [
    {
        "email": "admin@cellutech.com",
        "password_field": "seed_admin_password",
        "is_admin": True,
        "capabilities": ["policy:read", "inventory:read", "order:create", "email:send"],
    },
    {
        "email": "ops@cellutech.com",
        "password_field": "seed_ops_password",
        "is_admin": False,
        "capabilities": ["policy:read", "inventory:read", "order:create", "email:send"],
    },
    {
        "email": "manager@cellutech.com",
        "password_field": "seed_manager_password",
        "is_admin": False,
        "capabilities": ["policy:read", "inventory:read", "order:create"],
    },
    {
        "email": "viewer@cellutech.com",
        "password_field": "seed_viewer_password",
        "is_admin": False,
        "capabilities": ["policy:read", "inventory:read"],
    },
]


async def ensure_capability(
    session: AsyncSession,
    user_id: int,
    capability: str,
    granted_by: int,
) -> None:
    """Ensure exactly one capability assignment exists per user/capability pair."""
    existing = await session.execute(
        select(UserCapability.id).where(
            UserCapability.user_id == user_id,
            UserCapability.capability == capability,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            UserCapability(
                user_id=user_id,
                capability=capability,
                granted_by=granted_by,
            )
        )


async def seed_demo_users() -> dict[str, list[str]]:
    """Create the required demo users and capabilities if they do not already exist."""
    settings = get_settings()
    created: list[str] = []
    existing: list[str] = []
    seed_passwords: dict[str, str] = {}

    for seed in SEED_USERS:
        password_value = getattr(settings, seed["password_field"])
        if not password_value:
            raise RuntimeError(f"Missing required seed password: {seed['password_field']}.")
        seed_passwords[seed["email"]] = password_value

    async for session in get_db_session():
        for seed in SEED_USERS:
            email = seed["email"]
            user = await session.scalar(select(User).where(User.email == email))

            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(seed_passwords[email]),
                    is_admin=seed["is_admin"],
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                created.append(email)
                print(f"Created user {email}")
            else:
                existing.append(email)
                print(f"User already exists {email}")

            for capability in seed["capabilities"]:
                await ensure_capability(session, user.id, capability, user.id)

        await session.commit()
        break

    return {"created": created, "existing": existing}


def main() -> None:
    """Entry point for the demo-user seed command."""
    asyncio.run(seed_demo_users())


if __name__ == "__main__":
    main()
