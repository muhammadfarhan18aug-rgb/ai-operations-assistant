"""State graph assembly for the AI Operations Assistant orchestration foundation."""

from __future__ import annotations

from langgraph.graph import StateGraph

from app.agent.nodes import action_node, classify_message, knowledge_node, unknown_node
from app.agent.persistence import create_default_checkpointer
from app.agent.routing import route_message
from app.agent.state import GraphState


def build_graph() -> StateGraph:
    """Assemble the graph with deterministic knowledge/action/unknown routing."""
    builder = StateGraph(GraphState)
    builder.add_node("classify_message", classify_message)
    builder.add_node("knowledge", knowledge_node)
    builder.add_node("action", action_node)
    builder.add_node("unknown", unknown_node)

    builder.set_entry_point("classify_message")
    builder.add_conditional_edges(
        "classify_message",
        lambda state: route_message(state),
        {
            "knowledge": "knowledge",
            "action": "action",
            "unknown": "unknown",
        },
    )
    builder.add_edge("knowledge", "__end__")
    builder.add_edge("action", "__end__")
    builder.add_edge("unknown", "__end__")

    checkpointer = create_default_checkpointer()
    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
