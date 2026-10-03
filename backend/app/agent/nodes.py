"""LangGraph node implementations for the protected orchestration skeleton."""

from __future__ import annotations

from typing import Any

from app.agent.state import GraphState


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).lower()
        content = str(message.get("content", ""))
        if role == "user" and content.strip():
            return content.strip()
    return ""


def classify_message(state: GraphState) -> GraphState:
    """Add the deterministic route classification into the state."""
    from app.agent.routing import route_message

    route = route_message(state)
    state["intent"] = route
    return state


def knowledge_node(state: GraphState) -> GraphState:
    """Knowledge branch placeholder for future in-context reasoning."""
    state["intent"] = "knowledge"
    state["response"] = (
        "Knowledge requests are routed to the future retrieval and reasoning layer; "
        "this foundation only enforces the branch boundary and safe state handling."
    )
    state["citations"] = []
    state["action_request"] = None
    state["approval_request"] = None
    state["error"] = None
    return state


def action_node(state: GraphState) -> GraphState:
    """Action branch placeholder that never executes live operations."""
    request_text = _latest_user_text(state.get("messages", []))
    state["intent"] = "action"
    state["response"] = (
        "This request was classified as an operational action, but the operational action layer "
        "is intentionally not implemented in this foundation step."
    )
    state["citations"] = []
    state["action_request"] = {
        "kind": "pending_authorization",
        "prompt": request_text,
        "status": "blocked",
    }
    state["approval_request"] = {
        "required": True,
        "reason": "Future tool execution is intentionally withheld in this foundation step.",
    }
    state["error"] = None
    return state


def unknown_node(state: GraphState) -> GraphState:
    """Fallback route used when the request cannot be safely classified."""
    state["intent"] = "unknown"
    state["response"] = (
        "The request could not be safely classified. Please rephrase it as a question or an explicit action."
    )
    state["citations"] = []
    state["action_request"] = None
    state["approval_request"] = None
    state["error"] = "request_unclassified"
    return state
