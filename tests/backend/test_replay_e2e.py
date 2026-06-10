import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PARITY_DB_SMOKE"),
    reason="set PARITY_DB_SMOKE=1 to run replay E2E against local hydrated DB")


@pytest.mark.asyncio
async def test_replay_mode_end_to_end_dad_demo():
    from datetime import datetime, timezone
    from backend.async_persistence import AsyncAnalysisDB
    from backend.services.kline_cache_service import KlineCacheService
    from backend.diagnostics.parity.data_access import ParityDataAccess
    from backend.services.backtest.replay_runner import run_replay

    db = AsyncAnalysisDB(os.environ["DATABASE_URL"]); await db.connect()
    try:
        cfg = {"leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
               "stop_loss_pct": 100, "max_drawdown_pct": 12, "smart_drawdown_close": True,
               "trailing_profit_pct": 2, "breakeven_timeout_hours": None,
               "max_trade_duration_hours": 24, "min_score": 7, "confidence_filter": "moderate",
               "signal_sides": "both", "execution_mode": "batch", "fill_to_max_trades": True,
               "skip_if_positions_open": True, "adaptive_blacklist_enabled": True,
               "adaptive_blacklist_min_trades": 5, "adaptive_blacklist_max_win_rate": 30,
               "adaptive_blacklist_lookback_hours": 48, "target_goal_type": "profit_pct",
               "target_goal_value": 15, "max_price_drift_pct": None, "max_same_sector": 2,
               "max_same_direction": 3, "direction": "straight", "fee_rate_pct": 0.055,
               "slippage_bps": 2, "simulation_interval": "5m"}
        result, comp = await run_replay(
            ParityDataAccess(db), KlineCacheService(db),
            "75aecaa7-0f10-400b-a562-1ddd7ae6cf94",
            datetime(2026, 6, 4, 22, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 6, tzinfo=timezone.utc), cfg)
        assert comp["n_cycles"] == 17
        assert comp["pinned_trades"] == 51
        assert comp["pnl_correlation"] > 0.9            # high fidelity guard
        assert comp["directional_agreement"] >= 15
    finally:
        await db.close()
