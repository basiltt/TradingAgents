import pytest
from pydantic import ValidationError
from backend.schemas.backtest_schemas import ScanSource


def test_replay_mode_requires_account_id():
    with pytest.raises(ValidationError):
        ScanSource(mode="replay")            # no replay_account_id


def test_replay_mode_valid():
    s = ScanSource(mode="replay", replay_account_id="75aecaa7-0f10-400b-a562-1ddd7ae6cf94")
    assert s.mode == "replay"
    assert s.replay_account_id == "75aecaa7-0f10-400b-a562-1ddd7ae6cf94"


def test_existing_modes_unaffected():
    assert ScanSource(mode="schedule", schedule_id="x").mode == "schedule"
    assert ScanSource(mode="explicit", scan_ids=["a"]).mode == "explicit"


@pytest.mark.asyncio
async def test_replay_runner_builds_comparison_from_fakes():
    from datetime import datetime, timezone
    from backend.services.backtest.replay_runner import run_replay

    def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    # Fake data-access returning one cycle of 2 pinned trades + their signals + klines.
    class FakeDA:
        async def fetch_live_trades(self, account_id, start, end):
            return [
                dict(symbol="A", side="Sell", net_pnl=10.0, close_reason="rule_triggered",
                     entry_price=100.0, exit_price=99.0, scan_result_id=1, status="closed",
                     base_capital=200.0, scan_id="s1", signal_time=_dt("2026-06-05T01:00:00"),
                     opened_at=_dt("2026-06-05T01:01:00"), closed_at=_dt("2026-06-05T02:00:00")),
                dict(symbol="B", side="Sell", net_pnl=12.0, close_reason="rule_triggered",
                     entry_price=50.0, exit_price=49.0, scan_result_id=2, status="closed",
                     base_capital=200.0, scan_id="s1", signal_time=_dt("2026-06-05T01:00:00"),
                     opened_at=_dt("2026-06-05T01:01:10"), closed_at=_dt("2026-06-05T02:00:00")),
            ]
        async def fetch_signals(self, scan_ids):
            t = _dt("2026-06-05T01:00:00")
            return [
                {"scan_id": "s1", "ticker": "A", "direction": "sell", "score": -8,
                 "signal_time": t, "id": 1, "analysis_completed_at": None, "analysis_price": 100.0},
                {"scan_id": "s1", "ticker": "B", "direction": "sell", "score": -8,
                 "signal_time": t, "id": 2, "analysis_completed_at": None, "analysis_price": 50.0},
            ]
        async def fetch_klines(self, kline_cache, symbols, start, end, interval="5m"):
            # Flat candles so the engine holds to backtest_end; PnL ~ entry vs last close.
            t0 = _dt("2026-06-05T01:05:00")
            from datetime import timedelta
            def series(p): return [{"open_time": t0 + timedelta(minutes=5*i),
                                    "open": p, "high": p, "low": p, "close": p, "volume": 1.0}
                                   for i in range(40)]
            return {"A": series(99.0), "B": series(49.0)}
        async def build_fine_klines(self, *a, **k): return {}

    config = {"leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
              "stop_loss_pct": 100, "max_drawdown_pct": 100, "execution_mode": "batch",
              "fill_to_max_trades": True, "skip_if_positions_open": True, "min_score": 7,
              "confidence_filter": "any", "signal_sides": "both", "direction": "straight",
              "fee_rate_pct": 0.055, "slippage_bps": 0, "simulation_interval": "5m",
              "max_price_drift_pct": None, "breakeven_timeout_hours": None}

    result, comparison = await run_replay(
        FakeDA(), kline_cache=None, account_id="acct",
        start=_dt("2026-06-04T22:00:00Z"), end=_dt("2026-06-10T06:00:00Z"),
        base_config=config)

    assert comparison["n_cycles"] == 1
    assert comparison["pinned_trades"] == 2
    assert len(comparison["cycles"]) == 1
    c0 = comparison["cycles"][0]
    assert c0["scan_id"] == "s1"
    assert "live_net_pnl" in c0 and "backtest_net_pnl" in c0 and "delta_pct" in c0
    assert "final_equity_delta_pct" in comparison
    # result carries engine trades for the normal results dashboard
    assert "trades" in result
