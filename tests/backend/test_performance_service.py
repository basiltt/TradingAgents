"""Unit tests for PerformanceService pure computation (spec §3/§4.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.performance_service import (
    classify_trades, compute_pnl_kpis,
    compute_starting_equity, compute_cumulative_curve, compute_drawdown_series,
    build_daily_return_series, compute_risk_ratios, resolve_timeframe_window,
    compute_max_consecutive,
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
