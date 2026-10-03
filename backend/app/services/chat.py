"""Service layer for the durable chat and LangGraph orchestration foundation."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.models.thread import Thread
from app.models.user import User
from app.schemas.chat import ChatResponse
from app.services.approvals import persist_pending_approval

_GRAPH = build_graph()


async def process_chat_message(
    session: AsyncSession,
    current_user: User,
    message: str,
    thread_id: str | None = None,
) -> ChatResponse:
    """Process a user message through the graph and guard thread ownership."""
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

    graph_input = {
        "thread_id": resolved_thread_id,
        "user_id": current_user.id,
        "messages": [{"role": "user", "content": message}],
        "intent": "",
        "response": "",
        "citations": [],
        "action_request": None,
        "approval_request": None,
        "error": None,
    }

    graph_result = _GRAPH.invoke(
        graph_input,
        config={"configurable": {"thread_id": resolved_thread_id, "user_id": current_user.id}},
    )

    approval_request = graph_result.get("approval_request")
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

    return ChatResponse(
        thread_id=str(graph_result.get("thread_id") or resolved_thread_id),
        user_id=current_user.id,
        intent=str(graph_result.get("intent") or "unknown"),
        response=str(graph_result.get("response") or "No response generated."),
        citations=list(graph_result.get("citations") or []),
        action_request=graph_result.get("action_request"),
        approval_request=graph_result.get("approval_request"),
        error=graph_result.get("error"),
    )


async def get_user_threads(session: AsyncSession, current_user: User) -> list[Thread]:
    """Fetch a user's threads without trusting any client-provided identity."""
    result = await session.execute(select(Thread).where(Thread.owner_user_id == current_user.id).order_by(Thread.created_at.desc()))
    return result.scalars().all()
