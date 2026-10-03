from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from app.config import get_settings
from app.main import create_app
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


@pytest.mark.asyncio
async def test_admin_user_document_and_activity_apis_are_complete():
    await seed_demo_users()
    created_email = f"fresh.operator-{uuid.uuid4().hex[:10]}@assistant.test"
    application = create_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as admin:
            admin_login = await admin.post(
                "/auth/login",
                json={"email": "admin@assistant.test", "password": "AdminPassword123!"},
            )
            assert admin_login.status_code == 200
            users = await admin.get("/admin/users")
            assert users.status_code == 200
            assert {row["email"] for row in users.json()} >= {
                "admin@assistant.test",
                "ali@assistant.test",
                "sara@assistant.test",
                "dave@assistant.test",
            }

            created = await admin.post(
                "/admin/users",
                json={"email": created_email, "password": "InitialPass123!", "capabilities": ["inventory:read"]},
            )
            assert created.status_code == 200, created.text
            created_user = created.json()
            assert created_user["capabilities"] == ["inventory:read"]
            user_id = created_user["id"]

            deactivated = await admin.post(f"/admin/users/{user_id}/deactivate")
            assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
            reactivated = await admin.post(f"/admin/users/{user_id}/reactivate")
            assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
            granted = await admin.post(f"/admin/users/{user_id}/capabilities", json={"capability": "email:send"})
            assert granted.status_code == 200
            assert set(granted.json()["capabilities"]) == {"inventory:read", "email:send"}
            revoked = await admin.request(
                "DELETE",
                f"/admin/users/{user_id}/capabilities",
                json={"capability": "email:send"},
            )
            assert revoked.status_code == 200
            assert revoked.json()["capabilities"] == ["inventory:read"]

            uploaded = await admin.post(
                "/admin/documents",
                json={
                    "title": "Disposable Test Policy",
                    "filename": "disposable_test_policy.md",
                    "content": "The unique reimbursement code is COBALT-731. All claims using this code require itemized receipts.",
                },
            )
            assert uploaded.status_code == 200, uploaded.text
            document_id = uploaded.json()["id"]
            assert uploaded.json()["index_status"] == "indexed"
            listed = await admin.get("/admin/documents")
            assert any(document["id"] == document_id for document in listed.json())
            status = await admin.get("/admin/documents/indexing-status")
            assert status.json()["statuses"]["indexed"] >= 1

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as ali:
            ali_login = await ali.post(
                "/auth/login",
                json={"email": "ali@assistant.test", "password": "AliPassword123!"},
            )
            assert ali_login.status_code == 200
            answer = await ali.post("/chat", json={"message": "What is the unique reimbursement code COBALT-731?"})
            assert answer.status_code == 200
            assert "Disposable Test Policy" in answer.json()["citations"]
            denied = await ali.get("/admin/users")
            assert denied.status_code == 403

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as admin:
            await admin.post("/auth/login", json={"email": "admin@assistant.test", "password": "AdminPassword123!"})
            removed = await admin.delete(f"/admin/documents/{document_id}")
            assert removed.status_code == 200
            assert removed.json()["status"] == "deleted"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as ali:
                await ali.post("/auth/login", json={"email": "ali@assistant.test", "password": "AliPassword123!"})
                after_removal = await ali.post("/chat", json={"message": "What is the unique reimbursement code COBALT-731?"})
                assert after_removal.status_code == 200
                assert "Disposable Test Policy" not in after_removal.json()["citations"]

            activity = await admin.get("/admin/activity")
            assert activity.status_code == 200
            assert {"audit_trail", "orders", "email_messages"} <= set(activity.json())
