from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent import model as model_module
from app.agent.model import ModelActionPlan, ModelProviderError, OpenAIChatModel, build_chat_model
from app.config import Settings, get_settings
from app.main import create_app
from app.models.order import Order
from app.seed.seed import seed_demo_users


class _FakeOpenAIStream:
    def __init__(self, chunks: list[str]):
        self.chunks = chunks

    async def __aiter__(self):
        for content in self.chunks:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeOpenAIClient:
    def __init__(self, *, api_key: str):
        assert api_key == "test-placeholder-key"
        self.requests: list[dict[str, object]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs.get("stream"):
            return _FakeOpenAIStream(["Policy answer ", "arrived as provider deltas."])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"route": "knowledge"})))],
        )

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def configure_seed_env(monkeypatch):
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


def test_no_key_selects_deterministic_fallback_and_configured_provider_instantiates():
    assert build_chat_model(Settings(model_provider="openai", model_name="gpt-4o-mini", model_api_key="")) is None
    configured = build_chat_model(
        Settings(model_provider="openai", model_name="gpt-4o-mini", model_api_key="test-placeholder-key")
    )
    assert isinstance(configured, OpenAIChatModel)
    assert configured.model_name == "gpt-4o-mini"
    assert configured.api_key == "test-placeholder-key"
    compatible = build_chat_model(
        Settings(
            model_provider="openai-compatible",
            model_name="local-chat-model",
            model_api_key="test-placeholder-key",
            model_base_url="https://models.example.test/v1",
        )
    )
    assert isinstance(compatible, OpenAIChatModel)
    assert compatible.base_url == "https://models.example.test/v1"


@pytest.mark.asyncio
async def test_openai_adapter_parses_plans_and_yields_native_stream_deltas(monkeypatch):
    clients: list[_FakeOpenAIClient] = []

    def fake_client(**kwargs):
        client = _FakeOpenAIClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(model_module, "AsyncOpenAI", fake_client)
    configured = OpenAIChatModel(model_name="gpt-4o-mini", api_key="test-placeholder-key")

    plan = await configured.plan_request("What does the procurement policy require?")
    assert isinstance(plan, ModelActionPlan)
    assert plan.route == "knowledge"

    deltas = [
        delta
        async for delta in configured.stream_grounded_answer(
            "What does the policy require?",
            [{"title": "Procurement", "section": "Approval", "excerpt": "A manager approves purchases over the threshold."}],
        )
    ]
    assert deltas == ["Policy answer ", "arrived as provider deltas."]
    assert clients[1].requests[0]["stream"] is True


@pytest.mark.asyncio
async def test_model_mode_sse_forwards_real_provider_delta_events(monkeypatch):
    await seed_demo_users()

    class FakeModel:
        async def plan_request(self, _message: str) -> ModelActionPlan:
            return ModelActionPlan(route="knowledge")

        async def stream_grounded_answer(self, _question: str, _sources: list[dict[str, str]]):
            yield "Streamed from "
            yield "the configured provider."

    monkeypatch.setattr("app.agent.nodes.build_chat_model", lambda: FakeModel())
    application = create_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            login = await client.post(
                "/auth/login",
                json={"email": "admin@assistant.test", "password": "AdminPassword123!"},
            )
            assert login.status_code == 200
            async with client.stream(
                "POST",
                "/chat/stream",
                json={"message": "What does procurement policy require?"},
                headers={"accept": "text/event-stream"},
            ) as response:
                payload = "".join([chunk async for chunk in response.aiter_text()])
    delta_events = [
        json.loads(block.split("data: ", 1)[1])
        for block in payload.strip().split("\n\n")
        if block.startswith("event: assistant_delta")
    ]
    assert [event["content"] for event in delta_events] == ["Streamed from ", "the configured provider."]
    final_payload = next(json.loads(block.split("data: ", 1)[1]) for block in payload.split("\n\n") if block.startswith("event: final"))
    assert "Streamed from the configured provider." in final_payload["response"]


@pytest.mark.asyncio
async def test_model_provider_failure_fails_closed_without_write(monkeypatch, session):
    await seed_demo_users()
    before = await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043"))

    class FailingModel:
        async def plan_request(self, _message: str):
            raise ModelProviderError("Provider failure")

    monkeypatch.setattr("app.agent.nodes.build_chat_model", lambda: FailingModel())
    application = create_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            await client.post(
                "/auth/login",
                json={"email": "admin@assistant.test", "password": "AdminPassword123!"},
            )
            response = await client.post(
                "/chat",
                json={"message": "Create a purchase order for SKU-1043 quantity 3 from Northstar Supply."},
            )
            assert response.status_code == 200
            assert response.json()["error"] == "model_provider_failure"
            assert "no action was run" in response.json()["response"].lower()
            assert response.json()["approval_request"] is None

    after = await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043"))
    assert after == before


@pytest.mark.asyncio
async def test_model_action_plan_enters_the_same_order_approval_gate(monkeypatch, session):
    await seed_demo_users()
    before = await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043"))

    class ActionPlanningModel:
        async def plan_request(self, _message: str) -> ModelActionPlan:
            return ModelActionPlan(
                route="action",
                wants_order=True,
                order_sku="SKU-1043",
                order_quantity=4,
                supplier="Northstar Supply",
            )

    monkeypatch.setattr("app.agent.nodes.build_chat_model", lambda: ActionPlanningModel())
    application = create_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            await client.post(
                "/auth/login",
                json={"email": "admin@assistant.test", "password": "AdminPassword123!"},
            )
            response = await client.post("/chat", json={"message": "Please restock the operations module."})
            assert response.status_code == 200
            approval_request = response.json()["approval_request"]
            assert approval_request["required"] is True
            assert approval_request["action_args"] == {
                "sku": "SKU-1043",
                "quantity": 4,
                "supplier": "Northstar Supply",
            }
            assert await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043")) == before

            approved = await client.post(f"/approvals/{approval_request['approval_id']}/approve", json={})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "EXECUTED"
            assert await session.scalar(select(func.count()).select_from(Order).where(Order.sku == "SKU-1043")) == before + 1
