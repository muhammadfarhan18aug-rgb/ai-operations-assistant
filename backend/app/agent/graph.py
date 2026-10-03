"""State graph assembly for the AI Operations Assistant orchestration foundation."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph

from app.agent.nodes import (
    classify_message,
    email_approval_node,
    inventory_node,
    knowledge_node,
    order_approval_node,
    plan_actions,
    unknown_node,
)
from app.agent.state import GraphState


def build_graph(checkpointer: AsyncPostgresSaver):
    """Assemble the graph with the required durable PostgreSQL checkpointer."""
    builder = StateGraph(GraphState)
    builder.add_node("classify_message", classify_message)
    builder.add_node("knowledge", knowledge_node)
    builder.add_node("plan_actions", plan_actions)
    builder.add_node("inventory", inventory_node)
    builder.add_node("order_approval", order_approval_node)
    builder.add_node("email_approval", email_approval_node)
    builder.add_node("unknown", unknown_node)

    builder.set_entry_point("classify_message")
    builder.add_conditional_edges(
        "classify_message",
        lambda state: state.get("intent") if state.get("intent") in {"knowledge", "action", "unknown"} else "unknown",
        {
            "knowledge": "knowledge",
            "action": "plan_actions",
            "unknown": "unknown",
        },
    )
    builder.add_conditional_edges(
        "plan_actions",
        lambda state: "inventory" if state.get("workflow", {}).get("needs_inventory") else _next_action(state),
        {"inventory": "inventory", "order": "order_approval", "email": "email_approval", "end": "__end__"},
    )
    builder.add_conditional_edges(
        "inventory",
        lambda state: _next_after_inventory(state),
        {"order": "order_approval", "email": "email_approval", "end": "__end__"},
    )
    builder.add_conditional_edges(
        "order_approval",
        lambda state: "email" if state.get("order_result") and state.get("workflow", {}).get("wants_email") else "end",
        {"email": "email_approval", "end": "__end__"},
    )
    builder.add_edge("knowledge", "__end__")
    builder.add_edge("email_approval", "__end__")
    builder.add_edge("unknown", "__end__")

    return builder.compile(checkpointer=checkpointer)


def _next_action(state: GraphState) -> str:
    workflow = state.get("workflow") or {}
    if workflow.get("wants_order"):
        return "order"
    if workflow.get("wants_email"):
        return "email"
    return "end"


def _next_after_inventory(state: GraphState) -> str:
    workflow = state.get("workflow") or {}
    if workflow.get("wants_order") and int(workflow.get("shortfall") or 0) > 0:
        return "order"
    if workflow.get("wants_email"):
        return "email"
    return "end"
