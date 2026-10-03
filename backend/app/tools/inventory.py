"""Inventory lookup tool with DB-authoritative authorization."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext


class InventoryLookupInput(BaseModel):
    """Validated inventory lookup request."""

    sku: str = Field(..., min_length=1, max_length=128)

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not all(ch.isalnum() or ch in "-_" for ch in cleaned):
            raise ValueError("SKU must contain only letters, numbers, dashes, or underscores.")
        return cleaned


async def lookup_inventory(
    session: AsyncSession,
    context: ToolContext,
    sku: str | InventoryLookupInput,
    **_ignored: object,
) -> dict[str, object]:
    """Return product inventory details only after database-backed capability authorization."""
    if isinstance(sku, InventoryLookupInput):
        validated = sku
    else:
        validated = InventoryLookupInput(sku=sku)

    await authorize_tool(session, context, "inventory:read")

    result = await session.execute(select(Product).where(Product.sku == validated.sku))
    product = result.scalar_one_or_none()
    if product is None:
        raise ToolAuthorizationError(f"Product '{validated.sku}' was not found.")

    return {
        "sku": product.sku,
        "name": product.name,
        "quantity_on_hand": int(product.quantity_on_hand),
        "unit_price": str(product.unit_price),
        "supplier": product.supplier,
    }
