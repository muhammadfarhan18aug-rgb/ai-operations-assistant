"""Trusted backend-only execution context for operational tools."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class ToolContext:
    """Execution context created by the authenticated backend. The client does not supply it."""

    authenticated_user_id: int
    thread_id: str | None = None
    execution_id: str | None = None

    def __post_init__(self) -> None:
        if self.execution_id is None:
            object.__setattr__(self, "execution_id", uuid4().hex)
