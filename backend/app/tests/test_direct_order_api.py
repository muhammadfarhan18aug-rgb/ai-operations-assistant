from __future__ import annotations

import hashlib
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import create_app
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.user import User
from app.seed.seed import seed_demo_users


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


@pytest.mark.asyncio
async def test_ali_direct_purchase_order_api_returns_403_and_audits_denial(session):
    await seed_demo_users()
    ali = await session.scalar(select(User).where(User.email == "ali@assistant.test"))
    assert ali is not None
    before = await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043"))
    application = create_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            login = await client.post("/auth/login", json={"email": ali.email, "password": "AliPassword123!"})
            assert login.status_code == 200
            response = await client.post(
                "/purchase-orders",
                json={
                    "sku": "SKU-1043",
                    "quantity": 5,
                    "supplier": "Northstar Supply",
                },
            )
            assert response.status_code == 403, response.text
            assert "/chat" not in response.request.url.path

    after = await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043"))
    assert after == before
    denials = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.user_id == ali.id)
            .where(AuditLog.tool == "purchase_order_create")
            .where(AuditLog.outcome == "denied")
            .order_by(AuditLog.created_at.desc())
        )
    ).all()
    assert denials
    assert denials[0].arguments["request_source"] == "direct_api"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("admin@assistant.test", "AdminPassword123!"),
        ("sara@assistant.test", "SaraPassword123!"),
    ],
)
async def test_authorized_direct_order_still_requires_graph_approval(session, email: str, password: str):
    await seed_demo_users()
    application = create_app()
    idempotency_key = f"authorized-direct-{uuid.uuid4().hex}"
    request_body = {
        "sku": "SKU-1043",
        "quantity": 2,
        "supplier": "Northstar Supply",
        "idempotency_key": idempotency_key,
    }
    request_id = f"direct-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}"
    tool_idempotency_key = f"po-{request_id}"
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            login = await client.post("/auth/login", json={"email": email, "password": password})
            assert login.status_code == 200
            first = await client.post("/purchase-orders", json=request_body)
            assert first.status_code == 202, first.text
            approval = first.json()
            assert approval["status"] == "PENDING"
            assert approval["tool_name"] == "purchase_order_create"
            assert approval["action_args"]["quantity"] == 2
            assert await session.scalar(select(Order.id).where(Order.idempotency_key == tool_idempotency_key)) is None

            repeated = await client.post("/purchase-orders", json=request_body)
            assert repeated.status_code == 202
            assert repeated.json()["id"] == approval["id"]
            assert await session.scalar(select(Order.id).where(Order.idempotency_key == tool_idempotency_key)) is None

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as other_user:
                await other_user.post(
                    "/auth/login",
                    json={"email": "ali@assistant.test", "password": "AliPassword123!"},
                )
                stolen_key = await other_user.post("/purchase-orders", json=request_body)
                assert stolen_key.status_code == 403

            approved = await client.post(f"/approvals/{approval['id']}/approve", json={})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "EXECUTED"
            order = await session.scalar(select(Order).where(Order.idempotency_key == tool_idempotency_key))
            assert order is not None and order.quantity == 2
            assert (await client.post("/purchase-orders", json=request_body)).status_code == 409
            assert len((await session.scalars(select(Order).where(Order.idempotency_key == tool_idempotency_key))).all()) == 1
