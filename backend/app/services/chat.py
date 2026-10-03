"""Service layer for the durable chat and LangGraph orchestration foundation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.models.thread import Thread
from app.models.user import User
from app.schemas.chat import ChatResponse
from app.services.approvals import persist_pending_approval

_GRAPH = build_graph()


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
        "messages": list(thread.messages),
        "intent": "",
        "response": "",
        "citations": [],
        "action_request": None,
        "approval_request": None,
        "error": None,
    }
    return resolved_thread_id, graph_input


async def process_chat_message(
    session: AsyncSession,
    current_user: User,
    message: str,
    thread_id: str | None = None,
) -> ChatResponse:
    """Process a user message through the graph and guard thread ownership."""
    resolved_thread_id, graph_input = await _prepare_chat_state(session, current_user, message, thread_id)

    graph_result = await _GRAPH.ainvoke(
        graph_input,
        config={"configurable": {"thread_id": resolved_thread_id, "user_id": current_user.id}},
    )

    approval_request = graph_result.get("approval_request")
    thread = await session.get(Thread, UUID(resolved_thread_id))
    if thread is not None:
        thread.messages = [
            *(thread.messages or []),
            {
                "role": "assistant",
                "content": str(graph_result.get("response") or "No response generated."),
                "citations": list(graph_result.get("citations") or []),
                "citation_metadata": list(graph_result.get("citation_metadata") or []),
            },
        ]
    if approval_request and approval_request.get("required"):
        tool_name = approval_request.get("tool_name")
        if tool_name:
            approval = await persist_pending_approval(
                session,
                user_id=current_user.id,
                thread_id=resolved_thread_id,
                tool_name=tool_name,
                action_args=approval_request.get("action_args") or {"prompt": message},
            )
            await session.commit()
            approval_request["approval_id"] = approval.id
            approval_request["status"] = approval.status
            graph_result["approval_request"] = approval_request
    else:
        await session.commit()

    return ChatResponse(
        thread_id=str(graph_result.get("thread_id") or resolved_thread_id),
        user_id=current_user.id,
        intent=str(graph_result.get("intent") or "unknown"),
        response=str(graph_result.get("response") or "No response generated."),
        citations=list(graph_result.get("citations") or []),
        citation_metadata=list(graph_result.get("citation_metadata") or []),
        action_request=graph_result.get("action_request"),
        approval_request=graph_result.get("approval_request"),
        error=graph_result.get("error"),
    )


async def stream_chat_message(
    session: AsyncSession,
    current_user: User,
    message: str,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE events and convert pre-final failures to non-sensitive error events."""
    try:
        async for event in _stream_chat_message_events(session, current_user, message, thread_id):
            yield event
    except HTTPException as exc:
        yield _format_sse("error", {"message": str(exc.detail)})
    except Exception:
        yield _format_sse("error", {"message": "The chat request could not be completed."})


async def _stream_chat_message_events(
    session: AsyncSession,
    current_user: User,
    message: str,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield real backend progress updates using server-sent events."""
    resolved_thread_id, graph_input = await _prepare_chat_state(session, current_user, message, thread_id)
    yield _format_sse("status", {"message": "Classifying request", "thread_id": resolved_thread_id})

    graph_result = await _GRAPH.ainvoke(
        graph_input,
        config={"configurable": {"thread_id": resolved_thread_id, "user_id": current_user.id}},
    )

    yield _format_sse("status", {"message": "Completed backend routing", "intent": graph_result.get("intent")})

    approval_request = graph_result.get("approval_request")
    thread = await session.get(Thread, UUID(resolved_thread_id))
    if thread is not None:
        thread.messages = [
            *(thread.messages or []),
            {
                "role": "assistant",
                "content": str(graph_result.get("response") or "No response generated."),
                "citations": list(graph_result.get("citations") or []),
                "citation_metadata": list(graph_result.get("citation_metadata") or []),
            },
        ]
    if approval_request and approval_request.get("required"):
        tool_name = approval_request.get("tool_name")
        if tool_name:
            approval = await persist_pending_approval(
                session,
                user_id=current_user.id,
                thread_id=resolved_thread_id,
                tool_name=tool_name,
                action_args=approval_request.get("action_args") or {"prompt": message},
            )
            await session.commit()
            approval_request["approval_id"] = approval.id
            approval_request["status"] = approval.status
            graph_result["approval_request"] = approval_request
            yield _format_sse("approval", {"approval_id": approval.id, "tool_name": tool_name, "status": approval.status})
    else:
        await session.commit()

    final = ChatResponse(
        thread_id=str(graph_result.get("thread_id") or resolved_thread_id),
        user_id=current_user.id,
        intent=str(graph_result.get("intent") or "unknown"),
        response=str(graph_result.get("response") or "No response generated."),
        citations=list(graph_result.get("citations") or []),
        citation_metadata=list(graph_result.get("citation_metadata") or []),
        action_request=graph_result.get("action_request"),
        approval_request=graph_result.get("approval_request"),
        error=graph_result.get("error"),
    )
    yield _format_sse("final", final.model_dump())


async def get_user_threads(session: AsyncSession, current_user: User) -> list[Thread]:
    """Fetch a user's threads without trusting any client-provided identity."""
    result = await session.execute(select(Thread).where(Thread.owner_user_id == current_user.id).order_by(Thread.created_at.desc()))
    return result.scalars().all()
