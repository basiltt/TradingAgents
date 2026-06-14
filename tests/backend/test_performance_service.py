"""Unit tests for PerformanceService pure computation (spec §3/§4.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.performance_service import (
    classify_trades, compute_pnl_kpis,
    compute_starting_equity, compute_cumulative_curve, compute_drawdown_series,
    build_daily_return_series, compute_risk_ratios, resolve_timeframe_window,
    compute_max_consecutive,
    compute_daily_pnl, compute_monthly_pnl, compute_drawdown_duration,
)
# IMPORTANT (TDD import hygiene): import ONLY the helpers each task has implemented so far.
# A module-level import of a not-yet-defined name fails at pytest COLLECTION time (before
# any test runs), so `-k` can't bypass it. Each later task (1.6, 1.7, 1.8, 1.9) extends
# THIS import line with the names it adds in its own Step 1.


def _t(net_pnl, closed_at, *, realized=None, opened_at=None, base_capital=None,
       symbol="BTCUSDT", side="Buy", close_reason="take_profit",
       strategy_kind="trend", account_id="a1", _id=1):
    """Build a canonical-trade dict like get_performance_trades returns."""
    return {
        "id": _id, "account_id": account_id, "symbol": symbol, "side": side,
        "net_pnl": net_pnl, "realized_pnl": realized if realized is not None else net_pnl,
        "realized_pnl_pct": None, "base_capital": base_capital,
        "close_reason": close_reason, "strategy_kind": strategy_kind,
        "opened_at": opened_at, "closed_at": closed_at, "leverage": 20,
    }


class TestClassifyTrades:
    def test_win_loss_breakeven_null(self):
        trades = [_t(5.0, None, _id=1), _t(-3.0, None, _id=2),
                  _t(0.0, None, _id=3), _t(None, None, _id=4)]
        c = classify_trades(trades)
        assert c.win_count == 1
        assert c.loss_count == 1
        # breakeven (0) and null are neither win nor loss
        assert c.win_count + c.loss_count == 2
        assert len(trades) == 4  # but total_trades counts all 4 (asserted in compute_pnl_kpis)


class TestComputePnlKpis:
    def test_basic_reconciliation(self):
        # 2 wins (+4, +2), 1 loss (-3), 1 breakeven (0)
        trades = [_t(4.0, None, _id=1), _t(2.0, None, _id=2),
                  _t(-3.0, None, _id=3), _t(0.0, None, _id=4)]
        k = compute_pnl_kpis(trades)
        assert k["net_pnl"] == pytest.approx(3.0)
        assert k["total_trades"] == 4
        assert k["win_count"] == 2
        assert k["loss_count"] == 1
        assert k["win_rate"] == pytest.approx(50.0)  # 2/4
        assert k["avg_win"] == pytest.approx(3.0)     # (4+2)/2
        assert k["avg_loss"] == pytest.approx(-3.0)   # -3/1
        assert k["profit_factor"] == pytest.approx(2.0)  # 6/3
        assert k["expectancy"] == pytest.approx(0.75)    # 3/4

    def test_profit_factor_null_when_no_losses(self):
        k = compute_pnl_kpis([_t(4.0, None, _id=1)])
        assert k["profit_factor"] is None

    def test_null_net_pnl_coalesced_to_zero_in_sum(self):
        k = compute_pnl_kpis([_t(None, None, _id=1), _t(5.0, None, _id=2)])
        assert k["net_pnl"] == pytest.approx(5.0)
        assert k["total_trades"] == 2
        assert k["win_count"] == 1  # null is not a win


class TestStartingEquity:
    def test_prefers_cycle_equity_one_value_per_account(self):
        # account a1 has a cycle equity (100), a2 has none -> falls back to base_capital (50)
        D, contrib = compute_starting_equity(
            account_ids=["a1", "a2"],
            cycle_equity={"a1": 100.0},
            first_trade_capital={"a1": 999.0, "a2": 50.0},  # a1 ignores this (cycle wins)
        )
        assert D == pytest.approx(150.0)  # 100 + 50, NOT summed per-trade
        assert contrib == {"a1", "a2"}

    def test_null_account_excluded_returns_none_when_all_null(self):
        D, contrib = compute_starting_equity(account_ids=["a1"], cycle_equity={}, first_trade_capital={})
        assert D is None
        assert contrib == set()

    def test_partial_null_excludes_that_account(self):
        # a2 has no equity anywhere -> excluded from D AND from the contributing set
        D, contrib = compute_starting_equity(
            account_ids=["a1", "a2"], cycle_equity={"a1": 100.0}, first_trade_capital={},
        )
        assert D == pytest.approx(100.0)
        assert contrib == {"a1"}  # a2 excluded -> its P&L must NOT enter %/ratio numerators


class TestCumulativeCurve:
    def test_runs_from_zero_origin_ordered(self):
        trades = [_t(5.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-2.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2),
                  _t(3.0, datetime(2026, 5, 3, tzinfo=timezone.utc), _id=3)]
        curve = compute_cumulative_curve(trades)
        assert [round(p["cum_pnl"], 2) for p in curve] == [5.0, 3.0, 6.0]
        assert [round(p["peak"], 2) for p in curve] == [5.0, 5.0, 6.0]

    def test_null_pnl_coalesced(self):
        trades = [_t(None, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(4.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2)]
        curve = compute_cumulative_curve(trades)
        assert [round(p["cum_pnl"], 2) for p in curve] == [0.0, 4.0]


class TestDrawdownSeries:
    def test_peak_seeded_at_D_so_early_loss_registers(self):
        # D=100; first trade is a loss -> drawdown must be negative, NOT 0
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2)]
        series, dd_max = compute_drawdown_series(trades, D=100.0)
        # equity_proxy: 90, 95 ; peak seeded at D=100 -> 100,100
        assert series[0]["drawdown_pct"] == pytest.approx((90 - 100) / 100 * 100)  # -10.0
        assert dd_max["max_drawdown_pct"] == pytest.approx(-10.0)

    def test_naive_seed_would_hide_it_guard(self):
        # If peak were seeded at equity_proxy[0]=90 instead of D=100, first dd would be 0.
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1)]
        series, _ = compute_drawdown_series(trades, D=100.0)
        assert series[0]["drawdown_pct"] < 0  # proves D-seed, not equity_proxy[0]-seed

    def test_d_null_returns_abs_drawdown(self):
        trades = [_t(-10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1)]
        series, dd_max = compute_drawdown_series(trades, D=None)
        # absolute dollars under *_abs semantics; pct is None
        assert dd_max["max_drawdown_abs"] == pytest.approx(-10.0)
        assert dd_max["max_drawdown_pct"] is None


class TestMaxConsecutive:
    def test_per_trade_sequence_not_daily(self):
        # 3 wins in a row then a loss -> max_consecutive_wins = 3
        trades = [_t(1.0, None, _id=1), _t(2.0, None, _id=2), _t(3.0, None, _id=3),
                  _t(-1.0, None, _id=4)]
        w, l = compute_max_consecutive(trades)
        assert w == 3
        assert l == 1

    def test_breakeven_breaks_streak(self):
        trades = [_t(1.0, None, _id=1), _t(0.0, None, _id=2), _t(2.0, None, _id=3)]
        w, _ = compute_max_consecutive(trades)
        assert w == 1


class TestDailyReturnSeries:
    def test_forward_filled_calendar_days_first_seeded_at_D(self):
        # trades on day1 (+10) and day3 (+5); day2 has no trade -> 0% return that day
        D = 100.0
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 3, 8, tzinfo=timezone.utc), _id=2)]
        pairs = build_daily_return_series(trades, D=D)
        # returns (date, return_pct) pairs; day1 +10%, day2 (no trade) 0%, day3 ~4.545%
        assert len(pairs) == 3  # calendar-filled: 5/1, 5/2, 5/3
        rets = [r for (_d, r) in pairs]
        assert rets[0] == pytest.approx(10.0)
        assert rets[1] == pytest.approx(0.0)
        assert rets[2] == pytest.approx((115 - 110) / 110 * 100)


class TestRiskRatios:
    def test_null_below_10_trading_days(self):
        # only 2 trading days -> ratios null
        D = 100.0
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(5.0, datetime(2026, 5, 2, 8, tzinfo=timezone.utc), _id=2)]
        r = compute_risk_ratios(trades, D=D, max_drawdown_pct=-4.2)
        assert r["sharpe_ratio"] is None
        assert r["sortino_ratio"] is None
        assert r["calmar_ratio"] is None

    def test_calmar_uses_abs_drawdown_positive(self):
        # 11 distinct trading days, small positive returns, negative max_dd -> positive Calmar
        D = 100.0
        trades = [_t(1.0, datetime(2026, 5, d, 8, tzinfo=timezone.utc), _id=d)
                  for d in range(1, 12)]
        r = compute_risk_ratios(trades, D=D, max_drawdown_pct=-2.0)
        assert r["calmar_ratio"] is not None
        assert r["calmar_ratio"] > 0  # abs(max_dd) used

    def test_d_null_all_ratios_null(self):
        trades = [_t(1.0, datetime(2026, 5, d, 8, tzinfo=timezone.utc), _id=d)
                  for d in range(1, 12)]
        r = compute_risk_ratios(trades, D=None, max_drawdown_pct=None)
        assert r == {"sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None}


class TestTimeframeWindow:
    def test_all_has_no_lower_bound(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, a = resolve_timeframe_window("ALL", anchor)
        assert start is None
        assert a == anchor

    def test_1m_is_calendar_month(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("1M", anchor)
        assert start == datetime(2026, 5, 14, 12, tzinfo=timezone.utc)

    def test_1d_is_trailing_24h(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("1D", anchor)
        assert start == anchor - timedelta(hours=24)

    def test_ytd_is_jan1(self):
        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        start, _ = resolve_timeframe_window("YTD", anchor)
        assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            resolve_timeframe_window("7H", datetime(2026, 6, 14, tzinfo=timezone.utc))


class TestDailyMonthlyPnl:
    def test_daily_pnl_grouped_by_utc_day(self):
        trades = [_t(2.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
                  _t(1.0, datetime(2026, 5, 1, 20, tzinfo=timezone.utc), _id=2),
                  _t(-1.0, datetime(2026, 5, 2, 9, tzinfo=timezone.utc), _id=3)]
        daily = compute_daily_pnl(trades)
        assert daily == [{"date": "2026-05-01", "pnl": pytest.approx(3.0)},
                         {"date": "2026-05-02", "pnl": pytest.approx(-1.0)}]

    def test_monthly_pnl_with_return_pct(self):
        trades = [_t(8.0, datetime(2026, 5, 10, tzinfo=timezone.utc), _id=1)]
        monthly = compute_monthly_pnl(trades, D=160.0)
        assert monthly == [{"month": "2026-05", "pnl": pytest.approx(8.0),
                            "return_pct": pytest.approx(5.0)}]

    def test_monthly_return_pct_null_when_D_null(self):
        trades = [_t(8.0, datetime(2026, 5, 10, tzinfo=timezone.utc), _id=1)]
        monthly = compute_monthly_pnl(trades, D=None)
        assert monthly[0]["return_pct"] is None


class TestDrawdownDuration:
    def test_recovered_episode_floored_days(self):
        # peak at day1 (after +10), trough day2 (-6 -> 4), recover day5 (+8 -> 12 > 10 peak)
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-6.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2),
                  _t(8.0, datetime(2026, 5, 5, tzinfo=timezone.utc), _id=3)]
        days, recovered = compute_drawdown_duration(trades, D=100.0)
        assert recovered is True
        assert days == 4  # 5/1 peak -> 5/5 recovery = 4 days, floored

    def test_unrecovered_uses_last_in_window(self):
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1),
                  _t(-6.0, datetime(2026, 5, 4, tzinfo=timezone.utc), _id=2)]
        days, recovered = compute_drawdown_duration(trades, D=100.0)
        assert recovered is False
        assert days == 3  # 5/1 peak -> 5/4 last trade


class TestComputeOverview:
    @pytest.mark.asyncio
    async def test_overview_from_trades_no_live_call(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        trades = [_t(10.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1, account_id="a1"),
                  _t(-4.0, datetime(2026, 5, 2, 8, tzinfo=timezone.utc), _id=2, account_id="a1"),
                  _t(6.0, datetime(2026, 5, 3, 8, tzinfo=timezone.utc), _id=3, account_id="a1")]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(side_effect=RuntimeError("bybit down"))

        svc = PerformanceService(db=db, accounts_service=accounts)
        result = await svc.compute_overview(scope="all", timeframe="ALL", anchor=anchor)

        assert result["kpis"]["net_pnl"] == pytest.approx(12.0)
        assert result["kpis"]["total_trades"] == 3
        assert result["kpis"]["total_equity"] is None
        assert result["meta"]["degraded"] is True
        assert result["meta"]["starting_equity"] == pytest.approx(100.0)
        assert len(result["equity_curve"]) == 3
        assert result["meta"]["currency"] == "USDT"

    @pytest.mark.asyncio
    async def test_window_slices_not_rebases(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        all_trades = [
            _t(14.0, datetime(2026, 4, 1, 8, tzinfo=timezone.utc), _id=1, account_id="a1"),
            _t(10.0, datetime(2026, 5, 20, 8, tzinfo=timezone.utc), _id=2, account_id="a1"),
            _t(2.0, datetime(2026, 6, 1, 8, tzinfo=timezone.utc), _id=3, account_id="a1"),
        ]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades = AsyncMock(return_value=all_trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(side_effect=RuntimeError("down"))
        svc = PerformanceService(db=db, accounts_service=accounts)
        result = await svc.compute_overview(scope="all", timeframe="1M", anchor=anchor)
        assert result["kpis"]["net_pnl"] == pytest.approx(12.0)
        assert result["equity_curve"][0]["cum_pnl"] == pytest.approx(24.0)
        assert result["equity_curve"][-1]["cum_pnl"] == pytest.approx(26.0)

    @pytest.mark.asyncio
    async def test_single_account_empty_scope_does_not_leak_all(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=[])
        db.get_performance_trades = AsyncMock(return_value=[
            _t(99.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1, account_id="other")])
        db.get_account_first_cycle_equity = AsyncMock(return_value={})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="acc_bad", timeframe="ALL", anchor=anchor)
        assert result["kpis"]["total_trades"] == 0
        assert result["kpis"]["net_pnl"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_aggregate_null_D_account_does_not_inflate_return(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1, account_id="a1"),
                  _t(90.0, datetime(2026, 5, 2, tzinfo=timezone.utc), _id=2, account_id="a2")]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1", "a2"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="all", timeframe="ALL", anchor=anchor)
        assert result["kpis"]["net_pnl"] == pytest.approx(100.0)
        assert result["kpis"]["total_return_pct"] == pytest.approx(10.0)
        assert result["meta"]["starting_equity"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_null_D_scope_still_reports_absolute_drawdown(self):
        # Regression: when no account has a starting equity (D None), the curve still shows
        # dips, so the ABSOLUTE-dollar drawdown must be computed over the in-scope trades --
        # NOT left at $0.00 (which previously happened because the D-relative subset was
        # empty). Trades: +10 then -40 -> a $40 absolute drawdown from the running peak.
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        trades = [_t(10.0, datetime(2026, 5, 1, tzinfo=timezone.utc), _id=1, account_id="a1",
                     opened_at=datetime(2026, 5, 1, tzinfo=timezone.utc)),
                  _t(-40.0, datetime(2026, 5, 5, tzinfo=timezone.utc), _id=2, account_id="a1",
                     opened_at=datetime(2026, 5, 5, tzinfo=timezone.utc))]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={})  # no cycle
        db.get_account_first_trade_capital = AsyncMock(return_value={})  # no base_capital -> D None
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="all", timeframe="ALL", anchor=anchor)
        k = result["kpis"]
        assert result["meta"]["starting_equity"] is None     # D is None
        assert k["max_drawdown_pct"] is None                 # no %-basis without D
        # absolute drawdown reflects the real dip (peak +10 -> trough -30 = -40), not 0.0
        assert k["max_drawdown_abs"] == pytest.approx(-40.0)
        assert len(result["drawdown_series"]) == 2           # series populated, not empty
        # duration is computed on the abs path too (no longer forced to None)
        assert k["drawdown_duration_days"] is not None

    @pytest.mark.asyncio
    async def test_kpis_prev_windows_only_prior_period_and_excludes_null_D(self):
        # Value-level guard for _compute_prev (the hero delta engine): the prior equal-length
        # window must count ONLY prior-window trades, and a null-D account's P&L must not
        # enter the D-relative total_equity proxy (aggregate null-D rule).
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        # 1M window => current = [2026-05-14, anchor); prev = [2026-04-14, 2026-05-14)
        trades = [
            # prior window (a1 contributes to D; a2 is null-D)
            _t(7.0, datetime(2026, 4, 20, 8, tzinfo=timezone.utc), _id=1, account_id="a1"),
            _t(3.0, datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=2, account_id="a1"),
            _t(50.0, datetime(2026, 4, 25, 8, tzinfo=timezone.utc), _id=3, account_id="a2"),
            # current window (must NOT count toward prev)
            _t(99.0, datetime(2026, 6, 1, 8, tzinfo=timezone.utc), _id=4, account_id="a1"),
            # before prev window (must NOT count toward prev)
            _t(11.0, datetime(2026, 3, 1, 8, tzinfo=timezone.utc), _id=5, account_id="a1"),
        ]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1", "a2"])
        db.get_performance_trades = AsyncMock(return_value=trades)
        db.get_account_first_cycle_equity = AsyncMock(return_value={"a1": 100.0})  # only a1 -> D=100
        db.get_account_first_trade_capital = AsyncMock(return_value={})
        svc = PerformanceService(db=db, accounts_service=None)
        result = await svc.compute_overview(scope="all", timeframe="1M", anchor=anchor)
        prev = result["kpis_prev"]
        assert prev is not None
        # net_pnl/total_trades count ONLY the prior WINDOW [2026-04-14, 2026-05-14): 7+3+50.
        # (current-window id=4 and pre-window id=5 are excluded from these.)
        assert prev["net_pnl"] == pytest.approx(60.0)
        assert prev["total_trades"] == 3
        # total_equity is the realized equity PROXY at prev-window-end (spec §10): D + ALL
        # D-relative (a1) realized P&L up to prev_end = 100 + (7 + 3 + 11) = 121. The older
        # a1 trade id=5 IS in the cumulative proxy; a2's 50 is excluded (a2 is null-D).
        assert prev["total_equity"] == pytest.approx(121.0)


class TestComputeBreakdowns:
    def test_by_symbol_strategy_close_reason(self):
        from backend.services.performance_service import compute_breakdowns
        trades = [
            _t(5.0, datetime(2026, 5, 1, 10, tzinfo=timezone.utc), symbol="BTCUSDT",
               strategy_kind="trend", close_reason="take_profit",
               opened_at=datetime(2026, 5, 1, 8, tzinfo=timezone.utc), _id=1),
            _t(-2.0, datetime(2026, 5, 2, 10, tzinfo=timezone.utc), symbol="BTCUSDT",
               strategy_kind="trend", close_reason="stop_loss",
               opened_at=datetime(2026, 5, 2, 8, tzinfo=timezone.utc), _id=2),
            _t(3.0, datetime(2026, 5, 3, 10, tzinfo=timezone.utc), symbol="ETHUSDT",
               strategy_kind="mean_reversion", close_reason="take_profit",
               opened_at=datetime(2026, 5, 3, 6, tzinfo=timezone.utc), _id=3),
        ]
        b = compute_breakdowns(trades)
        by_sym = {r["symbol"]: r for r in b["by_symbol"]}
        assert by_sym["BTCUSDT"]["trades"] == 2
        assert by_sym["BTCUSDT"]["pnl"] == pytest.approx(3.0)
        assert by_sym["BTCUSDT"]["win_rate"] == pytest.approx(50.0)
        by_strat = {r["strategy"]: r for r in b["by_strategy"]}
        assert by_strat["trend"]["trades"] == 2
        by_reason = {r["reason"]: r for r in b["by_close_reason"]}
        assert by_reason["take_profit"]["count"] == 2
        assert "trailing" not in by_reason  # no invented bucket
        # distribution + hold-time present
        assert isinstance(b["pnl_distribution"], list)
        assert isinstance(b["hold_time_buckets"], list)

    def test_legacy_strategy_flag_key_present(self):
        from backend.services.performance_service import compute_breakdowns
        b = compute_breakdowns([])
        assert "strategy_legacy_approximate" in b["meta"]


class TestComputeTradesPage:
    @pytest.mark.asyncio
    async def test_paginates_and_shapes_rows(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        anchor = datetime(2026, 6, 14, 12, tzinfo=timezone.utc)
        rows = [
            {"id": "t1", "symbol": "BTCUSDT", "side": "Buy", "net_pnl": 5.0,
             "base_capital": 100.0, "close_reason": "take_profit",
             "opened_at": datetime(2026, 5, 1, 8, tzinfo=timezone.utc),
             "closed_at": datetime(2026, 5, 1, 14, tzinfo=timezone.utc)},
            {"id": "t2", "symbol": "ETHUSDT", "side": "Sell", "net_pnl": None,
             "base_capital": None, "close_reason": "external",
             "opened_at": None,
             "closed_at": datetime(2026, 5, 2, 9, tzinfo=timezone.utc)},
        ]
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_performance_trades_page = AsyncMock(return_value=(rows, "nextcur", True))
        svc = PerformanceService(db=db, accounts_service=None)
        res = await svc.compute_trades_page(scope="all", timeframe="ALL", anchor=anchor,
                                            sort="net_pnl", direction="desc", cursor=None, limit=50)
        assert res["cursor"] == "nextcur"
        assert res["has_more"] is True
        r0 = res["rows"][0]
        assert r0["id"] == "t1"
        assert r0["net_pnl"] == pytest.approx(5.0)
        assert r0["net_pnl_pct"] == pytest.approx(5.0)   # 5/100*100
        assert r0["hold_hours"] == pytest.approx(6.0)
        # null base_capital -> net_pnl_pct None; null opened_at -> hold None
        r1 = res["rows"][1]
        assert r1["net_pnl_pct"] is None
        assert r1["hold_hours"] is None


class TestComputeLive:
    @pytest.mark.asyncio
    async def test_fail_soft_one_account_raises(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1", "a2"])
        db.get_symbol_sectors = AsyncMock(return_value={"BTCUSDT": "L1"})
        accounts = MagicMock()
        # dashboard provides tiles for both accounts
        accounts.get_dashboard = AsyncMock(return_value=[
            {"id": "a1", "label": "A1", "account_type": "live", "total_equity": "100",
             "today_pnl": "1.2", "positions_count": 1},
            {"id": "a2", "label": "A2", "account_type": "demo", "total_equity": "50",
             "today_pnl": "0", "positions_count": 0},
        ])
        # a1 positions OK; a2 raises -> degraded, but a1 still present
        async def _positions(acc_id):
            if acc_id == "a2":
                raise RuntimeError("bybit down for a2")
            return [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1",
                     "leverage": "20", "avgPrice": "2950", "unrealisedPnl": "-1.6",
                     "positionValue": "295"}]
        accounts.get_positions = AsyncMock(side_effect=_positions)

        svc = PerformanceService(db=db, accounts_service=accounts)
        res = await svc.compute_live(scope="all")

        assert res["degraded"] is True
        # a1's position present
        assert any(p["symbol"] == "BTCUSDT" for p in res["positions"])
        # both tiles present; a2 carries an error
        tiles = {t["account_id"]: t for t in res["account_tiles"]}
        assert tiles["a2"]["error"] is not None
        assert tiles["a1"]["error"] is None
        # sector concentration computed from positions
        assert any(s["sector"] == "L1" for s in res["sector_concentration"])

    @pytest.mark.asyncio
    async def test_no_accounts_service_is_fully_degraded(self):
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService
        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        svc = PerformanceService(db=db, accounts_service=None)
        res = await svc.compute_live(scope="all")
        assert res["degraded"] is True
        assert res["positions"] == []

    @pytest.mark.asyncio
    async def test_upl_pct_derived_from_size_times_entry_not_position_value(self):
        # Regression: bybit_client.get_positions never returns `positionValue`, so the
        # unrealized % MUST be derived from size*entry. A dict WITHOUT positionValue must
        # still produce a non-null upl_pct (previously it was always None).
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_symbol_sectors = AsyncMock(return_value={"BTCUSDT": "l1"})
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(return_value=[
            {"id": "a1", "label": "A1", "account_type": "live", "total_equity": "100",
             "today_pnl": "1", "positions_count": 1}])
        accounts.get_positions = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "leverage": "20",
             "avgPrice": "2950", "unrealisedPnl": "-1.6"}])  # NO positionValue key
        svc = PerformanceService(db=db, accounts_service=accounts)
        res = await svc.compute_live(scope="all")
        pos = res["positions"][0]
        # notional = 0.1*2950 = 295 ; upl_pct = -1.6/295*100
        assert pos["unrealized_pnl_pct"] == pytest.approx(-1.6 / 295 * 100)
        assert res["degraded"] is False

    @pytest.mark.asyncio
    async def test_malformed_card_equity_does_not_500_the_tab(self):
        # Regression (fail-soft): a non-numeric card money string must coerce to None,
        # not raise -- tile construction is outside the per-account try/except.
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService

        db = MagicMock()
        db.get_scope_account_ids = AsyncMock(return_value=["a1"])
        db.get_symbol_sectors = AsyncMock(return_value={})
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(return_value=[
            {"id": "a1", "label": "A1", "account_type": "live",
             "total_equity": "N/A", "today_pnl": "1,234.5", "positions_count": "oops"}])
        accounts.get_positions = AsyncMock(return_value=[])
        svc = PerformanceService(db=db, accounts_service=accounts)
        res = await svc.compute_live(scope="all")  # must not raise
        tile = res["account_tiles"][0]
        assert tile["equity"] is None          # "N/A" -> None
        assert tile["today_pnl"] is None        # "1,234.5" unparseable -> None
        assert tile["positions_count"] == 0     # "oops" -> 0


class TestLiveOverlay:
    @pytest.mark.asyncio
    async def test_partial_overlay_sums_reporting_accounts_and_degrades(self):
        # Regression (M1): one disabled account (total_equity None) must NOT blank the whole
        # scope -- sum the accounts that reported and flag degraded.
        from unittest.mock import AsyncMock, MagicMock
        from backend.services.performance_service import PerformanceService
        accounts = MagicMock()
        accounts.get_dashboard = AsyncMock(return_value=[
            {"id": "a1", "total_equity": "100", "total_perp_upl": "5", "positions_count": 2},
            {"id": "a2", "total_equity": None, "total_perp_upl": None, "positions_count": None},
        ])
        svc = PerformanceService(db=MagicMock(), accounts_service=accounts)
        overlay, degraded = await svc._live_overlay(["a1", "a2"])
        assert overlay["total_equity"] == pytest.approx(100.0)  # a1 only, a2 not nulled away
        assert overlay["open_count"] == 2
        assert degraded is True  # a2 missing


class TestStartingEquityFallback:
    def test_nonpositive_cycle_equity_falls_back_to_first_trade_capital(self):
        # Regression: a junk cycle row (initial_equity 0 or negative) must not suppress the
        # base_capital fallback or silently drop the account from D.
        from backend.services.performance_service import compute_starting_equity
        D, contrib = compute_starting_equity(
            account_ids=["a1", "a2"],
            cycle_equity={"a1": 0.0, "a2": -5.0},
            first_trade_capital={"a1": 80.0, "a2": 50.0},
        )
        assert D == pytest.approx(130.0)
        assert contrib == {"a1", "a2"}
