"""The auto-trade enable branch applies per-scan capability overrides w/o persisting."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.auto_trade_service import AutoTradeExecutor


def _make_executor_with_ai():
    ai_svc = AsyncMock()
    # No stored config → get_config raises, so defaults are used.
    ai_svc.get_config = AsyncMock(side_effect=ValueError("not configured"))
    ai_svc.enable = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), MagicMock(), ai_manager_service=ai_svc)
    return ex, ai_svc


def _make_executor_with_existing_config(existing: dict):
    """Executor whose account already has a saved AIManagerConfig (as a dict)."""
    ai_svc = AsyncMock()
    ai_svc.get_config = AsyncMock(return_value=existing)
    ai_svc.enable = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), MagicMock(), ai_manager_service=ai_svc)
    return ex, ai_svc


@pytest.mark.asyncio
async def test_emergency_close_override_flows_through():
    """A per-scan emergency_close=False must reach emergency_close_enabled=False on
    the config handed to enable() (the crash-protection footgun end-to-end)."""
    ex, ai_svc = _make_executor_with_ai()
    cfg = {
        "ai_manager_enabled": True,
        "ai_manager_capabilities": {"emergency_close": False},
    }
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    sent_config = ai_svc.enable.await_args[0][1]
    assert sent_config.emergency_close_enabled is False
    assert ai_svc.enable.await_args.kwargs.get("persist") is False


@pytest.mark.asyncio
async def test_override_merges_onto_existing_account_config():
    """The capability override must layer onto the account's saved config, not
    replace it — non-capability fields the user customized must survive."""
    ex, ai_svc = _make_executor_with_existing_config(
        {"max_daily_actions": 7, "mtf_enabled": True}
    )
    cfg = {
        "ai_manager_enabled": True,
        "ai_manager_capabilities": {"mtf": False},
    }
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    sent_config = ai_svc.enable.await_args[0][1]
    assert sent_config.mtf_enabled is False        # capability overridden
    assert sent_config.max_daily_actions == 7      # user's custom value preserved
    assert sent_config.auto_enabled is True


@pytest.mark.asyncio
async def test_override_present_calls_enable_persist_false():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {
        "ai_manager_enabled": True,
        "ai_manager_capabilities": {"trailing": False, "mtf": False},
    }
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")

    ai_svc.enable.assert_awaited_once()
    _args, kwargs = ai_svc.enable.await_args
    assert kwargs.get("persist") is False
    sent_config = _args[1]
    assert sent_config.auto_enabled is True
    assert sent_config.trailing_enabled is False
    assert sent_config.mtf_enabled is False
    assert sent_config.orderbook_enabled is True  # untouched key stays on


@pytest.mark.asyncio
async def test_no_override_uses_legacy_persist_true():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True}  # no capabilities key
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")

    ai_svc.enable.assert_awaited_once()
    _args, kwargs = ai_svc.enable.await_args
    # legacy path: persist not forced False (default True)
    assert kwargs.get("persist", True) is True


@pytest.mark.asyncio
async def test_mean_reversion_skips_enable():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True, "ai_manager_capabilities": {"mtf": False}}
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="mean_reversion")
    ai_svc.enable.assert_not_called()


@pytest.mark.asyncio
async def test_enable_only_once_per_account():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True}
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    ai_svc.enable.assert_awaited_once()  # second call is a no-op


@pytest.mark.asyncio
async def test_malformed_override_falls_back_to_managed_enable():
    """A bad capability override must NOT leave the account unmanaged — it should
    still enable with the account config (persist=True), not skip enablement."""
    ex, ai_svc = _make_executor_with_ai()
    cfg = {
        "ai_manager_enabled": True,
        # Unknown key → ValidationError in apply_capability_overrides; the caller
        # must fall back to a managed enable rather than skip enablement.
        "ai_manager_capabilities": {"bogus_capability": False},
    }
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")

    ai_svc.enable.assert_awaited_once()
    _args, kwargs = ai_svc.enable.await_args
    assert kwargs.get("persist", True) is True  # fell back to safe managed enable
    assert _args[1].auto_enabled is True
    # The config must be the UNMODIFIED account default — no half-applied override.
    assert _args[1].emergency_close_enabled is True  # safety left ON
    assert _args[1].mtf_enabled is True


@pytest.mark.asyncio
async def test_persistent_enable_failure_not_retried_each_placement():
    """A persistent enable failure stays attempted-once (no per-placement spam)."""
    ex, ai_svc = _make_executor_with_ai()
    ai_svc.enable = AsyncMock(side_effect=RuntimeError("db down"))
    cfg = {"ai_manager_enabled": True}
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    assert ai_svc.enable.await_count == 1  # not retried on the second placement
