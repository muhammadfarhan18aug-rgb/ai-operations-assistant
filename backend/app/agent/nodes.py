"""LangGraph node implementations for the protected orchestration skeleton."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.agent.state import GraphState
from app.database import get_db_session
from app.policies.retrieval import retrieve_policy_context
from app.services.approvals import requires_human_approval, _extract_tool_args
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext
from app.tools.registry import resolve_tool


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


async def knowledge_node(state: GraphState) -> GraphState:
    """Knowledge branch that grounds answers in retrieved policy documents only."""
    question = _latest_user_text(state.get("messages", []))
    state["intent"] = "knowledge"
    state["user_question"] = question
    state["retrieved_policy_chunks"] = []
    state["citation_metadata"] = []
    state["grounded_answer"] = ""
    state["retrieval_status"] = "unknown"
    state["citations"] = []
    state["action_request"] = None
    state["approval_request"] = None
    state["error"] = None

    if not question:
        state["retrieval_status"] = "no_question"
        state["grounded_answer"] = "No question was provided for grounded policy retrieval."
        state["response"] = state["grounded_answer"]
        return state

    async for session in get_db_session():
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        if user_id is None:
            state["retrieval_status"] = "unauthorized"
            state["grounded_answer"] = "You are not authorized to read policy documents."
            state["response"] = state["grounded_answer"]
            state["error"] = "policy_read_denied"
            break

        context = ToolContext(
            authenticated_user_id=user_id,
            thread_id=thread_id,
            execution_id=uuid4().hex,
        )
        try:
            await authorize_tool(session, context, "policy:read")
        except ToolAuthorizationError:
            state["retrieval_status"] = "unauthorized"
            state["grounded_answer"] = "You are not authorized to read policy documents."
            state["response"] = state["grounded_answer"]
            state["error"] = "policy_read_denied"
            break

        result = await retrieve_policy_context(session, question, limit=3)
        state["retrieved_policy_chunks"] = result.retrieved_policy_chunks
        state["citation_metadata"] = result.citation_metadata
        state["grounded_answer"] = result.grounded_answer
        state["retrieval_status"] = result.retrieval_status
        state["citations"] = [citation["document_title"] for citation in result.citation_metadata]
        state["response"] = result.grounded_answer
        break

    return state


def _extract_inventory_sku(request_text: str) -> str | None:
    match = re.search(r"(?i)\b(SKU[-_][A-Za-z0-9_-]+)\b", request_text)
    if match:
        return match.group(1)
    match = re.search(r"(?i)\b(?:sku|product|item)\b\s*[:=]\s*([A-Za-z0-9_-]+)", request_text)
    return match.group(1) if match else None


async def action_node(state: GraphState) -> GraphState:
    """Resolve an allowlisted action and execute only authorized read-only lookups."""
    request_text = _latest_user_text(state.get("messages", []))
    normalized = request_text.lower()

    if any(keyword in normalized for keyword in ("purchase", "po", "order", "buy")):
        tool_name = "purchase_order_create"
    elif any(keyword in normalized for keyword in ("email", "send", "notify", "message")):
        tool_name = "email_send"
    elif any(keyword in normalized for keyword in ("inventory", "stock", "sku", "quantity")):
        tool_name = "inventory_lookup"
    elif any(keyword in normalized for keyword in ("policy", "procedure", "compliance", "document")):
        tool_name = "policy_lookup"
    else:
        tool_name = "inventory_lookup"

    state["intent"] = "action"
    state["citations"] = []
    state["action_request"] = {
        "kind": "explicit_tool_selection",
        "prompt": request_text,
        "status": "pending_authorization",
        "tool_name": tool_name,
    }

    if tool_name == "inventory_lookup":
        sku = _extract_inventory_sku(request_text)
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        if not sku or user_id is None or thread_id is None:
            state["action_request"]["status"] = "invalid_request"
            state["response"] = "Provide a product SKU to look up inventory."
            state["error"] = "inventory_lookup_missing_context"
            state["approval_request"] = {
                "required": False,
                "tool_name": tool_name,
                "status": "not_required",
                "action_args": {},
                "reason": "Inventory lookup is read-only.",
            }
            return state

        context = ToolContext(authenticated_user_id=user_id, thread_id=thread_id, execution_id=uuid4().hex)
        try:
            tool = resolve_tool(tool_name)
            async for session in get_db_session():
                result = await tool(session, context, sku=sku)
                break
        except ToolAuthorizationError:
            state["action_request"]["status"] = "denied"
            state["response"] = "Inventory lookup is not authorized or the requested product was not found."
            state["error"] = "inventory_lookup_denied"
            result = None
        else:
            state["action_request"]["status"] = "executed"
            state["action_request"]["result"] = result
            state["response"] = f"Inventory for {result['sku']}: {result['quantity_on_hand']} units on hand."
            state["error"] = None

        state["approval_request"] = {
            "required": False,
            "tool_name": tool_name,
            "status": "not_required",
            "action_args": {"sku": sku},
            "reason": "Inventory lookup is read-only.",
        }
        state["citations"] = []
        return state

    requires_approval = requires_human_approval(tool_name)
    if requires_approval:
        state["response"] = (
            "Human approval is required before the dangerous write action can execute. "
            "The backend is creating a durable approval record for this request."
        )
        state["approval_request"] = {
            "required": True,
            "tool_name": tool_name,
            "status": "pending",
            "action_args": _extract_tool_args(tool_name, request_text),
            "reason": "Responsible backend policy requires explicit human approval before a write action executes.",
        }
    else:
        state["response"] = (
            "This request was classified as an operational action, but tool execution remains gated by the "
            "backend authorization boundary in this foundation step."
        )
        state["approval_request"] = {
            "required": False,
            "tool_name": tool_name,
            "status": "not_required",
            "action_args": {},
            "reason": "Read-only tool or policy lookup does not require human approval.",
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
