"""Deterministic routing for the development-safe LangGraph agent."""

from __future__ import annotations

import re
from typing import Any

from app.agent.state import GraphState


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the most recent user message from the conversation state."""
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).lower()
        content = str(message.get("content", ""))
        if role == "user" and content.strip():
            return content.strip()
    return ""


def route_message(state: GraphState) -> str:
    """Classify the current request into the allowed foundation routes."""
    latest_text = _latest_user_text(state.get("messages", []))
    if not latest_text:
        return "unknown"

    normalized = latest_text.lower()

    if re.search(r"\b(?:inventory|stock|units on hand|quantity on hand)\b", normalized) and re.search(
        r"\bSKU[-_][A-Za-z0-9_-]+\b", latest_text, re.IGNORECASE
    ):
        return "action"

    if re.search(r"\b(?:check|lookup|look up|show)\s+(?:the\s+)?(?:inventory|stock)\b", normalized):
        return "action"

    action_keywords = (
        "create",
        "purchase",
        "buy",
        "submit",
        "send",
        "approve",
        "reject",
        "cancel",
        "email",
        "order",
        "refund",
    )
    knowledge_keywords = (
        "what",
        "why",
        "how",
        "status",
        "current",
        "inventory",
        "policy",
        "document",
        "list",
        "show",
        "summary",
        "details",
    )

    if any(keyword in normalized for keyword in action_keywords):
        return "action"
    if any(keyword in normalized for keyword in knowledge_keywords):
        return "knowledge"
    return "unknown"
