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
                     opened_at=_dt("2026-06-05T01:01:00"), closed_at=_dt("2026-06-05T02:00:00"),
                     exchange_closed_pnl=11.0),
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
              "max_price_drift_pct": None, "breakeven_timeout_hours": None,
              "starting_capital": 150.0}

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
    # result carries the live ledger for the normal results dashboard; the candle
    # engine stays in replay_comparison as the diagnostic comparison.
    assert [t["pnl"] for t in result["trades"]] == [11.0, 12.0]
    assert result["starting_capital"] == 200.0
    assert result["equity_curve"][-1]["equity"] == 223.0
    # data-integrity disclosure keys are present
    assert "missing_pins" in comparison and "excluded_trades" in comparison


@pytest.mark.asyncio
async def test_replay_runner_raises_on_no_cycles():
    from backend.services.backtest.replay_runner import run_replay, ReplayError
    from datetime import datetime, timezone

    def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    class EmptyDA:
        async def fetch_live_trades(self, account_id, start, end): return []
        async def fetch_excluded_counts(self, account_id, start, end):
            return {"excluded_non_scanner_or_ai": 5, "scanner_without_scan_row": 0}

    with pytest.raises(ReplayError):
        await run_replay(EmptyDA(), kline_cache=None, account_id="acct",
                         start=_dt("2026-06-04T22:00:00Z"), end=_dt("2026-06-10T06:00:00Z"),
                         base_config={})


@pytest.mark.asyncio
async def test_replay_runner_uses_run_sync_wrapper():
    """When a run_sync wrapper is supplied, the CPU-bound cycle replay goes through it
    (the service passes loop.run_in_executor so the engine never blocks the loop)."""
    from backend.services.backtest.replay_runner import run_replay
    from datetime import datetime, timezone

    def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    class FakeDA:
        async def fetch_live_trades(self, account_id, start, end):
            return [dict(symbol="A", side="Sell", net_pnl=1.0, close_reason="rule_triggered",
                         entry_price=100.0, exit_price=99.0, scan_result_id=1, status="closed",
                         base_capital=200.0, scan_id="s1", signal_time=_dt("2026-06-05T01:00:00"),
                         opened_at=_dt("2026-06-05T01:01:00"), closed_at=_dt("2026-06-05T02:00:00"))]
        async def fetch_signals(self, scan_ids):
            t = _dt("2026-06-05T01:00:00")
            return [{"scan_id": "s1", "ticker": "A", "direction": "sell", "score": -8,
                     "signal_time": t, "id": 1, "analysis_completed_at": None, "analysis_price": 100.0}]
        async def fetch_klines(self, kline_cache, symbols, start, end, interval="5m"):
            from datetime import timedelta
            t0 = _dt("2026-06-05T01:05:00")
            return {"A": [{"open_time": t0 + timedelta(minutes=5 * i), "open": 99.0,
                           "high": 99.0, "low": 99.0, "close": 99.0, "volume": 1.0}
                          for i in range(20)]}

    used = {"called": False}
    async def fake_run_sync(fn):
        used["called"] = True
        return fn()

    cfg = {"leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
           "stop_loss_pct": 100, "max_drawdown_pct": 100, "execution_mode": "batch",
           "fill_to_max_trades": True, "skip_if_positions_open": True, "min_score": 7,
           "confidence_filter": "any", "signal_sides": "both", "direction": "straight",
           "fee_rate_pct": 0.055, "slippage_bps": 0, "simulation_interval": "5m",
           "max_price_drift_pct": None, "breakeven_timeout_hours": None}
    result, comparison = await run_replay(
        FakeDA(), kline_cache=None, account_id="acct",
        start=_dt("2026-06-04T22:00:00Z"), end=_dt("2026-06-10T06:00:00Z"),
        base_config=cfg, run_sync=fake_run_sync)
    assert used["called"] is True
    assert comparison["n_cycles"] == 1


@pytest.mark.asyncio
async def test_parity_data_access_warms_klines_before_read():
    """Selective replay must not silently simulate only already-cached symbols."""
    from datetime import datetime, timezone
    from backend.diagnostics.parity.data_access import ParityDataAccess

    class FakeKlineCache:
        def __init__(self):
            self.calls = []

        async def ensure_coverage(self, symbols, interval, start, end):
            self.calls.append(("ensure", tuple(symbols), interval, start, end))
            return {"cached": len(symbols), "fetched": 0, "failed": 0}

        async def get_klines(self, symbol, interval, start, end):
            self.calls.append(("get", symbol, interval, start, end))
            return [{"open_time": start, "open": 1.0, "high": 1.0,
                     "low": 1.0, "close": 1.0, "volume": 1.0}]

    start = datetime(2026, 6, 5, tzinfo=timezone.utc)
    end = datetime(2026, 6, 10, tzinfo=timezone.utc)
    cache = FakeKlineCache()

    klines = await ParityDataAccess(db=None).fetch_klines(
        cache, ["B", "A", "A"], start, end, "5m")

    assert set(klines) == {"A", "B"}
    assert cache.calls[0][0] == "ensure"
    assert cache.calls[0][1] == ("A", "B")
    assert [c[0] for c in cache.calls[1:]] == ["get", "get"]


def test_pin_signals_anchors_to_first_live_open():
    from datetime import datetime, timezone
    from backend.diagnostics.parity.models import Cycle, LiveTrade
    from backend.diagnostics.parity.shim import pin_signals

    scan_time = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
    first_open = datetime(2026, 6, 5, 1, 8, tzinfo=timezone.utc)
    later_open = datetime(2026, 6, 5, 1, 9, tzinfo=timezone.utc)
    cycles = [Cycle(
        scan_id="s1",
        signal_time=scan_time,
        base_capital=200.0,
        live_trades=[
            LiveTrade("A", "Sell", 1.0, "rule_triggered", 100.0, 99.0, 1, later_open, later_open),
            LiveTrade("B", "Sell", 1.0, "rule_triggered", 50.0, 49.0, 2, first_open, later_open),
        ],
    )]
    signals = [
        {"scan_id": "s1", "ticker": "A", "direction": "sell", "signal_time": scan_time},
        {"scan_id": "s1", "ticker": "B", "direction": "sell", "signal_time": scan_time},
    ]

    pinned = pin_signals(signals, cycles)

    assert len(pinned) == 2
    assert {s["signal_time"] for s in pinned} == {first_open}
