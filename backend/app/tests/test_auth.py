from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.product import Product
from app.models.thread import Thread
from app.models.user import User
from app.models.user_capability import UserCapability
from app.seed.seed import seed_demo_users

ADMIN_EMAIL = "admin@cellutech.com"
OPS_EMAIL = "ops@cellutech.com"
MANAGER_EMAIL = "manager@cellutech.com"
VIEWER_EMAIL = "viewer@cellutech.com"
ALL_USER_EMAILS = [ADMIN_EMAIL, OPS_EMAIL, MANAGER_EMAIL, VIEWER_EMAIL]


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


def make_session_factory():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession), engine


@pytest_asyncio.fixture
async def async_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def seeded_users():
    await seed_demo_users()
    return {
        "admin": "AdminPassword123!",
        "ops": "OpsPassword123!",
        "manager": "ManagerPassword123!",
        "viewer": "ViewerPassword123!",
    }


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as db_session:
        yield db_session
    await engine.dispose()


async def _login(async_client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await async_client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_seed_command_creates_all_four_users_and_capabilities(async_client):
    await seed_demo_users()
    session_factory, engine = make_session_factory()
    try:
        async with session_factory() as session:
            users = (await session.execute(select(User).where(User.email.in_(ALL_USER_EMAILS)))).scalars().all()
            assert {user.email: user.is_admin for user in users} == {
                ADMIN_EMAIL: True,
                OPS_EMAIL: False,
                MANAGER_EMAIL: False,
                VIEWER_EMAIL: False,
            }

            expected_capabilities = {
                ADMIN_EMAIL: {"policy:read", "inventory:read", "order:create", "email:send"},
                OPS_EMAIL: {"policy:read", "inventory:read", "order:create", "email:send"},
                MANAGER_EMAIL: {"policy:read", "inventory:read", "order:create"},
                VIEWER_EMAIL: {"policy:read", "inventory:read"},
            }
            actual_capabilities = {}
            for user in users:
                result = await session.execute(
                    select(UserCapability.capability).where(UserCapability.user_id == user.id)
                )
                actual_capabilities[user.email] = set(result.scalars().all())
            assert actual_capabilities == expected_capabilities

    finally:
        await engine.dispose()

    for email, password in (
        (ADMIN_EMAIL, "AdminPassword123!"),
        (OPS_EMAIL, "OpsPassword123!"),
        (MANAGER_EMAIL, "ManagerPassword123!"),
        (VIEWER_EMAIL, "ViewerPassword123!"),
    ):
        assert (await async_client.post("/auth/login", json={"email": email, "password": password})).status_code == 200


@pytest.mark.asyncio
async def test_seed_command_is_idempotent():
    await seed_demo_users()
    await seed_demo_users()
    session_factory, engine = make_session_factory()
    try:
        async with session_factory() as session:
            result = await session.execute(select(User.email).where(User.email.in_(ALL_USER_EMAILS)))
            emails = set(result.scalars().all())
            assert emails.issuperset(set(ALL_USER_EMAILS))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_passwords_are_stored_as_hashes():
    await seed_demo_users()
    session_factory, engine = make_session_factory()
    try:
        async with session_factory() as session:
            user = (await session.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one()
            assert user.password_hash.startswith("$argon2id$")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_correct_password_authenticates(async_client, seeded_users):
    response = await async_client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "AdminPassword123!"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_incorrect_password_fails(async_client, seeded_users):
    response = await async_client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


@pytest.mark.asyncio
async def test_inactive_user_cannot_authenticate(async_client):
    inactive_email = f"inactive_{uuid.uuid4().hex[:8]}@cellutech.com"
    session_factory, engine = make_session_factory()
    try:
        async with session_factory() as session:
            user = User(
                email=inactive_email,
                password_hash="$argon2id$v=19$m=65536,t=3,p=4$abcdefghijklmnopqrstuv$abcdefghijklmnopqrstuv",
                is_admin=False,
                is_active=False,
            )
            session.add(user)
            await session.commit()
    finally:
        await engine.dispose()

    response = await async_client.post(
        "/auth/login",
        json={"email": inactive_email, "password": "TestPassword123!"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_returns_jwt(async_client, seeded_users):
    token = await _login(async_client, ADMIN_EMAIL, "AdminPassword123!")
    assert token


@pytest.mark.asyncio
async def test_invalid_jwt_returns_401(async_client, seeded_users):
    response = await async_client.get("/auth/me", headers={"Authorization": "Bearer definitely-not-valid"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(async_client, seeded_users):
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        "this_is_a_very_long_test_secret_key_1234567890",
        algorithm="HS256",
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_requires_authentication(async_client, seeded_users):
    response = await async_client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_returns_auth_data_without_password_hash(async_client, seeded_users):
    token = await _login(async_client, VIEWER_EMAIL, "ViewerPassword123!")
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == VIEWER_EMAIL
    assert payload["is_admin"] is False
    assert payload["is_active"] is True
    assert "password_hash" not in payload
    assert "capabilities" in payload


@pytest.mark.asyncio
async def test_admin_can_access_admin_users(async_client, seeded_users):
    token = await _login(async_client, ADMIN_EMAIL, "AdminPassword123!")
    response = await async_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    users = response.json()
    assert any(user["email"] == ADMIN_EMAIL for user in users)


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_users(async_client, seeded_users):
    token = await _login(async_client, VIEWER_EMAIL, "ViewerPassword123!")
    response = await async_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_endpoint_requires_authentication(async_client, seeded_users):
    response = await async_client.get("/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_stream_emits_server_sent_events(async_client, seeded_users):
    token = await _login(async_client, ADMIN_EMAIL, "AdminPassword123!")
    async with async_client.stream(
        "POST",
        "/chat/stream",
        json={"message": "What procurement policy covers purchase order approval?"},
        headers={"Authorization": f"Bearer {token}", "accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join([chunk async for chunk in response.aiter_text()])

    assert "event: status" in payload
    assert "event: final" in payload

    async_client.cookies.clear()
    unauthenticated = await async_client.post(
        "/chat/stream",
        json={"message": "What is the procurement policy?"},
    )
    assert unauthenticated.status_code == 401

    token = await _login(async_client, ADMIN_EMAIL, "AdminPassword123!")
    async with async_client.stream(
        "POST",
        "/chat/stream",
        json={"message": "What is the procurement policy?", "thread_id": "not-a-uuid"},
        headers={"Authorization": f"Bearer {token}", "accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        payload = "".join([chunk async for chunk in response.aiter_text()])

    assert "event: error" in payload
    assert "Thread ID is invalid." in payload
    assert "Traceback" not in payload


@pytest.mark.asyncio
async def test_seed_command_creates_assistant_demo_users_and_capabilities(async_client):
    await seed_demo_users()
    session_factory, engine = make_session_factory()
    try:
        async with session_factory() as session:
            expected = {
                "admin@assistant.test": {"policy:read", "inventory:read", "order:create", "email:send"},
                "ali@assistant.test": {"policy:read", "inventory:read"},
                "sara@assistant.test": {"policy:read", "inventory:read", "order:create"},
                "dave@assistant.test": set(),
            }
            actual = {}
            for email, capabilities in expected.items():
                user = (await session.execute(select(User).where(User.email == email))).scalar_one()
                result = await session.execute(
                    select(UserCapability.capability).where(UserCapability.user_id == user.id)
                )
                actual[email] = set(result.scalars().all())
            assert actual == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reference_scenario_purchase_order_approval_flow(async_client, seeded_users, session):
    await seed_demo_users()
    manager = (await session.execute(select(User).where(User.email == "manager@cellutech.com"))).scalar_one()
    sku = f"SKU-REF-{uuid.uuid4().hex[:8]}"
    session.add(Product(sku=sku, name="Reference Widget", quantity_on_hand=42, unit_price=10.50, supplier="Acme Supplies"))
    await session.commit()

    token = await _login(async_client, "manager@cellutech.com", "ManagerPassword123!")
    inventory_response = await async_client.post(
        "/chat",
        json={"message": f"Check inventory for {sku}.", "thread_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert inventory_response.status_code == 200
    inventory_payload = inventory_response.json()
    assert inventory_payload["action_request"]["tool_name"] == "inventory_lookup"
    assert inventory_payload["action_request"]["status"] == "executed"
    assert inventory_payload["action_request"]["result"]["quantity_on_hand"] == 42
    thread_id = inventory_payload["thread_id"]

    async with async_client.stream(
        "POST",
        "/chat/stream",
        json={"message": f"Create a purchase order for {sku} quantity 2 from Acme Supplies.", "thread_id": thread_id},
        headers={"Authorization": f"Bearer {token}", "accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        stream_payload = "".join([chunk async for chunk in response.aiter_text()])

    events: dict[str, list[dict[str, object]]] = {}
    for block in stream_payload.strip().split("\n\n"):
        lines = block.splitlines()
        event_name = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        if event_name and data:
            events.setdefault(event_name, []).append(json.loads(data))

    assert "status" in events
    assert "approval" in events
    payload = events["final"][0]
    assert payload["thread_id"] == thread_id
    assert payload["approval_request"]["required"] is True
    approval_id = payload["approval_request"]["approval_id"]

    pending = await async_client.get("/approvals/pending", headers={"Authorization": f"Bearer {token}"})
    assert pending.status_code == 200
    assert any(item["id"] == approval_id for item in pending.json())
    assert events["approval"][0]["approval_id"] == approval_id

    approval = await session.get(ApprovalRequest, approval_id)
    assert approval is not None
    assert str(approval.thread_id) == thread_id
    assert approval.status == "PENDING"
    assert approval.action_args["sku"] == sku
    assert approval.action_args["supplier"] == "Acme Supplies"
    assert (await session.execute(select(Order).where(Order.idempotency_key == approval.idempotency_key))).scalar_one_or_none() is None

    approved = await async_client.post(
        f"/approvals/{approval_id}/approve",
        json={"reason": "Approved for the reference scenario"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "EXECUTED"
    assert approved.json()["result"]["sku"] == sku
    assert approved.json()["result"]["idempotency_key"] == approval.idempotency_key

    order = (await session.execute(select(Order).where(Order.idempotency_key == approval.idempotency_key))).scalar_one()
    assert order.sku == sku
    assert order.supplier == "Acme Supplies"
    audit_logs = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.thread_id == thread_id,
                AuditLog.tool == "purchase_order_create",
                AuditLog.outcome == "executed",
            )
        )
    ).scalars().all()
    assert len(audit_logs) == 1
    thread = await session.get(Thread, uuid.UUID(thread_id))
    assert thread is not None
    assert thread.owner_user_id == manager.id
    assert [message["role"] for message in thread.messages] == ["user", "assistant", "user", "assistant"]
    assert thread.messages[0]["content"] == f"Check inventory for {sku}."

    duplicate = await async_client.post(
        f"/approvals/{approval_id}/approve",
        json={"reason": "Retry"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert duplicate.status_code == 409
    order_rows = await session.execute(select(Order).where(Order.idempotency_key == approval.idempotency_key))
    assert len(order_rows.scalars().all()) == 1


@pytest.mark.asyncio
async def test_user_without_capability_cannot_pass_require_capability(async_client, seeded_users):
    token = await _login(async_client, VIEWER_EMAIL, "ViewerPassword123!")
    response = await async_client.get("/authz/order-test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_with_capability_can_pass_require_capability(async_client, seeded_users):
    token = await _login(async_client, VIEWER_EMAIL, "ViewerPassword123!")
    response = await async_client.get("/authz/inventory-test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_capabilities_are_loaded_from_database_not_jwt(async_client, seeded_users):
    forged = jwt.encode(
        {"sub": "1", "capabilities": ["email:send"], "exp": datetime.now(timezone.utc) + timedelta(minutes=60)},
        "this_is_a_very_long_test_secret_key_1234567890",
        algorithm="HS256",
    )
    response = await async_client.get("/authz/email-test", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_obtain_order_create_authorization(async_client, seeded_users):
    token = await _login(async_client, VIEWER_EMAIL, "ViewerPassword123!")
    response = await async_client.get("/authz/order-test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_manager_cannot_obtain_email_send_authorization(async_client, seeded_users):
    token = await _login(async_client, MANAGER_EMAIL, "ManagerPassword123!")
    response = await async_client.get("/authz/email-test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_has_all_four_capabilities(async_client, seeded_users):
    token = await _login(async_client, ADMIN_EMAIL, "AdminPassword123!")
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    capabilities = set(response.json()["capabilities"])
    assert capabilities == {"policy:read", "inventory:read", "order:create", "email:send"}
