"""Tests for ai_manager_llm_provider — LLM callable creation and resilience.

Covers two fixes:
  1. Graceful degradation when the LLM (or its proxy) returns an empty
     content array — the callable must NOT raise (which spams ERROR tracebacks
     and forces a retry); it returns an empty string so the decision graph
     falls back to HOLD cleanly.
  2. LLM identity used for change-detection must include backend_url + api_key,
     so that changing the proxy endpoint/port or the key on a *running* AI
     Manager task triggers a live refresh (not just provider/model changes).
"""

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fix 1: graceful empty-content handling
# ---------------------------------------------------------------------------


def _mock_transport(json_body: dict, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json_body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_anthropic_empty_content_returns_empty_string_not_raise(monkeypatch):
    """An empty content array (e.g. stop_reason=None from a proxy) must degrade
    to an empty string instead of raising ValueError."""
    from backend.services import ai_manager_llm_provider as prov

    # Neutralize the global rate limiter so the call is hermetic.
    monkeypatch.setattr(prov, "_acquire_global_rate_limit", _async_false)
    monkeypatch.setattr(prov, "_release_global_rate_limit", lambda acquired: None)

    callable_, _model, close = prov.create_llm_callable_with_cleanup(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
        backend_url="http://localhost:3131",
    )
    assert callable_ is not None

    # Inject a transport that returns the degenerate empty-content body.
    _swap_transport(callable_, _mock_transport({"content": [], "stop_reason": None}))

    result = await callable_("system", "context")
    assert result == ""  # graceful: empty string, not an exception
    await close()


@pytest.mark.asyncio
async def test_anthropic_normal_text_still_returned(monkeypatch):
    """A normal text block is still extracted and returned."""
    from backend.services import ai_manager_llm_provider as prov

    monkeypatch.setattr(prov, "_acquire_global_rate_limit", _async_false)
    monkeypatch.setattr(prov, "_release_global_rate_limit", lambda acquired: None)

    callable_, _model, close = prov.create_llm_callable_with_cleanup(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
        backend_url="http://localhost:3131",
    )
    _swap_transport(
        callable_,
        _mock_transport(
            {"content": [{"type": "text", "text": "HELLO"}], "stop_reason": "end_turn"}
        ),
    )
    result = await callable_("system", "context")
    assert result == "HELLO"
    await close()


@pytest.mark.asyncio
async def test_openai_empty_choices_returns_empty_string(monkeypatch):
    """OpenAI-compatible path: empty/missing choices degrade to empty string."""
    from backend.services import ai_manager_llm_provider as prov

    monkeypatch.setattr(prov, "_acquire_global_rate_limit", _async_false)
    monkeypatch.setattr(prov, "_release_global_rate_limit", lambda acquired: None)

    callable_, _model, close = prov.create_llm_callable_with_cleanup(
        provider="openai",
        api_key="test-key",
        model="gpt-4o-mini",
        backend_url="http://localhost:3131",
    )
    _swap_transport(callable_, _mock_transport({"choices": []}))
    result = await callable_("system", "context")
    assert result == ""
    await close()


# ---------------------------------------------------------------------------
# Pure-helper unit tests: _extract_anthropic_text / _extract_openai_text
# ---------------------------------------------------------------------------


def test_extract_anthropic_text_empty_content_returns_empty():
    from backend.services.ai_manager_llm_provider import _extract_anthropic_text

    assert _extract_anthropic_text({"content": [], "stop_reason": None}, "m") == ""
    assert _extract_anthropic_text({}, "m") == ""


def test_extract_anthropic_text_prefers_text_block_over_thinking():
    from backend.services.ai_manager_llm_provider import _extract_anthropic_text

    data = {
        "content": [
            {"type": "thinking", "thinking": "reasoning..."},
            {"type": "text", "text": "DECISION"},
        ],
        "stop_reason": "end_turn",
    }
    assert _extract_anthropic_text(data, "m") == "DECISION"


def test_extract_anthropic_text_falls_back_to_thinking_when_no_text():
    from backend.services.ai_manager_llm_provider import _extract_anthropic_text

    data = {"content": [{"type": "thinking", "thinking": "only-thinking"}]}
    assert _extract_anthropic_text(data, "m") == "only-thinking"


def test_extract_openai_text_empty_and_normal():
    from backend.services.ai_manager_llm_provider import _extract_openai_text

    assert _extract_openai_text({"choices": []}, "m") == ""
    assert _extract_openai_text({"choices": [{"message": {"content": None}}]}, "m") == ""
    assert (
        _extract_openai_text({"choices": [{"message": {"content": "OK"}}]}, "m") == "OK"
    )


@pytest.mark.asyncio
async def test_anthropic_non_cleanup_path_also_degrades(monkeypatch):
    """The create_llm_callable (non-cleanup) anthropic path must degrade too —
    it shares _extract_anthropic_text with the cleanup path."""
    from backend.services import ai_manager_llm_provider as prov

    monkeypatch.setattr(prov, "_acquire_global_rate_limit", _async_false)
    monkeypatch.setattr(prov, "_release_global_rate_limit", lambda acquired: None)

    callable_, _model = prov.create_llm_callable(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
        backend_url="http://localhost:3131",
    )
    assert callable_ is not None
    _swap_transport(callable_, _mock_transport({"content": [], "stop_reason": None}))
    result = await callable_("system", "context")
    assert result == ""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _async_false():
    return False


def _swap_transport(callable_, transport: httpx.MockTransport) -> None:
    """Reach into the closure's httpx client and replace its transport.

    The callable closes over a module-level `client` (httpx.AsyncClient). We
    locate it via the closure cells and swap the transport so the request is
    served by our mock instead of hitting the network.
    """
    for cell in callable_.__closure__ or ():
        val = cell.cell_contents
        if isinstance(val, httpx.AsyncClient):
            val._transport = transport
            # Also patch the per-host transport map used by AsyncClient.
            val._mounts = {}
            return
    raise AssertionError("Could not find httpx.AsyncClient in callable closure")


# ---------------------------------------------------------------------------
# Fix 2: LLM identity includes backend_url + api_key (stale-settings refresh)
# ---------------------------------------------------------------------------


def _scan_configs(account_id: str, *, provider="anthropic", model="claude-sonnet-4-6",
                  backend_url=None, api_key=None):
    """Build a minimal scan_configs list that enables the AI manager for account_id."""
    return [
        {
            "provider": provider,
            "deep_think_llm": model,
            "backend_url": backend_url,
            "llm_api_key": api_key,
            "auto_trade_configs": [
                {"account_id": account_id, "ai_manager_enabled": True}
            ],
        }
    ]


def test_identity_changes_when_backend_url_changes():
    """Changing the proxy URL/port must produce a different identity so a running
    task gets its LLM callable refreshed."""
    from backend.services.ai_account_manager_service import AIAccountManagerService

    acc = "acc-1"
    id_3131 = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, backend_url="http://localhost:3131")
    )
    id_4141 = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, backend_url="http://localhost:4141")
    )
    assert id_3131 is not None
    assert id_3131 != id_4141


