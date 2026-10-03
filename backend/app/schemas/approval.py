from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApprovalDecisionRequest(BaseModel):
    """Human decision payload for an approval record."""

    reason: str | None = Field(default=None, max_length=255)
    action_args: dict[str, Any] | None = None


class ApprovalSummary(BaseModel):
    """Approval summary used by the API."""

    id: int
    user_id: int
    thread_id: str
    tool_name: str
    action_args: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    decision_made_by: int | None = None
    decision_made_at: datetime | None = None
    decision_reason: str | None = None
    result: dict[str, Any] | None = None
    expires_at: datetime | None = None
