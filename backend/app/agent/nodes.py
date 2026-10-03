"""LangGraph node implementations for the protected orchestration skeleton."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.agent.model import ModelProviderError, build_chat_model
from app.agent.state import GraphState
from app.database import get_db_session
from app.models.audit_log import AuditLog
from app.models.user import User
from app.policies.retrieval import retrieve_policy_context
from app.tools.authorization import ToolAuthorizationError, ToolNotFoundError, authorize_tool
from app.tools.context import ToolContext
from app.tools.email import EmailSendInput
from app.tools.purchase_orders import PurchaseOrderCreateInput
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


async def classify_message(state: GraphState) -> GraphState:
    """Use a configured model for structured intent extraction or deterministic fallback."""
    from app.agent.routing import route_message

    if state.get("direct_order"):
        state["intent"] = "action"
        state["model_plan"] = None
        state["error"] = None
        return state

    question = _latest_user_text(state.get("messages", []))
    try:
        model = build_chat_model()
        if model is None:
            state["intent"] = route_message(state)
            state["model_plan"] = None
            state["error"] = None
            return state

        plan = await model.plan_request(question)
    except ModelProviderError:
        state["intent"] = "unknown"
        state["model_plan"] = None
        state["response"] = "The configured model provider is unavailable. No action was run."
        state["error"] = "model_provider_failure"
        return state

    state["intent"] = plan.route
    state["model_plan"] = plan.model_dump()
    state["error"] = None
    return state


def _emit_progress(event: str, **payload: Any) -> None:
    try:
        get_stream_writer()({"event": event, **payload})
    except RuntimeError:
        pass


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
        if result.retrieval_status == "success":
            try:
                model = build_chat_model()
                if model is not None:
                    sources = [
                        {"title": citation["document_title"], "section": str(citation.get("section") or ""), "excerpt": chunk}
                        for citation, chunk in zip(result.citation_metadata, result.retrieved_policy_chunks, strict=False)
                    ]
                    answer_parts: list[str] = []
                    async for delta in model.stream_grounded_answer(question, sources):
                        answer_parts.append(delta)
                        _emit_progress("assistant_delta", content=delta, thread_id=thread_id)
                    if not answer_parts:
                        raise ModelProviderError("The configured model returned an empty answer.")
                    sources_text = ", ".join(dict.fromkeys(state["citations"]))
                    state["grounded_answer"] = f"{''.join(answer_parts)}\n\nSources: {sources_text}"
                    state["response"] = state["grounded_answer"]
            except ModelProviderError:
                state["grounded_answer"] = "The configured model provider could not complete a grounded answer."
                state["response"] = state["grounded_answer"]
                state["error"] = "model_provider_failure"
        break

    return state


def _extract_inventory_sku(request_text: str) -> str | None:
    match = re.search(r"(?i)\b(SKU[-_][A-Za-z0-9_-]+)\b", request_text)
    if match:
        return match.group(1)
    match = re.search(r"(?i)\b(?:sku|product|item)\b\s*[:=]\s*([A-Za-z0-9_-]+)", request_text)
    return match.group(1) if match else None


def plan_actions(state: GraphState) -> GraphState:
    """Build a bounded plan; tool authorization remains independent of model output."""
    request_text = _latest_user_text(state.get("messages", []))
    normalized = request_text.lower()
    model_plan = state.get("model_plan")
    parsed_sku = _extract_inventory_sku(request_text)
    parsed_order = _extract_explicit_order_args(request_text)
    if model_plan:
        sku = str(model_plan.get("sku") or parsed_sku or "") or None
        requested_quantity = model_plan.get("target_quantity") or _requested_stock_quantity(request_text)
        wants_order = bool(model_plan.get("wants_order"))
        wants_email = bool(model_plan.get("wants_email"))
        needs_inventory = bool(model_plan.get("needs_inventory") and sku)
        explicit_order = {
            **parsed_order,
            **({"sku": model_plan["order_sku"]} if model_plan.get("order_sku") else {}),
            **({"quantity": model_plan["order_quantity"]} if model_plan.get("order_quantity") is not None else {}),
            **({"supplier": model_plan["supplier"]} if model_plan.get("supplier") else {}),
        }
    else:
        sku = parsed_sku
        requested_quantity = _requested_stock_quantity(request_text)
        wants_order = any(keyword in normalized for keyword in ("purchase order", "raise an order", "raise a purchase", "shortfall", "reorder", "buy"))
        wants_email = any(keyword in normalized for keyword in ("email", "confirmation", "notify me"))
        needs_inventory = bool(
            sku
            and any(word in normalized for word in ("have", "check", "lookup", "look up", "stock", "inventory", "units"))
        )
        explicit_order = parsed_order
    request_id = state.get("request_id") or uuid4().hex
    state["intent"] = "action"
    state["citations"] = []
    state["action_request"] = {
        "kind": "sequential_action_plan",
        "prompt": request_text,
        "status": "planned",
        "tool_name": "inventory_lookup" if needs_inventory else "purchase_order_create" if wants_order else "email_send" if wants_email else None,
    }
    state["workflow"] = {
        "sku": sku,
        "requested_quantity": requested_quantity,
        "needs_inventory": needs_inventory,
        "wants_order": wants_order,
        "wants_email": wants_email,
        "shortfall": 0,
        "explicit_order": explicit_order,
        "request_id": request_id,
        "requires_order_before_email": wants_order and wants_email,
    }
    state["approval_request"] = None
    state["inventory_result"] = None
    state["order_result"] = None
    state["email_result"] = None
    state["error"] = None
    _emit_progress("routing", route="action", steps=[name for name, enabled in (("inventory", needs_inventory), ("order", wants_order), ("email", wants_email)) if enabled])
    if not needs_inventory and not wants_order and not wants_email:
        state["response"] = "The request did not identify a supported operational action."
        state["error"] = "request_unclassified"
        state["action_request"]["status"] = "unsupported"
    return state


def _requested_stock_quantity(request_text: str) -> int | None:
    match = re.search(r"(?i)\b(\d+)\s+(?:units|items|pieces)\s+of\s+SKU[-_][A-Za-z0-9_-]+", request_text)
    return int(match.group(1)) if match else None


def _extract_explicit_order_args(request_text: str) -> dict[str, Any]:
    sku = _extract_inventory_sku(request_text)
    quantity_match = re.search(r"(?i)(?:qty|quantity)\s*[:=]?\s*(-?\d+)", request_text)
    supplier_match = re.search(r"(?i)(?:supplier|vendor|from)\s*[:=]?\s*([A-Za-z0-9 .&'-]+)", request_text)
    return {
        **({"sku": sku} if sku else {}),
        **({"quantity": int(quantity_match.group(1))} if quantity_match else {}),
        **({"supplier": supplier_match.group(1).strip().rstrip(".")} if supplier_match else {}),
    }


def _context(state: GraphState) -> ToolContext:
    return ToolContext(
        authenticated_user_id=state.get("user_id"),
        thread_id=state.get("thread_id"),
        execution_id=str((state.get("workflow") or {}).get("request_id") or uuid4().hex),
    )


async def inventory_node(state: GraphState) -> GraphState:
    workflow = state.get("workflow") or {}
    sku = workflow.get("sku")
    if not sku:
        state["response"] = "Provide a product SKU to look up inventory."
        state["error"] = "inventory_lookup_missing_sku"
        return state

    _emit_progress("tool_started", tool="inventory_lookup", arguments={"sku": sku})
    try:
        async for session in get_db_session():
            result = await resolve_tool("inventory_lookup")(session, _context(state), sku=sku)
            break
    except ToolAuthorizationError:
        state["response"] = "Inventory lookup is not authorized or the requested product was not found."
        state["error"] = "inventory_lookup_denied"
        state["action_request"] = {**(state.get("action_request") or {}), "status": "denied"}
        return state

    workflow["shortfall"] = max(0, int(workflow.get("requested_quantity") or 0) - int(result["quantity_on_hand"]))
    state["workflow"] = workflow
    state["inventory_result"] = result
    state["action_request"] = {**(state.get("action_request") or {}), "status": "executed", "result": result}
    state["response"] = f"Inventory for {result['sku']}: {result['quantity_on_hand']} units on hand."
    state["error"] = None
    _emit_progress("tool_result", tool="inventory_lookup", result=result)
    return state


async def _preauthorize(state: GraphState, capability: str) -> None:
    async for session in get_db_session():
        await authorize_tool(session, _context(state), capability)
        break


async def _record_audit(state: GraphState, tool: str, args: dict[str, Any], outcome: str) -> None:
    async for session in get_db_session():
        session.add(AuditLog(
            user_id=int(state["user_id"]),
            tool=tool,
            arguments={**args, "thread_id": state["thread_id"]},
            outcome=outcome,
            thread_id=str(state["thread_id"]),
        ))
        await session.commit()
        break


async def order_approval_node(state: GraphState) -> GraphState:
    workflow = state.get("workflow") or {}
    inventory = state.get("inventory_result") or {}
    explicit = workflow.get("explicit_order") or {}
    quantity = int(workflow.get("shortfall") or explicit.get("quantity") or 0)
    args = {
        "sku": str(explicit.get("sku") or inventory.get("sku") or workflow.get("sku") or ""),
        "quantity": quantity,
        "supplier": str(explicit.get("supplier") or inventory.get("supplier") or ""),
    }
    key = f"po-{workflow.get('request_id')}"
    try:
        await _preauthorize(state, "order:create")
        validated = PurchaseOrderCreateInput(**args, idempotency_key=key)
    except ToolAuthorizationError:
        state["response"] = "Purchase order creation is not authorized for this account."
        state["error"] = "order_create_denied"
        state["action_request"] = {**(state.get("action_request") or {}), "status": "denied"}
        return state
    except Exception as exc:
        state["response"] = f"The purchase order draft is invalid: {exc}"
        state["error"] = "order_draft_invalid"
        return state

    draft = {"sku": validated.sku, "quantity": validated.quantity, "supplier": validated.supplier}
    state["approval_request"] = {"required": True, "tool_name": "purchase_order_create", "status": "pending", "action_args": draft}
    decision_payload = {
        "tool": "purchase_order_create",
        "action_args": draft,
        "idempotency_key": key,
        "description": f"Create a purchase order for {validated.quantity} units of {validated.sku} from {validated.supplier}.",
    }
    decision = interrupt(decision_payload)
    while True:
        if not isinstance(decision, dict) or decision.get("decision") != "approve":
            reason = str(decision.get("reason") or "Rejected by human operator.") if isinstance(decision, dict) else "Rejected by human operator."
            rejected_args = decision.get("action_args", draft) if isinstance(decision, dict) else draft
            await _record_audit(state, "purchase_order_create", rejected_args, "rejected")
            state["approval_request"] = {"required": True, "tool_name": "purchase_order_create", "status": "REJECTED", "action_args": rejected_args}
            state["action_request"] = {**(state.get("action_request") or {}), "status": "rejected"}
            state["response"] = f"Purchase order rejected. No order was created. {reason}"
            return state

        edited = decision.get("action_args") or draft
        validated = PurchaseOrderCreateInput(**edited, idempotency_key=key)
        _emit_progress("tool_started", tool="purchase_order_create", arguments=edited)
        try:
            async for session in get_db_session():
                result = await resolve_tool("purchase_order_create")(
                    session,
                    _context(state),
                    sku=validated.sku,
                    quantity=validated.quantity,
                    supplier=validated.supplier,
                    idempotency_key=key,
                )
                break
        except ToolNotFoundError as exc:
            message = f"The purchase order could not be created: {exc} Correct the SKU and submit the approval again."
            decision_payload = {
                "tool": "purchase_order_create",
                "action_args": {"sku": validated.sku, "quantity": validated.quantity, "supplier": validated.supplier},
                "idempotency_key": key,
                "validation_error": str(exc),
                "description": message,
            }
            state["approval_request"] = {
                "required": True,
                "tool_name": "purchase_order_create",
                "status": "pending",
                "action_args": decision_payload["action_args"],
            }
            state["response"] = message
            state["error"] = "order_product_not_found"
            _emit_progress("tool_result", tool="purchase_order_create", result={"error": str(exc)})
            decision = interrupt(decision_payload)
            continue
        except ToolAuthorizationError:
            state["response"] = "Purchase order creation is no longer authorized for this account."
            state["error"] = "order_create_denied"
            state["action_request"] = {**(state.get("action_request") or {}), "status": "denied"}
            return state
        break

    state["order_result"] = result
    state["approval_request"] = {"required": True, "tool_name": "purchase_order_create", "status": "EXECUTED", "action_args": edited}
    state["action_request"] = {**(state.get("action_request") or {}), "status": "executed", "result": result}
    state["response"] = f"Purchase order {result['order_reference']} was created for {result['quantity']} units of {result['sku']}."
    state["error"] = None
    _emit_progress("tool_result", tool="purchase_order_create", result=result)
    return state


async def email_approval_node(state: GraphState) -> GraphState:
    workflow = state.get("workflow") or {}
    order = state.get("order_result") or {}
    recipient_match = re.search(r"(?i)\b(?:to|email)\s+([A-Z0-9_.+-]+@[A-Z0-9.-]+)", _latest_user_text(state.get("messages", [])))
    recipient = recipient_match.group(1) if recipient_match else None
    if recipient is None:
        async for session in get_db_session():
            user = await session.get(User, state.get("user_id"))
            recipient = user.email if user else ""
            break
    order_reference = str(order.get("order_reference") or "")
    subject = f"Purchase order confirmation: {order_reference}" if order_reference else "Operations confirmation"
    body = f"Purchase order {order_reference} was created for {order.get('quantity')} units of {order.get('sku')}." if order_reference else "Your requested operation is complete."
    args = {"recipient": recipient, "subject": subject, "body": body}
    key = f"email-{workflow.get('request_id')}"
    try:
        await _preauthorize(state, "email:send")
        validated = EmailSendInput(**args, idempotency_key=key)
    except ToolAuthorizationError:
        state["response"] = "The purchase order was created, but email confirmation was not sent because this account lacks email permission."
        state["error"] = "email_send_denied"
        state["action_request"] = {**(state.get("action_request") or {}), "status": "email_denied"}
        return state
    except Exception as exc:
        state["response"] = f"The email draft is invalid: {exc}"
        state["error"] = "email_draft_invalid"
        return state

    draft = {"recipient": str(validated.recipient), "subject": validated.subject, "body": validated.body}
    state["approval_request"] = {"required": True, "tool_name": "email_send", "status": "pending", "action_args": draft}
    decision = interrupt({
        "tool": "email_send",
        "action_args": draft,
        "idempotency_key": key,
        "description": f"Send the purchase order confirmation to {validated.recipient}.",
    })
    if not isinstance(decision, dict) or decision.get("decision") != "approve":
        reason = str(decision.get("reason") or "Rejected by human operator.") if isinstance(decision, dict) else "Rejected by human operator."
        await _record_audit(state, "email_send", draft, "rejected")
        state["approval_request"] = {"required": True, "tool_name": "email_send", "status": "REJECTED", "action_args": draft}
        state["response"] = f"Email rejected. No email was sent. {reason}"
        return state

    edited = decision.get("action_args") or draft
    validated = EmailSendInput(**edited, idempotency_key=key)
    _emit_progress("tool_started", tool="email_send", arguments=draft)
    async for session in get_db_session():
        result = await resolve_tool("email_send")(
            session,
            _context(state),
            recipient=str(validated.recipient),
            subject=validated.subject,
            body=validated.body,
            idempotency_key=key,
        )
        break
    state["email_result"] = result
    state["approval_request"] = {"required": True, "tool_name": "email_send", "status": "EXECUTED", "action_args": edited}
    state["response"] = f"Email confirmation was sent to {result['recipient']}."
    state["error"] = None
    _emit_progress("tool_result", tool="email_send", result=result)
    return state


def unknown_node(state: GraphState) -> GraphState:
    """Fallback route used when the request cannot be safely classified."""
    state["intent"] = "unknown"
    if state.get("error") != "model_provider_failure":
        state["response"] = (
            "The request could not be safely classified. Please rephrase it as a question or an explicit action."
        )
        state["error"] = "request_unclassified"
    state["citations"] = []
    state["action_request"] = None
    state["approval_request"] = None
    return state
