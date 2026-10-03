"""Seed command for the required demo users and their capabilities."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_session
from app.models.product import Product
from app.models.user import User
from app.models.user_capability import UserCapability
from app.policies.ingestion import ingest_repository_policy_documents
from app.services.password import hash_password

SEED_USERS: list[dict[str, Any]] = [
    {
        "email": "admin@assistant.test",
        "password_field": "seed_admin_password",
        "is_admin": True,
        "capabilities": ["policy:read", "inventory:read", "order:create", "email:send"],
    },
    {
        "email": "ali@assistant.test",
        "password_field": "seed_ali_password",
        "is_admin": False,
        "capabilities": ["policy:read", "inventory:read"],
    },
    {
        "email": "sara@assistant.test",
        "password_field": "seed_sara_password",
        "is_admin": False,
        "capabilities": ["policy:read", "inventory:read", "order:create"],
    },
    {
        "email": "dave@assistant.test",
        "password_field": "seed_dave_password",
        "is_admin": False,
        "capabilities": [],
    },
]

LEGACY_SEED_FIELD_ALIASES: dict[str, str] = {
    "seed_admin_password": "SEED_ADMIN_PASSWORD",
    "seed_ali_password": "SEED_ALI_PASSWORD",
    "seed_sara_password": "SEED_SARA_PASSWORD",
    "seed_dave_password": "SEED_DAVE_PASSWORD",
}

SEED_PRODUCTS: list[dict[str, Any]] = [
    {"sku": "SKU-1001", "name": "Wireless keyboard", "quantity_on_hand": 74, "unit_price": "29.99", "supplier": "Northstar Supply"},
    {"sku": "SKU-1002", "name": "USB-C dock", "quantity_on_hand": 38, "unit_price": "119.00", "supplier": "Northstar Supply"},
    {"sku": "SKU-1003", "name": "27-inch monitor", "quantity_on_hand": 52, "unit_price": "239.00", "supplier": "Clearview Technology"},
    {"sku": "SKU-1004", "name": "Laptop stand", "quantity_on_hand": 7, "unit_price": "42.50", "supplier": "Northstar Supply"},
    {"sku": "SKU-1005", "name": "Noise-canceling headset", "quantity_on_hand": 31, "unit_price": "89.00", "supplier": "Clearview Technology"},
    {"sku": "SKU-1006", "name": "Webcam", "quantity_on_hand": 5, "unit_price": "64.00", "supplier": "Clearview Technology"},
    {"sku": "SKU-1007", "name": "Ergonomic chair", "quantity_on_hand": 24, "unit_price": "319.00", "supplier": "Workplace Partners"},
    {"sku": "SKU-1008", "name": "Desk lamp", "quantity_on_hand": 63, "unit_price": "38.00", "supplier": "Workplace Partners"},
    {"sku": "SKU-1009", "name": "Ethernet adapter", "quantity_on_hand": 9, "unit_price": "18.50", "supplier": "Northstar Supply"},
    {"sku": "SKU-1010", "name": "Portable SSD 1TB", "quantity_on_hand": 46, "unit_price": "109.00", "supplier": "Clearview Technology"},
    {"sku": "SKU-1011", "name": "Conference speakerphone", "quantity_on_hand": 3, "unit_price": "179.00", "supplier": "Clearview Technology"},
    {"sku": "SKU-1012", "name": "USB-C cable 2m", "quantity_on_hand": 118, "unit_price": "12.00", "supplier": "Northstar Supply"},
    {"sku": "SKU-1013", "name": "Document scanner", "quantity_on_hand": 16, "unit_price": "289.00", "supplier": "Office Essentials"},
    {"sku": "SKU-1014", "name": "Label printer", "quantity_on_hand": 28, "unit_price": "149.00", "supplier": "Office Essentials"},
    {"sku": "SKU-1015", "name": "Surge protector", "quantity_on_hand": 82, "unit_price": "24.00", "supplier": "Office Essentials"},
    {"sku": "SKU-1043", "name": "Operations sensor module", "quantity_on_hand": 120, "unit_price": "84.00", "supplier": "Northstar Supply"},
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
        password_field = seed["password_field"]
        password_value = (
            getattr(settings, password_field, "")
            or os.getenv(LEGACY_SEED_FIELD_ALIASES.get(password_field, password_field.upper()), "")
            or os.getenv("SEED_PASSWORD", "")
        )
        if not password_value:
            raise RuntimeError(
                "Seed credentials are not configured. Set SEED_PASSWORD or the per-user SEED_* environment variables before seeding demo users."
            )
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

            user.is_admin = seed["is_admin"]
            user.is_active = True
            expected_capabilities = set(seed["capabilities"])
            if expected_capabilities:
                await session.execute(
                    delete(UserCapability)
                    .where(UserCapability.user_id == user.id)
                    .where(UserCapability.capability.not_in(expected_capabilities))
                )
            else:
                await session.execute(delete(UserCapability).where(UserCapability.user_id == user.id))
            for capability in expected_capabilities:
                await ensure_capability(session, user.id, capability, user.id)

            if seed["is_admin"]:
                admin_user = user

        for product_seed in SEED_PRODUCTS:
            product = await session.scalar(select(Product).where(Product.sku == product_seed["sku"]))
            if product is None:
                product = Product(sku=product_seed["sku"])
                session.add(product)
            product.name = product_seed["name"]
            product.quantity_on_hand = product_seed["quantity_on_hand"]
            product.unit_price = Decimal(product_seed["unit_price"])
            product.supplier = product_seed["supplier"]

        if "admin_user" in locals():
            await ingest_repository_policy_documents(session, admin_user.id)

        await session.commit()
        break

    return {"created": created, "existing": existing}


def main() -> None:
    """Entry point for the demo-user seed command."""
    asyncio.run(seed_demo_users())


if __name__ == "__main__":
    main()
