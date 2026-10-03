"""Chat API routes for the LangGraph orchestration foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db_session
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import process_chat_message

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def create_chat_message(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    """Send a user message through the orchestration graph for the authenticated user."""
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id must match the authenticated user.")

    return await process_chat_message(
        session=session,
        current_user=current_user,
        message=payload.message,
        thread_id=payload.thread_id,
    )
