"""Service layer for the durable chat and LangGraph orchestration foundation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import Thread
from app.models.user import User
from app.schemas.chat import ChatResponse
from app.services.approvals import persist_pending_approval

def _format_sse(event: str, payload: dict[str, object]) -> str:
    """Format a single server-sent event payload."""
    serialized = json.dumps(payload, default=str)
    return f"event: {event}\ndata: {serialized}\n\n"


async def _prepare_chat_state(
    session: AsyncSession,
    current_user: User,
    message: str,
    thread_id: str | None = None,
) -> tuple[str, dict[str, object]]:
    """Resolve thread ownership and construct the deterministic graph input."""
    if not message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty.")

    resolved_thread_id = thread_id
    thread = None
    if resolved_thread_id:
        try:
            thread_uuid = UUID(str(resolved_thread_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thread ID is invalid.") from exc

        thread = await session.get(Thread, thread_uuid)
        if thread is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")
        if thread.owner_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Thread does not belong to the authenticated user.")
    else:
        thread = Thread(owner_user_id=current_user.id, title=message[:80])
        session.add(thread)
        await session.flush()
        resolved_thread_id = str(thread.id)

    thread.messages = [*(thread.messages or []), {"role": "user", "content": message}]
    await session.commit()

    graph_input = {
        "thread_id": resolved_thread_id,
        "user_id": current_user.id,
        "request_id": uuid4().hex,
        "messages": list(thread.messages),
        "intent": "",
        "response": "",
        "citations": [],
        "action_request": None,
        "approval_request": None,
        "error": None,
        "workflow": None,
        "inventory_result": None,
        "order_result": None,
        "email_result": None,
        "user_question": "",
        "retrieved_policy_chunks": [],
        "citation_metadata": [],
        "grounded_answer": "",
        "retrieval_status": "unknown",
        "model_plan": None,
        "direct_order": False,
    }
    return resolved_thread_id, graph_input


async def process_chat_message(
    session: AsyncSession,
    current_user: User,
    message: str,
    graph: Any,
    thread_id: str | None = None,
) -> ChatResponse:
    """Process a user message through the graph and guard thread ownership."""
    resolved_thread_id, graph_input = await _prepare_chat_state(session, current_user, message, thread_id)

    graph_result = await graph.ainvoke(
        graph_input,
        config={"configurable": {"thread_id": resolved_thread_id, "user_id": current_user.id}},
    )
    return await _finalize_chat_result(session, current_user, resolved_thread_id, graph_result)


def _interrupt_payload(graph_result: dict[str, Any]) -> dict[str, Any] | None:
    interruptions = graph_result.get("__interrupt__", ())
    for interruption in interruptions:
        value = getattr(interruption, "value", None)
        if isinstance(value, dict) and value.get("tool"):
            return value
    return None


async def _finalize_chat_result(
    session: AsyncSession,
    current_user: User,
    resolved_thread_id: str,
    graph_result: dict[str, Any],
) -> ChatResponse:
    interrupted = _interrupt_payload(graph_result)
    approval_request = graph_result.get("approval_request")
    response_text = str(graph_result.get("response") or "No response generated.")
    if interrupted:
        approval_request = {
            "required": True,
            "tool_name": interrupted["tool"],
            "status": "PENDING",
            "action_args": interrupted.get("action_args") or {},
        }
        response_text = str(interrupted.get("description") or "Approval is required before this action can run.")
        approval = await persist_pending_approval(
            session,
            user_id=current_user.id,
            thread_id=resolved_thread_id,
            tool_name=str(interrupted["tool"]),
            action_args=interrupted.get("action_args") or {},
            idempotency_key=str(interrupted.get("idempotency_key") or "") or None,
        )
        approval_request["approval_id"] = approval.id
        approval_request["status"] = approval.status

    thread = await session.get(Thread, UUID(resolved_thread_id))
    if thread is not None:
        thread.messages = [
            *(thread.messages or []),
            {
                "role": "assistant",
                "content": response_text,
                "citations": list(graph_result.get("citations") or []),
                "citation_metadata": list(graph_result.get("citation_metadata") or []),
            },
        ]
    await session.commit()

    return ChatResponse(
        thread_id=str(graph_result.get("thread_id") or resolved_thread_id),
        user_id=current_user.id,
        intent=str(graph_result.get("intent") or "unknown"),
        response=response_text,
        citations=list(graph_result.get("citations") or []),
        citation_metadata=list(graph_result.get("citation_metadata") or []),
        action_request=graph_result.get("action_request"),
        approval_request=approval_request,
        error=graph_result.get("error"),
    )


async def stream_chat_message(
    session: AsyncSession,
    current_user: User,
    message: str,
    graph: Any,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE events and convert pre-final failures to non-sensitive error events."""
    try:
        async for event in _stream_chat_message_events(session, current_user, message, graph, thread_id):
            yield event
    except HTTPException as exc:
        yield _format_sse("error", {"message": str(exc.detail)})
    except Exception:
        yield _format_sse("error", {"message": "The chat request could not be completed."})


async def _stream_chat_message_events(
    session: AsyncSession,
    current_user: User,
    message: str,
    graph: Any,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield real backend progress updates using server-sent events."""
    resolved_thread_id, graph_input = await _prepare_chat_state(session, current_user, message, thread_id)
    yield _format_sse("status", {"message": "Classifying request", "thread_id": resolved_thread_id})
    config = {"configurable": {"thread_id": resolved_thread_id, "user_id": current_user.id}}
    graph_result: dict[str, Any] = dict(graph_input)
    async for item in graph.astream(graph_input, config=config, stream_mode=["updates", "custom"]):
        if isinstance(item, tuple) and len(item) == 2:
            stream_mode, chunk = item
        else:
            stream_mode, chunk = "updates", item
        if stream_mode == "custom" and isinstance(chunk, dict):
            event_name = str(chunk.get("event") or "status")
            yield _format_sse(event_name, {key: value for key, value in chunk.items() if key != "event"})
            continue
        if not isinstance(chunk, dict):
            continue
        if "__interrupt__" in chunk:
            graph_result["__interrupt__"] = chunk["__interrupt__"]
            continue
        for node_name, node_update in chunk.items():
            if not isinstance(node_update, dict):
                continue
            if "__interrupt__" in node_update:
                graph_result["__interrupt__"] = node_update["__interrupt__"]
            graph_result.update(node_update)
            yield _format_sse("status", {"message": f"Completed {node_name.replace('_', ' ')}", "node": node_name})

    if not graph_result.get("__interrupt__"):
        snapshot = await graph.aget_state(config)
        for task in snapshot.tasks:
            if task.interrupts:
                graph_result["__interrupt__"] = task.interrupts
                break

    final = await _finalize_chat_result(session, current_user, resolved_thread_id, graph_result)
    if final.error == "model_provider_failure":
        yield _format_sse("error", {"message": final.response})
    if final.approval_request and final.approval_request.get("approval_id"):
        yield _format_sse("approval_required", final.approval_request)
    yield _format_sse("final", final.model_dump())


async def get_user_threads(session: AsyncSession, current_user: User) -> list[Thread]:
    """Fetch a user's threads without trusting any client-provided identity."""
    result = await session.execute(select(Thread).where(Thread.owner_user_id == current_user.id).order_by(Thread.created_at.desc()))
    return result.scalars().all()
