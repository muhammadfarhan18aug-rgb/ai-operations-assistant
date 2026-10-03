from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest
from app.models.thread import Thread
from app.models.user import User
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext
from app.tools.email import send_email
from app.tools.purchase_orders import create_purchase_order

REQUIRES_HUMAN_APPROVAL = {"purchase_order_create", "email_send"}


def requires_human_approval(tool_name: str | None) -> bool:
    """Return whether the backend requires explicit human approval before this tool executes."""
    return bool(tool_name and tool_name in REQUIRES_HUMAN_APPROVAL)


def _sanitize_action_args(raw_args: Any) -> dict[str, Any]:
    if raw_args is None:
        return {}
    if not isinstance(raw_args, dict):
        return {"raw_payload": raw_args}

    sanitized: dict[str, Any] = {}
    for key, value in raw_args.items():
        lowered = str(key).lower()
        if lowered in {"password", "token", "secret", "api_key", "jwt", "authorization"}:
            continue
        sanitized[str(key)] = value
    return sanitized


def _extract_tool_args(tool_name: str, request_text: str) -> dict[str, Any]:
    normalized = request_text.strip()
    if not normalized:
        return {}

    if tool_name == "purchase_order_create":
        sku = _find_value(r"(?i)\b(SKU[-_][A-Za-z0-9_-]+)\b", normalized)
        if not sku:
            sku = _find_value(r"(?i)\b(?:sku|product|item)\b\s*[:=]?\s*([A-Za-z0-9_-]+)", normalized)
        quantity = _find_value(r"(?i)(?:qty|quantity)\s*[:=]?\s*(\d+)", normalized)
        supplier = _find_value(r"(?i)(?:supplier|vendor|from)\s*[:=]?\s*([A-Za-z0-9 .&'-]+)", normalized)
        args: dict[str, Any] = {}
        if sku:
            args["sku"] = sku
        if quantity:
            args["quantity"] = int(quantity)
        if supplier:
            args["supplier"] = supplier.strip().rstrip(".")
        if not args:
            args["prompt"] = normalized
        return args

    if tool_name == "email_send":
        recipient = _find_value(r"(?i)(?:to|recipient|email)\s*[:=]?\s*([A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+)", normalized)
        subject = _find_value(r"(?i)(?:subject)\s*[:=]?\s*([A-Za-z0-9 _.-]+)", normalized)
        body = _find_value(r"(?i)(?:body|message|content)\s*[:=]?\s*(.+)", normalized)
        args = {}
        if recipient:
            args["recipient"] = recipient
        if subject:
            args["subject"] = subject.strip()
        if body:
            args["body"] = body.strip()
        if not args:
            args["prompt"] = normalized
        return args

    return {"prompt": normalized}


def _find_value(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    if match is None:
        return None
    return match.group(1).strip()


async def persist_pending_approval(
    session: AsyncSession,
    *,
    user_id: int,
    thread_id: str | None,
    tool_name: str,
    action_args: dict[str, Any] | None = None,
) -> ApprovalRequest:
    """Create a durable approval record for an action that requires explicit human approval."""
    if not requires_human_approval(tool_name):
        raise ValueError(f"Tool '{tool_name}' does not require human approval.")

    if thread_id is None:
        raise ValueError("Thread ID is required for approval persistence.")

    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise ValueError("Thread not found for approval persistence.")
    if thread.owner_user_id != user_id:
        raise ValueError("Thread does not belong to the authenticated user.")

    approval = ApprovalRequest(
        user_id=user_id,
        thread_id=thread_id,
        tool_name=tool_name,
        action_args=_sanitize_action_args(action_args),
        status="PENDING",
        idempotency_key=f"approval-{tool_name}-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    session.add(approval)
    await session.flush()
    return approval


async def get_owned_approval(session: AsyncSession, *, user_id: int, approval_id: int) -> ApprovalRequest:
    approval = await session.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    if approval.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval does not belong to the authenticated user.")
    return approval


async def list_pending_approvals_for_user(session: AsyncSession, user_id: int) -> list[ApprovalRequest]:
    result = await session.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.user_id == user_id)
        .where(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.created_at.desc())
    )
    return result.scalars().all()


async def reject_approval_request(
    session: AsyncSession,
    *,
    current_user: User,
    approval_id: int,
    reason: str | None = None,
) -> ApprovalRequest:
    approval = await get_owned_approval(session, user_id=current_user.id, approval_id=approval_id)
    if approval.status not in {"PENDING", "APPROVED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval cannot be rejected in its current state.")

    approval.status = "REJECTED"
    approval.decision_made_by = current_user.id
    approval.decision_made_at = datetime.now(timezone.utc)
    approval.decision_reason = reason or "Rejected by human operator."
    approval.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return approval


