from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def use_deterministic_model_fallback_by_default(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "")
    monkeypatch.setenv("MODEL_NAME", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
