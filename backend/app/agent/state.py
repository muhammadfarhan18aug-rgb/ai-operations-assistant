"""Typed state definitions for the LangGraph orchestration foundation."""

from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict):
    """State carried through the orchestration graph."""

    thread_id: str | None
    user_id: int | None
    messages: list[dict[str, Any]]
    intent: str
    response: str
    citations: list[str]
    user_question: str
    retrieved_policy_chunks: list[str]
    citation_metadata: list[dict[str, Any]]
    grounded_answer: str
    retrieval_status: str
    action_request: dict[str, Any] | None
    approval_request: dict[str, Any] | None
    error: str | None