async def approve_approval_request(
    session: AsyncSession,
    *,
    current_user: User,
    approval_id: int,
    reason: str | None = None,
    action_args: dict[str, Any] | None = None,
) -> ApprovalRequest:
    approval = await get_owned_approval(session, user_id=current_user.id, approval_id=approval_id)
    if approval.status not in {"PENDING", "APPROVED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending and cannot be executed.")

    if approval.expires_at and approval.expires_at <= datetime.now(timezone.utc):
        approval.status = "EXPIRED"
        approval.updated_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval request has expired.")

    if action_args is not None:
        approval.action_args = _sanitize_action_args(action_args)

    if approval.tool_name == "purchase_order_create":
        if "sku" not in approval.action_args or "quantity" not in approval.action_args or "supplier" not in approval.action_args:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Edited order arguments are incomplete.")
        from app.tools.purchase_orders import PurchaseOrderCreateInput

        PurchaseOrderCreateInput(
            sku=str(approval.action_args["sku"]),
            quantity=int(approval.action_args["quantity"]),
            supplier=str(approval.action_args["supplier"]),
            idempotency_key=str(approval.idempotency_key),
        )
    elif approval.tool_name == "email_send":
        if "recipient" not in approval.action_args or "subject" not in approval.action_args or "body" not in approval.action_args:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Edited email arguments are incomplete.")
        from app.tools.email import EmailSendInput

        EmailSendInput(
            recipient=str(approval.action_args["recipient"]),
            subject=str(approval.action_args["subject"]),
            body=str(approval.action_args["body"]),
            idempotency_key=str(approval.idempotency_key),
        )

    if approval.status == "PENDING":
        approval.status = "APPROVED"
        approval.decision_made_by = current_user.id
        approval.decision_made_at = datetime.now(timezone.utc)
        approval.decision_reason = reason or "Approved by human operator."
        approval.updated_at = datetime.now(timezone.utc)
        await session.flush()

    try:
        execution_result = await _execute_approved_action(session, approval)
        approval.status = "EXECUTED"
        approval.result = execution_result
        approval.updated_at = datetime.now(timezone.utc)
        approval.decision_made_by = current_user.id
        approval.decision_made_at = approval.decision_made_at or datetime.now(timezone.utc)
        approval.decision_reason = approval.decision_reason or reason or "Approved by human operator."
        await session.commit()
        return approval
    except Exception as exc:  # pragma: no cover - guarded by tests and runtime exception handling
        approval.status = "FAILED"
        approval.result = {"error": str(exc)}
        approval.updated_at = datetime.now(timezone.utc)
        approval.decision_reason = approval.decision_reason or reason or "Approval failed during execution."
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _execute_approved_action(session: AsyncSession, approval: ApprovalRequest) -> dict[str, Any]:
    if approval.status not in {"PENDING", "APPROVED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not in an executable state.")

    if approval.tool_name == "purchase_order_create":
        if "sku" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted SKU argument for purchase order creation.")
        if "quantity" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted quantity argument for purchase order creation.")
        if "supplier" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted supplier argument for purchase order creation.")

        context = ToolContext(authenticated_user_id=approval.user_id, thread_id=str(approval.thread_id), execution_id=uuid4().hex)
        await authorize_tool(session, context, "order:create")
        return await create_purchase_order(
            session,
            context,
            sku=str(approval.action_args["sku"]),
            quantity=int(approval.action_args["quantity"]),
            supplier=str(approval.action_args["supplier"]),
            idempotency_key=approval.idempotency_key,
        )

    if approval.tool_name == "email_send":
        if "recipient" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted recipient argument for email send.")
        if "subject" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted subject argument for email send.")
        if "body" not in approval.action_args:
            raise ToolAuthorizationError("Approval is missing the persisted body argument for email send.")

        context = ToolContext(authenticated_user_id=approval.user_id, thread_id=str(approval.thread_id), execution_id=uuid4().hex)
        await authorize_tool(session, context, "email:send")
        return await send_email(
            session,
            context,
            recipient=str(approval.action_args["recipient"]),
            subject=str(approval.action_args["subject"]),
            body=str(approval.action_args["body"]),
            idempotency_key=approval.idempotency_key,
        )

    raise ToolAuthorizationError(f"Tool '{approval.tool_name}' does not support required approval execution.")
