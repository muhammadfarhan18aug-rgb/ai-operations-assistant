from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.order import Order
from app.models.product import Product
from app.models.thread import Thread
from app.models.user import User
from app.seed.seed import seed_demo_users
from app.services.approvals import approve_approval_request, persist_pending_approval, reject_approval_request, requires_human_approval


@pytest.fixture(autouse=True)
def configure_demo_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "this_is_a_very_long_test_secret_key_1234567890")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "AdminPassword123!")
    monkeypatch.setenv("SEED_OPS_PASSWORD", "OpsPassword123!")
    monkeypatch.setenv("SEED_MANAGER_PASSWORD", "ManagerPassword123!")
    monkeypatch.setenv("SEED_VIEWER_PASSWORD", "ViewerPassword123!")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as db_session:
        yield db_session
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _login(async_client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await async_client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _create_user(session, email: str) -> User:
    user = User(email=email, password_hash="hashed_password", is_admin=False, is_active=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_thread(session, owner_id: int, title: str = "Approval thread") -> Thread:
    thread = Thread(owner_user_id=owner_id, title=title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


async def _create_product(session, sku: str, quantity_on_hand: int = 20) -> Product:
    product = Product(
        sku=sku,
        name="Approval Widget",
        quantity_on_hand=quantity_on_hand,
        unit_price=10.99,
        supplier="Acme Supplies",
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@pytest.mark.asyncio
async def test_purchase_order_and_email_require_human_approval():
    assert requires_human_approval("purchase_order_create") is True
    assert requires_human_approval("email_send") is True
    assert requires_human_approval("inventory_lookup") is False
    assert requires_human_approval("policy_lookup") is False


@pytest.mark.asyncio
async def test_pending_approval_can_be_approved_and_executes(session):
    await seed_demo_users()
    user = (await session.execute(__import__('sqlalchemy').select(User).where(User.email == "manager@cellutech.com"))).scalar_one()
    thread = await _create_thread(session, user.id)
    sku = f"SKU-APPROVAL-{uuid.uuid4().hex[:8]}"
    await _create_product(session, sku, quantity_on_hand=25)
    approval = await persist_pending_approval(
        session,
        user_id=user.id,
        thread_id=str(thread.id),
        tool_name="purchase_order_create",
        action_args={"sku": sku, "quantity": 3, "supplier": "Acme Supplies"},
    )
    await session.commit()

    approval = await approve_approval_request(session, current_user=user, approval_id=approval.id)

    assert approval.status == "EXECUTED"
    order = (await session.execute(__import__('sqlalchemy').select(Order).where(Order.idempotency_key == approval.idempotency_key))).scalar_one_or_none()
    assert order is not None
    assert order.sku == sku


@pytest.mark.asyncio
async def test_rejected_approval_cannot_execute(session):
    await seed_demo_users()
    user = (await session.execute(__import__('sqlalchemy').select(User).where(User.email == "manager@cellutech.com"))).scalar_one()
    thread = await _create_thread(session, user.id)
    approval = await persist_pending_approval(
        session,
        user_id=user.id,
        thread_id=str(thread.id),
        tool_name="purchase_order_create",
        action_args={"sku": "SKU-REJECTED", "quantity": 1, "supplier": "Acme Supplies"},
    )
    await session.commit()

    approval = await reject_approval_request(session, current_user=user, approval_id=approval.id, reason="Rejected")
    assert approval.status == "REJECTED"
    count = await session.execute(__import__('sqlalchemy').select(Order).where(Order.sku == "SKU-REJECTED"))
    assert count.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_user_cannot_approve_another_users_approval(async_client, session):
    await seed_demo_users()
    owner = (await session.execute(__import__('sqlalchemy').select(User).where(User.email == "manager@cellutech.com"))).scalar_one()
    other = (await session.execute(__import__('sqlalchemy').select(User).where(User.email == "viewer@cellutech.com"))).scalar_one()
    thread = await _create_thread(session, owner.id)
    approval = await persist_pending_approval(
        session,
        user_id=owner.id,
        thread_id=str(thread.id),
        tool_name="email_send",
        action_args={"recipient": "ops@cellutech.com", "subject": "Hello", "body": "Test"},
    )
    await session.commit()

    token = await _login(async_client, "viewer@cellutech.com", "ViewerPassword123!")
    response = await async_client.post(f"/approvals/{approval.id}/approve", headers={"Authorization": f"Bearer {token}"}, json={"reason": "Nope"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_pending_approval_and_action_request_are_supported_in_chat_state(session):
    await seed_demo_users()
    user = (await session.execute(__import__('sqlalchemy').select(User).where(User.email == "manager@cellutech.com"))).scalar_one()
    thread = await _create_thread(session, user.id)
    approval = await persist_pending_approval(
        session,
        user_id=user.id,
        thread_id=str(thread.id),
        tool_name="email_send",
        action_args={"recipient": "ops@cellutech.com", "subject": "Reminder", "body": "Hello"},
    )
    await session.commit()

    stored = await session.get(ApprovalRequest, approval.id)
    assert stored is not None
    assert stored.status == "PENDING"
    assert stored.tool_name == "email_send"
    assert stored.user_id == user.id
