"""Temporary internal authorization verification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.authorization import require_capability

router = APIRouter(prefix="/authz", tags=["internal-dev"])


@router.get("/inventory-test")
async def inventory_test(
    _: object = Depends(require_capability("inventory:read")),
) -> dict[str, str]:
    """Internal development verification endpoint for inventory capability checks."""
    return {"status": "ok", "message": "inventory:read authorization passed"}


@router.get("/order-test")
async def order_test(
    _: object = Depends(require_capability("order:create")),
) -> dict[str, str]:
    """Internal development verification endpoint for order capability checks."""
    return {"status": "ok", "message": "order:create authorization passed"}


@router.get("/email-test")
async def email_test(
    _: object = Depends(require_capability("email:send")),
) -> dict[str, str]:
    """Internal development verification endpoint for email capability checks."""
    return {"status": "ok", "message": "email:send authorization passed"}
