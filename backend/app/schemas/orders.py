"""Request schemas for direct purchase-order approval requests."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class DirectPurchaseOrderRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=128)
    quantity: int = Field(..., gt=0, le=100000)
    supplier: str = Field(..., min_length=1, max_length=255)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Required for authorized submissions; omitted keys still reach the DB capability check first.",
    )

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned or not all(character.isalnum() or character in "-_" for character in cleaned):
            raise ValueError("SKU must contain only letters, numbers, dashes, or underscores.")
        return cleaned