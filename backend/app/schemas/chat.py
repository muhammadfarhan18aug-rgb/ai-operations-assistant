"""Request and response schemas for the chat orchestration foundation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Chat submission for the AI orchestration foundation."""

    message: str = Field(..., min_length=1, max_length=4000)
    thread_id: str | None = None
    user_id: int | None = Field(default=None, exclude=True)
    stream: bool = Field(default=False, description="When true, the backend streams status events before the final response.")


class ChatResponse(BaseModel):
    """Chat response payload returned by the orchestration layer."""

    model_config = ConfigDict(from_attributes=True)

    thread_id: str
    user_id: int
    intent: str
    response: str
    citations: list[str] = []
    citation_metadata: list[dict[str, Any]] = Field(default_factory=list)
    action_request: dict[str, Any] | None = None
    approval_request: dict[str, Any] | None = None
    error: str | None = None
