from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.thread import Thread
from app.models.user import User
from app.seed.seed import seed_demo_users
from app.services.approvals import persist_pending_approval, requires_human_approval


@pytest.fixture(autouse=True)
def configure_demo_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "this_is_a_very_long_test_secret_key_1234567890")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "AdminPassword123!")
    monkeypatch.setenv("SEED_ALI_PASSWORD", "AliPassword123!")
    monkeypatch.setenv("SEED_SARA_PASSWORD", "SaraPassword123!")
    monkeypatch.setenv("SEED_DAVE_PASSWORD", "DavePassword123!")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client():
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _thread(session: AsyncSession, user: User) -> Thread:
    thread = Thread(owner_user_id=user.id, title="Approval ownership test")
    session.add(thread)
    await session.commit()
    return thread


@pytest.mark.asyncio
async def test_write_tools_require_graph_approval():
    assert requires_human_approval("purchase_order_create") is True
    assert requires_human_approval("email_send") is True
    assert requires_human_approval("inventory_lookup") is False
    assert requires_human_approval("policy_lookup") is False


@pytest.mark.asyncio
async def test_user_cannot_resume_another_users_approval(async_client, session):
    await seed_demo_users()
    owner = await session.scalar(select(User).where(User.email == "sara@assistant.test"))
    other = await session.scalar(select(User).where(User.email == "dave@assistant.test"))
    assert owner is not None and other is not None
    thread = await _thread(session, owner)
    approval = await persist_pending_approval(
        session,
        user_id=owner.id,
        thread_id=str(thread.id),
        tool_name="email_send",
        action_args={"recipient": "admin@assistant.test", "subject": "Hello", "body": "Test"},
    )
    await session.commit()

    login = await async_client.post("/auth/login", json={"email": other.email, "password": "DavePassword123!"})
    assert login.status_code == 200
    response = await async_client.post(f"/approvals/{approval.id}/approve", json={})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_expired_approval_cannot_resume(async_client, session):
    await seed_demo_users()
    owner = await session.scalar(select(User).where(User.email == "admin@assistant.test"))
    assert owner is not None
    thread = await _thread(session, owner)
    approval = await persist_pending_approval(
        session,
        user_id=owner.id,
        thread_id=str(thread.id),
        tool_name="purchase_order_create",
        action_args={"sku": "SKU-1043", "quantity": 1, "supplier": "Northstar Supply"},
    )
    approval.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    login = await async_client.post("/auth/login", json={"email": owner.email, "password": "AdminPassword123!"})
    assert login.status_code == 200
    response = await async_client.post(f"/approvals/{approval.id}/approve", json={})
    assert response.status_code == 409
    await session.refresh(approval)
    assert approval.status == "EXPIRED"