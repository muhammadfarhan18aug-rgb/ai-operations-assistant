from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from langgraph.types import Command
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
    idempotency_key: str | None = None,
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

    if idempotency_key:
        existing = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

    approval = ApprovalRequest(
        user_id=user_id,
        thread_id=thread_id,
        tool_name=tool_name,
        action_args=_sanitize_action_args(action_args),
        status="PENDING",
        idempotency_key=idempotency_key or f"approval-{tool_name}-{uuid4().hex}",
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


async def resume_approval_request(
    session: AsyncSession,
    *,
    current_user: User,
    graph: Any,
    approval_id: int,
    decision: str,
    reason: str | None = None,
    action_args: dict[str, Any] | None = None,
) -> ApprovalRequest:
    approval = await get_owned_approval(session, user_id=current_user.id, approval_id=approval_id)
    if approval.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending and cannot be executed.")
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported approval decision.")

    if approval.expires_at and approval.expires_at <= datetime.now(timezone.utc):
        approval.status = "EXPIRED"
        approval.updated_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval request has expired.")

    edited_args = _sanitize_action_args(action_args) if action_args is not None else approval.action_args
    if decision == "approve":
        _validate_action_args(approval, edited_args)
        approval.action_args = edited_args
    resume_value = {
        "decision": decision,
        "reason": reason or ("Approved by human operator." if decision == "approve" else "Rejected by human operator."),
        "action_args": edited_args,
    }
    config = {"configurable": {"thread_id": str(approval.thread_id), "user_id": current_user.id}}
    try:
        graph_result = await graph.ainvoke(Command(resume=resume_value), config=config)
        interrupted = _interrupt_payload(graph_result)
        if interrupted and interrupted.get("tool") == approval.tool_name:
            approval.action_args = _sanitize_action_args(interrupted.get("action_args"))
            approval.status = "PENDING"
            approval.result = {"validation_error": interrupted.get("validation_error")}
            approval.updated_at = datetime.now(timezone.utc)
            await _append_assistant_message(session, str(approval.thread_id), graph_result)
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(interrupted.get("validation_error") or "The resumed action failed validation."),
            )

        result_key = "order_result" if approval.tool_name == "purchase_order_create" else "email_result"
        assistant_message = str(graph_result.get("response") or "")
        if decision == "approve":
            execution_result = graph_result.get(result_key)
            approval.status = "EXECUTED" if isinstance(execution_result, dict) else "FAILED"
            approval.result = {**execution_result, "assistant_message": assistant_message} if isinstance(execution_result, dict) else {
                "assistant_message": assistant_message,
                "error": graph_result.get("error") or "The action did not complete.",
            }
        else:
            approval.status = "REJECTED"
            approval.result = {"assistant_message": assistant_message}
        approval.updated_at = datetime.now(timezone.utc)
        approval.decision_made_by = current_user.id
        approval.decision_made_at = approval.decision_made_at or datetime.now(timezone.utc)
        approval.decision_reason = resume_value["reason"]
        await _persist_followup_interrupt(session, graph_result, current_user, str(approval.thread_id))
        await _append_assistant_message(session, str(approval.thread_id), graph_result)
        await session.commit()
        return approval
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_action_args(approval: ApprovalRequest, action_args: dict[str, Any]) -> None:
    try:
        if approval.tool_name == "purchase_order_create":
            from app.tools.purchase_orders import PurchaseOrderCreateInput

            PurchaseOrderCreateInput(**action_args, idempotency_key=approval.idempotency_key)
        elif approval.tool_name == "email_send":
            from app.tools.email import EmailSendInput

            EmailSendInput(**action_args, idempotency_key=approval.idempotency_key)
        else:
            raise ValueError("Approval references an unsupported write tool.")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _interrupt_payload(graph_result: dict[str, Any]) -> dict[str, Any] | None:
    for interruption in graph_result.get("__interrupt__", ()):
        value = getattr(interruption, "value", None)
        if isinstance(value, dict) and value.get("tool"):
            return value
    return None


async def _persist_followup_interrupt(
    session: AsyncSession,
    graph_result: dict[str, Any],
    current_user: User,
    thread_id: str,
) -> None:
    interrupted = _interrupt_payload(graph_result)
    if interrupted is None:
        return
    await persist_pending_approval(
        session,
        user_id=current_user.id,
        thread_id=thread_id,
        tool_name=str(interrupted["tool"]),
        action_args=interrupted.get("action_args") or {},
        idempotency_key=str(interrupted.get("idempotency_key") or "") or None,
    )


async def _append_assistant_message(
    session: AsyncSession,
    thread_id: str,
    graph_result: dict[str, Any],
) -> None:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        return
    interrupted = _interrupt_payload(graph_result)
    response = str(graph_result.get("response") or "")
    if interrupted:
        response = str(interrupted.get("description") or "Approval is required before this action can run.")
    if response:
        thread.messages = [
            *(thread.messages or []),
            {"role": "assistant", "content": response, "citations": []},
        ]
