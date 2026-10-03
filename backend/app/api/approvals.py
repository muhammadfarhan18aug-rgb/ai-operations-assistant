from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.approval import ApprovalRequest
from app.models.user import User
from app.schemas.approval import ApprovalDecisionRequest, ApprovalSummary
from app.services.approvals import approve_approval_request, get_owned_approval, list_pending_approvals_for_user, reject_approval_request

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalSummary])
@router.get("/pending", response_model=list[ApprovalSummary])
async def list_pending(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApprovalSummary]:
    approvals = await list_pending_approvals_for_user(session, current_user.id)
    return [
        ApprovalSummary(
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
        for approval in approvals
    ]


@router.get("/{approval_id}", response_model=ApprovalSummary)
async def get_approval(
    approval_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalSummary:
    approval = await get_owned_approval(session, user_id=current_user.id, approval_id=approval_id)
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


@router.post("/{approval_id}/approve", response_model=ApprovalSummary)
async def approve_approval(
    approval_id: int,
    payload: ApprovalDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalSummary:
    approval = await approve_approval_request(
        session,
        current_user=current_user,
        approval_id=approval_id,
        reason=(payload.reason if payload else None),
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


@router.post("/{approval_id}/reject", response_model=ApprovalSummary)
async def reject_approval(
    approval_id: int,
    payload: ApprovalDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalSummary:
    approval = await reject_approval_request(
        session,
        current_user=current_user,
        approval_id=approval_id,
        reason=(payload.reason if payload else None),
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
