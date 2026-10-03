"""Direct order API that returns a graph-backed approval instead of executing a write."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.schemas.approval import ApprovalSummary
from app.services.orders import create_purchase_order_approval
from app.schemas.orders import DirectPurchaseOrderRequest

router = APIRouter(tags=["orders"])


@router.post("/purchase-orders", response_model=ApprovalSummary, status_code=status.HTTP_202_ACCEPTED)
async def request_purchase_order(
    request: Request,
    payload: DirectPurchaseOrderRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalSummary:
    """Submit a direct purchase-order request and pause for human approval."""
    approval = await create_purchase_order_approval(
        session,
        current_user=current_user,
        graph=request.app.state.graph,
        payload=payload,
    )
    return ApprovalSummary(
        id=approval.id,
        user_id=approval.user_id,
        thread_id=str(approval.thread_id),
        tool_name=approval.tool_name,
        action_args=approval.action_args,
        status=approval.status,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
        decision_made_by=approval.decision_made_by,
        decision_made_at=approval.decision_made_at,
        decision_reason=approval.decision_reason,
        result=approval.result,
        expires_at=approval.expires_at,
    )