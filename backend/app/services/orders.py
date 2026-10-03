"""Direct purchase-order requests that enter the same graph approval boundary."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.thread import Thread
from app.models.user import User
from app.schemas.orders import DirectPurchaseOrderRequest
from app.services.approvals import persist_pending_approval
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext
from app.tools.purchase_orders import PurchaseOrderCreateInput


def _approval_interrupt(graph_result: dict[str, Any]) -> dict[str, Any] | None:
    for interruption in graph_result.get("__interrupt__", ()):
        value = getattr(interruption, "value", None)
        if isinstance(value, dict) and value.get("tool") == "purchase_order_create":
            return value
    return None


async def create_purchase_order_approval(
    session: AsyncSession,
    *,
    current_user: User,
    graph: Any,
    payload: DirectPurchaseOrderRequest,
) -> ApprovalRequest:
    """Authorize the direct request, then pause the compiled graph before any write."""
    supplied_idempotency_key = payload.idempotency_key
    validated = PurchaseOrderCreateInput(
        sku=payload.sku,
        quantity=payload.quantity,
        supplier=payload.supplier,
        idempotency_key=supplied_idempotency_key or "direct-order-validation",
    )
    args = {"sku": validated.sku, "quantity": validated.quantity, "supplier": validated.supplier}
    if supplied_idempotency_key:
        request_id = f"direct-{hashlib.sha256(supplied_idempotency_key.encode()).hexdigest()[:32]}"
        graph_idempotency_key = f"po-{request_id}"
        existing = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.idempotency_key == graph_idempotency_key)
        )
        if existing is not None:
            if existing.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Idempotency key belongs to another user.")
            if existing.action_args != args:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was already used for different order arguments.")
            if existing.status == "PENDING":
                return existing
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This idempotent order request has already been decided.")

    thread = Thread(owner_user_id=current_user.id, title=f"Direct purchase order for {validated.sku}")
    message = f"Create a purchase order for {validated.sku} quantity {validated.quantity} from {validated.supplier}."
    thread.messages = [{"role": "user", "content": message}]
    session.add(thread)
    await session.flush()
    context = ToolContext(
        authenticated_user_id=current_user.id,
        thread_id=str(thread.id),
        execution_id=request_id if supplied_idempotency_key else "direct-order-request",
    )
    try:
        await authorize_tool(session, context, "order:create")
    except ToolAuthorizationError as exc:
        session.add(
            AuditLog(
                user_id=current_user.id,
                tool="purchase_order_create",
                arguments={**args, "request_source": "direct_api", "thread_id": str(thread.id)},
                outcome="denied",
                thread_id=str(thread.id),
            )
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Purchase order creation is not authorized.") from exc

    if not supplied_idempotency_key:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="idempotency_key is required for authorized direct order requests.",
        )

    request_id = f"direct-{hashlib.sha256(supplied_idempotency_key.encode()).hexdigest()[:32]}"
    validated = PurchaseOrderCreateInput(
        sku=payload.sku,
        quantity=payload.quantity,
        supplier=payload.supplier,
        idempotency_key=supplied_idempotency_key,
    )
    args = {"sku": validated.sku, "quantity": validated.quantity, "supplier": validated.supplier}

    graph_input = {
        "thread_id": str(thread.id),
        "user_id": current_user.id,
        "request_id": request_id,
        "messages": list(thread.messages),
        "intent": "action",
        "response": "",
        "citations": [],
        "user_question": "",
        "retrieved_policy_chunks": [],
        "citation_metadata": [],
        "grounded_answer": "",
        "retrieval_status": "unknown",
        "action_request": {"kind": "direct_api", "status": "pending_authorization", "tool_name": "purchase_order_create"},
        "approval_request": None,
        "error": None,
        "workflow": {
            "sku": validated.sku,
            "requested_quantity": None,
            "needs_inventory": False,
            "wants_order": True,
            "wants_email": False,
            "shortfall": 0,
            "explicit_order": args,
            "request_id": request_id,
            "requires_order_before_email": False,
        },
        "inventory_result": None,
        "order_result": None,
        "email_result": None,
        "model_plan": None,
        "direct_order": True,
    }
    config = {"configurable": {"thread_id": str(thread.id), "user_id": current_user.id}}
    graph_result = await graph.ainvoke(graph_input, config=config)
    interrupted = _approval_interrupt(graph_result)
    if interrupted is None:
        if graph_result.get("error") == "order_create_denied":
            session.add(
                AuditLog(
                    user_id=current_user.id,
                    tool="purchase_order_create",
                    arguments={**args, "request_source": "direct_api", "thread_id": str(thread.id)},
                    outcome="denied",
                    thread_id=str(thread.id),
                )
            )
            await session.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Purchase order creation is not authorized.")
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not establish the purchase-order approval gate.")

    approval = await persist_pending_approval(
        session,
        user_id=current_user.id,
        thread_id=str(thread.id),
        tool_name="purchase_order_create",
        action_args=interrupted.get("action_args") or args,
        idempotency_key=str(interrupted["idempotency_key"]),
    )
    thread.messages = [
        *thread.messages,
        {"role": "assistant", "content": str(interrupted.get("description") or "Approval is required before the order can run.")},
    ]
    await session.commit()
    return approval
