"""Explicit operational tool registry for secure backend tool dispatch."""

from __future__ import annotations

from collections.abc import Callable

from app.tools.email import send_email
from app.tools.inventory import lookup_inventory
from app.tools.policy import lookup_policy
from app.tools.purchase_orders import create_purchase_order

TOOL_REGISTRY: dict[str, Callable[..., object]] = {
    "inventory_lookup": lookup_inventory,
    "purchase_order_create": create_purchase_order,
    "email_send": send_email,
    "policy_lookup": lookup_policy,
}


def get_registered_tool_names() -> list[str]:
    """Return the statically allowed tool names."""
    return sorted(TOOL_REGISTRY)


def resolve_tool(name: str) -> Callable[..., object]:
    """Return an explicit tool implementation from the allowlist."""
    if name not in TOOL_REGISTRY:
        raise KeyError(f"Unknown tool: {name}")
    return TOOL_REGISTRY[name]
