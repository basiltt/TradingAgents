"""Tests for models router — TASK-007."""

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app(tmp_path):
    import os
    os.environ["TRADINGAGENTS_WEB_DB_PATH"] = str(tmp_path / "test.db")
    from backend.main import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


@pytest.mark.asyncio
async def test_get_models_valid_provider(client):
    resp = await client.get("/api/v1/models/openai")
    assert resp.status_code == 200
    data = resp.json()
    assert "quick" in data
    assert "deep" in data


@pytest.mark.asyncio
async def test_get_models_invalid_provider(client):
    resp = await client.get("/api/v1/models/badprovider")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_providers(client):
    resp = await client.get("/api/v1/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "openai" in data["providers"]
    assert "anthropic" in data["providers"]


# ---------------------------------------------------------------------------
# /fetch-models — native provider support (no custom URL)
# Regression: native `anthropic` (empty proxy URL) must return the real model
# list from api.anthropic.com instead of falling back to the hardcoded catalog.
# ---------------------------------------------------------------------------


def _capture_transport(json_body: dict, captured: dict, status: int = 200) -> httpx.MockTransport:
    """MockTransport that records the outbound request for assertions."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(status, json=json_body)

    return httpx.MockTransport(handler)


def _patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Force the models router's httpx.AsyncClient to use a mock transport."""
    import backend.routers.models as models_mod

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(models_mod.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_models_native_anthropic_uses_real_endpoint(client, monkeypatch):
    """Native anthropic (no custom url) must hit api.anthropic.com/v1/models with
    x-api-key auth and parse the anthropic response shape (id + display_name)."""
    captured: dict = {}
    body = {
        "data": [
            {"id": "claude-opus-4-20250514", "display_name": "Claude Opus 4"},
            {"id": "claude-3-5-haiku-20241022", "display_name": "Claude Haiku 3.5"},
        ]
    }
    _patch_async_client(monkeypatch, _capture_transport(body, captured))

    resp = await client.post(
        "/api/v1/fetch-models",
        json={"provider": "anthropic", "api_key": "sk-ant-test"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [m["id"] for m in data["models"]]
    assert "claude-opus-4-20250514" in ids
    assert "claude-3-5-haiku-20241022" in ids
    # Hit the real anthropic endpoint, not a fallback / bearer-only path.
    assert captured["url"].startswith("https://api.anthropic.com/v1/models")
    assert captured["headers"].get("x-api-key") == "sk-ant-test"
    assert "anthropic-version" in captured["headers"]
    # display_name should surface as the human label.
    opus = next(m for m in data["models"] if m["id"] == "claude-opus-4-20250514")
    assert opus["name"] == "Claude Opus 4"


@pytest.mark.asyncio
async def test_fetch_models_native_openai_uses_bearer(client, monkeypatch):
    """Native openai (no custom url) hits api.openai.com with Bearer auth."""
    captured: dict = {}
    body = {"data": [{"id": "gpt-5.4"}, {"id": "gpt-4.1"}]}
    _patch_async_client(monkeypatch, _capture_transport(body, captured))

    resp = await client.post(
        "/api/v1/fetch-models",
        json={"provider": "openai", "api_key": "sk-openai-test"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["models"]]
    assert "gpt-5.4" in ids
    assert captured["url"].startswith("https://api.openai.com/v1/models")
    assert captured["headers"].get("authorization") == "Bearer sk-openai-test"


@pytest.mark.asyncio
async def test_fetch_models_native_google_uses_key_param(client, monkeypatch):
    """Native google hits v1beta/models with ?key= and parses models/ ids."""
    captured: dict = {}
    body = {
        "models": [
            {"name": "models/gemini-3-pro", "displayName": "Gemini 3 Pro"},
            {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash"},
        ]
    }
    _patch_async_client(monkeypatch, _capture_transport(body, captured))

    resp = await client.post(
        "/api/v1/fetch-models",
        json={"provider": "google", "api_key": "g-test"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["models"]]
    # The "models/" prefix is stripped so the id is usable as a model name.
    assert "gemini-3-pro" in ids
    assert "v1beta/models" in captured["url"]
    assert "key=g-test" in captured["url"]


@pytest.mark.asyncio
async def test_fetch_models_native_anthropic_falls_back_to_env_key(client, monkeypatch):
    """When no api_key is supplied, the provider's env key is used."""
    captured: dict = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    body = {"data": [{"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"}]}
    _patch_async_client(monkeypatch, _capture_transport(body, captured))

    resp = await client.post(
        "/api/v1/fetch-models",
        json={"provider": "anthropic"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.json()["models"]
    assert captured["headers"].get("x-api-key") == "sk-ant-env"


@pytest.mark.asyncio
async def test_fetch_models_custom_url_still_bearer(client, monkeypatch):
    """A custom proxy url keeps the existing Bearer + OpenAI-shape behaviour."""
    captured: dict = {}
    body = {"data": [{"id": "MiniMax-M2.7"}]}
    _patch_async_client(monkeypatch, _capture_transport(body, captured))

    resp = await client.post(
        "/api/v1/fetch-models",
        json={"url": "https://api.minimax.io/anthropic", "api_key": "proxy-key"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["models"]]
    assert "MiniMax-M2.7" in ids
    assert captured["url"].startswith("https://api.minimax.io/anthropic/v1/models")
    assert captured["headers"].get("authorization") == "Bearer proxy-key"


@pytest.mark.asyncio
async def test_fetch_models_requires_url_or_provider(client):
    """With neither url nor provider, the endpoint 400s (nothing to query)."""
    resp = await client.post(
        "/api/v1/fetch-models",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400
