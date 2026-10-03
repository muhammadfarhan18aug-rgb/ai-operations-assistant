from __future__ import annotations

from app.agent.graph import build_graph
from app.agent.routing import route_message


def test_route_message_classifies_action_request() -> None:
    state = {
        "thread_id": "thread-123",
        "user_id": 42,
        "messages": [{"role": "user", "content": "Create a purchase order for three laptops."}],
        "intent": "",
        "response": "",
        "citations": [],
        "action_request": None,
        "approval_request": None,
        "error": None,
    }
    assert route_message(state) == "action"


def test_route_message_classifies_knowledge_request() -> None:
    state = {
        "thread_id": "thread-124",
        "user_id": 42,
        "messages": [{"role": "user", "content": "What is the current inventory for SKU-1001?"}],
        "intent": "",
        "response": "",
        "citations": [],
        "action_request": None,
        "approval_request": None,
        "error": None,
    }
    assert route_message(state) == "knowledge"


def test_build_graph_compiles() -> None:
    graph = build_graph()
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "get_state")
