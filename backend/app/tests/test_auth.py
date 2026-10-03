from __future__ import annotations

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
            result = await session.execute(select(User.email).where(User.email.in_(ALL_USER_EMAILS)))
            emails = set(result.scalars().all())
            assert emails.issuperset(set(ALL_USER_EMAILS))

            capability_rows = await session.execute(
                select(UserCapability.user_id, UserCapability.capability).where(
                    UserCapability.user_id.in_(select(User.id).where(User.email.in_(ALL_USER_EMAILS)))
                )
            )
            assert len(capability_rows.all()) >= 12
    finally:
        await engine.dispose()


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
