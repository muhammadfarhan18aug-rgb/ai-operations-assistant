"""Chat API routes for the LangGraph orchestration foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import process_chat_message, stream_chat_message

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def create_chat_message(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ChatResponse | StreamingResponse:
    """Send a user message through the orchestration graph for the authenticated user."""
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id must match the authenticated user.")

    accept_header = request.headers.get("accept", "")
    if payload.stream or "text/event-stream" in accept_header.lower():
        return StreamingResponse(
            stream_chat_message(
                session=session,
                current_user=current_user,
                message=payload.message,
                graph=request.app.state.graph,
                thread_id=payload.thread_id,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await process_chat_message(
        session=session,
        current_user=current_user,
        message=payload.message,
        graph=request.app.state.graph,
        thread_id=payload.thread_id,
    )


@router.post("/stream")
async def stream_chat_message_route(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Stream backend status and final response events for the authenticated user."""
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id must match the authenticated user.")

    return StreamingResponse(
        stream_chat_message(
            session=session,
            current_user=current_user,
            message=payload.message,
            graph=request.app.state.graph,
            thread_id=payload.thread_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
