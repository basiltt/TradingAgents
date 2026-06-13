"""Phase 2 — state-filter allowlist for regime_context (spec FR-6, AC-4).

With information barriers ON, regime_context must survive the read filter for
portfolio_manager and technical_analyst, and be stripped for other roles.
"""
import pytest

from tradingagents.agents.utils.state_filter import filter_state_for_read


def _state():
    return {
        "regime_context": "REGIME-X",
        "company_of_interest": "BTCUSDT",
        "crypto_interval": "15",
        "current_price_context": "price",
    }


@pytest.fixture(autouse=True)
def _barriers_on(monkeypatch):
    # Force information barriers ON regardless of env/default so the filter is active.
    import tradingagents.agents.utils.state_filter as sf
    monkeypatch.setattr(sf, "is_enabled", lambda flag: True)
    yield


def test_pm_keeps_regime_context():
    out = filter_state_for_read(_state(), "portfolio_manager")
    assert out.get("regime_context") == "REGIME-X"


def test_technical_analyst_strips_regime_context():
    # Regime context is injected at the PM only (the decision-maker); the
    # technical analyst is NOT allowlisted, so the barrier strips it.
    out = filter_state_for_read(_state(), "technical_analyst")
    assert "regime_context" not in out


def test_news_analyst_strips_regime_context():
    out = filter_state_for_read(_state(), "news_analyst")
    assert "regime_context" not in out