def test_identity_changes_when_api_key_changes():
    """Rotating the API key must change the identity."""
    from backend.services.ai_account_manager_service import AIAccountManagerService

    acc = "acc-1"
    id_a = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, api_key="key-a")
    )
    id_b = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, api_key="key-b")
    )
    assert id_a != id_b


def test_identity_stable_when_nothing_changes():
    """Identical settings must produce identical identity (no spurious refresh)."""
    from backend.services.ai_account_manager_service import AIAccountManagerService

    acc = "acc-1"
    cfg = dict(backend_url="http://localhost:3131", api_key="key-a")
    id1 = AIAccountManagerService._extract_llm_identity(acc, _scan_configs(acc, **cfg))
    id2 = AIAccountManagerService._extract_llm_identity(acc, _scan_configs(acc, **cfg))
    assert id1 == id2


def test_identity_still_changes_on_model_change():
    """Existing behavior preserved: model change still changes identity."""
    from backend.services.ai_account_manager_service import AIAccountManagerService

    acc = "acc-1"
    id_sonnet = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, model="claude-sonnet-4-6")
    )
    id_haiku = AIAccountManagerService._extract_llm_identity(
        acc, _scan_configs(acc, model="claude-haiku-4-5")
    )
    assert id_sonnet != id_haiku
