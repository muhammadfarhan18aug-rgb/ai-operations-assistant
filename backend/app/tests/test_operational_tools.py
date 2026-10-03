from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.order import Order
from app.models.product import Product
from app.models.thread import Thread
from app.models.user import User
from app.models.user_capability import UserCapability
from app.seed.seed import seed_demo_users
from app.tools.authorization import ToolAuthorizationError, authorize_tool
from app.tools.context import ToolContext
from app.tools.email import send_email
from app.tools.inventory import lookup_inventory
from app.tools.policy import lookup_policy
from app.tools.purchase_orders import create_purchase_order
from app.tools.registry import get_registered_tool_names, resolve_tool


@pytest.fixture(autouse=True)
def configure_demo_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "this_is_a_very_long_test_secret_key_1234567890")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "AdminPassword123!")
    monkeypatch.setenv("SEED_OPS_PASSWORD", "OpsPassword123!")
    monkeypatch.setenv("SEED_MANAGER_PASSWORD", "ManagerPassword123!")
    monkeypatch.setenv("SEED_VIEWER_PASSWORD", "ViewerPassword123!")
    yield


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as db_session:
        yield db_session
    await engine.dispose()


async def _create_thread(session, owner_user_id: int, title: str = "Test thread") -> Thread:
    thread = Thread(owner_user_id=owner_user_id, title=title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


async def _create_product(session, sku: str, quantity_on_hand: int = 20, unit_price: Decimal = Decimal("10.99")) -> Product:
    product = Product(
        sku=sku,
        name="Widget",
        quantity_on_hand=quantity_on_hand,
        unit_price=unit_price,
        supplier="Acme Supplies",
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def _get_user_by_email(session, email: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_inventory_lookup_requires_capability(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await lookup_inventory(session, ctx, sku="SKU-001")


@pytest.mark.asyncio
async def test_inventory_lookup_with_capability_returns_product(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    sku = f"SKU-READ-{uuid.uuid4().hex[:8]}"
    await _create_product(session, sku, quantity_on_hand=7, unit_price=Decimal("12.50"))
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    result = await lookup_inventory(session, ctx, sku=sku)
    assert result["sku"] == sku
    assert result["quantity_on_hand"] == 7


@pytest.mark.asyncio
async def test_purchase_order_requires_authorization_and_does_not_create_order(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    sku = f"SKU-PO-FAIL-{uuid.uuid4().hex[:8]}"
    await _create_product(session, sku, quantity_on_hand=10, unit_price=Decimal("9.00"))
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await create_purchase_order(
            session,
            ctx,
            sku=sku,
            quantity=2,
            supplier="Acme Supplies",
            idempotency_key="po-fail-key-1",
        )

    order_count = await session.execute(select(Order).where(Order.idempotency_key == "po-fail-key-1"))
    assert order_count.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purchase_order_is_idempotent_for_same_key(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "manager@cellutech.com")
    thread = await _create_thread(session, user.id)
    sku = f"SKU-PO-IDEM-{uuid.uuid4().hex[:8]}"
    await _create_product(session, sku, quantity_on_hand=25, unit_price=Decimal("18.00"))
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    first = await create_purchase_order(
        session,
        ctx,
        sku=sku,
        quantity=3,
        supplier="Acme Supplies",
        idempotency_key="idem-key-123",
    )
    second = await create_purchase_order(
        session,
        ctx,
        sku=sku,
        quantity=3,
        supplier="Acme Supplies",
        idempotency_key="idem-key-123",
    )

    assert first["idempotency_key"] == "idem-key-123"
    assert second["idempotency_key"] == "idem-key-123"
    assert first["order_reference"] == second["order_reference"]
    count = await session.execute(select(Order).where(Order.idempotency_key == "idem-key-123"))
    assert count.scalar_one().idempotency_key == "idem-key-123"


@pytest.mark.asyncio
async def test_email_requires_capability_and_does_not_send(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await send_email(
            session,
            ctx,
            recipient="ops@cellutech.com",
            subject="Test",
            body="hello",
            idempotency_key="email-key-1",
        )


@pytest.mark.asyncio
async def test_authorization_ignores_client_supplied_capability_and_admin_fields(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await create_purchase_order(
            session,
            ctx,
            sku=f"SKU-PO-FAIL-CLIENT-{uuid.uuid4().hex[:8]}",
            quantity=1,
            supplier="Acme Supplies",
            idempotency_key="po-fail-client-supplied-1",
            approved=True,
            is_admin=True,
            capabilities=["order:create"],
        )


@pytest.mark.asyncio
async def test_policy_lookup_requires_capability_and_uses_db_documents(session):
    await seed_demo_users()
    unauthorized = User(
        email=f"no-policy-{uuid.uuid4().hex[:8]}@cellutech.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$abcdefghijklmnopqrstuv$abcdefghijklmnopqrstuv",
        is_admin=False,
        is_active=True,
    )
    session.add(unauthorized)
    await session.commit()
    await session.refresh(unauthorized)
    thread = await _create_thread(session, unauthorized.id)
    ctx = ToolContext(authenticated_user_id=unauthorized.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await lookup_policy(session, ctx, title="Procurement policy")

    privileged = await _get_user_by_email(session, "manager@cellutech.com")
    privileged_ctx = ToolContext(authenticated_user_id=privileged.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    result = await lookup_policy(session, privileged_ctx, title="Procurement policy")
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_registry_only_contains_explicit_tool_names():
    names = get_registered_tool_names()
    assert "inventory_lookup" in names
    assert "purchase_order_create" in names
    assert "email_send" in names
    assert "policy_lookup" in names
    assert "not_real_tool" not in names

    with pytest.raises(KeyError):
        resolve_tool("not_real_tool")


@pytest.mark.asyncio
async def test_authorize_tool_checks_database_not_client_claims(session):
    await seed_demo_users()
    user = await _get_user_by_email(session, "viewer@cellutech.com")
    thread = await _create_thread(session, user.id)
    ctx = ToolContext(authenticated_user_id=user.id, thread_id=str(thread.id), execution_id=uuid.uuid4().hex)

    with pytest.raises(ToolAuthorizationError):
        await authorize_tool(session, ctx, "order:create")
