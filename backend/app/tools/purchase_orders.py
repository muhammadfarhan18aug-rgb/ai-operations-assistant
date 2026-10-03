"""Purchase order creation tool with DB-authoritative authorization and idempotency."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.product import Product
from app.models.thread import Thread
from app.tools.authorization import ToolAuthorizationError, ToolConflictError, ToolNotFoundError, authorize_tool, ensure_thread_for_context
from app.tools.context import ToolContext


class PurchaseOrderCreateInput(BaseModel):
    """Validated purchase order creation request."""

    sku: str = Field(..., min_length=1, max_length=128)
    quantity: int = Field(..., gt=0, le=100000)
    supplier: str = Field(..., min_length=1, max_length=255)
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not all(ch.isalnum() or ch in "-_" for ch in cleaned):
            raise ValueError("SKU must contain only letters, numbers, dashes, or underscores.")
        return cleaned


async def create_purchase_order(
    session: AsyncSession,
    context: ToolContext,
    sku: str | PurchaseOrderCreateInput | None = None,
    quantity: int | None = None,
    supplier: str | None = None,
    idempotency_key: str | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Create a purchase order only after the backend-authoritative capability check succeeds."""
    data: PurchaseOrderCreateInput
    if isinstance(sku, PurchaseOrderCreateInput):
        data = sku
    else:
        if sku is None:
            raise ToolAuthorizationError("Purchase order SKU is required.")
        if quantity is None or supplier is None or idempotency_key is None:
            raise ToolAuthorizationError("Purchase order quantity, supplier, and idempotency key are required.")
        data = PurchaseOrderCreateInput(
            sku=sku,
            quantity=quantity,
            supplier=supplier,
            idempotency_key=idempotency_key,
        )

    user = await authorize_tool(session, context, "order:create")

    existing = await session.execute(
        select(Order).where(Order.idempotency_key == data.idempotency_key).limit(1)
    )
    duplicate = existing.scalar_one_or_none()
    if duplicate is not None:
        return {
            "order_reference": duplicate.order_reference,
            "sku": duplicate.sku,
            "quantity": int(duplicate.quantity),
            "supplier": duplicate.supplier,
            "requested_by": duplicate.requested_by,
            "idempotency_key": duplicate.idempotency_key,
            "status": "duplicate",
        }

    product = await session.execute(select(Product).where(Product.sku == data.sku).limit(1))
    product_record = product.scalar_one_or_none()
    if product_record is None:
        raise ToolNotFoundError(f"Product '{data.sku}' was not found.")

    thread = await ensure_thread_for_context(session, context, user.id, f"Purchase order for {data.sku}")

    order_reference = f"PO-{uuid4().hex[:12].upper()}"
    order = Order(
        order_reference=order_reference,
        sku=data.sku,
        quantity=data.quantity,
        supplier=data.supplier,
        requested_by=user.id,
        idempotency_key=data.idempotency_key,
    )
    session.add(order)
    await session.flush()

    audit = AuditLog(
        user_id=user.id,
        tool="purchase_order_create",
        arguments={
            "sku": data.sku,
            "quantity": data.quantity,
            "supplier": data.supplier,
            "idempotency_key": data.idempotency_key,
            "thread_id": str(thread.id),
        },
        outcome="executed",
        thread_id=thread.id,
    )
    session.add(audit)
    await session.commit()

    return {
        "order_reference": order_reference,
        "sku": data.sku,
        "quantity": int(data.quantity),
        "supplier": data.supplier,
        "requested_by": user.id,
        "idempotency_key": data.idempotency_key,
        "status": "created",
    }
