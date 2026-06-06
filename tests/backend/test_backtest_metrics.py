"""Tests for backtest metrics computation — TradingView-parity metrics."""

import pytest
from datetime import datetime, timezone, timedelta


def _make_trade(symbol="BTCUSDT", side="Buy", pnl=100.0, entry_time=None, exit_time=None,
                fees_paid=2.0, entry_price=50000.0, exit_price=50500.0, **overrides):
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = {
        "symbol": symbol, "side": side, "entry_price": entry_price, "exit_price": exit_price,
        "qty": 0.1, "leverage": 20,
        "entry_time": entry_time or base_time,
        "exit_time": exit_time or (base_time + timedelta(hours=2)),
        "pnl": pnl, "pnl_pct": pnl / 500 * 100, "fees_paid": fees_paid,
        "close_reason": "tp" if pnl > 0 else "sl",
        "mfe_pct": 5.0, "mae_pct": -2.0, "signal_score": 8, "signal_confidence": "high",
        "scan_id": "s1",
    }
    base.update(overrides)
    return base


def _make_equity_curve(values):
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {"ts": base_time + timedelta(hours=i), "equity": v, "drawdown_pct": 0.0}
        for i, v in enumerate(values)
    ]


def _assert_json_safe(m):
    """No Infinity/NaN may EVER appear anywhere in the metrics output, and it
    must serialize as strict JSON (no Infinity/NaN literals)."""
    import math, json

    def walk(v):
        if isinstance(v, float):
            assert math.isfinite(v), f"non-finite float in output: {v}"
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(m)
    json.dumps(m, allow_nan=False)


class TestComputeAllMetrics:
    """Test the main compute_all_metrics function."""

    def test_basic_metrics_present(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=-50.0), _make_trade(pnl=200.0)]
        equity = _make_equity_curve([10000, 10100, 10050, 10250])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        # Core metrics must be present
        assert "net_profit" in m
        assert "win_rate" in m
        assert "profit_factor" in m
        assert "total_trades" in m
        assert m["total_trades"] == 3
        assert m["winners"] == 2
        assert m["losers"] == 1

    def test_net_profit_calculation(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=200.0)]
        equity = _make_equity_curve([10000, 10300])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        assert abs(m["net_profit"] - 300.0) < 0.01
        assert abs(m["net_profit_pct"] - 3.0) < 0.01  # 300/10000

    def test_win_rate(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=-50.0),
                  _make_trade(pnl=100.0), _make_trade(pnl=100.0)]
        equity = _make_equity_curve([10000, 10250])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        assert abs(m["win_rate"] - 75.0) < 0.01  # 3/4

    def test_profit_factor(self):
        from backend.services.backtest_metrics import compute_all_metrics
        # gross profit = 300, gross loss = 100 → PF = 3.0
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=200.0), _make_trade(pnl=-100.0)]
        equity = _make_equity_curve([10000, 10200])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        assert abs(m["profit_factor"] - 3.0) < 0.01


class TestEdgeCases:
    """Test edge cases per spec FR-006."""

    def test_zero_trades(self):
        from backend.services.backtest_metrics import compute_all_metrics
        equity = _make_equity_curve([10000])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics([], equity, config)
        assert m["total_trades"] == 0
        assert m["win_rate"] is None
        assert m["sharpe"] is None

    def test_one_trade_sharpe_none(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0)]
        equity = _make_equity_curve([10000, 10100])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        # Two same-day equity points → 1 daily return → <2 → Sharpe is exactly None
        assert m["sharpe"] is None

    def test_all_wins_profit_factor_none(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=200.0)]
        equity = _make_equity_curve([10000, 10300])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        # No losses → profit factor = None (NOT Infinity, which breaks JSON/JSONB)
        assert m["profit_factor"] is None
        import math
        # Verify NO infinity anywhere in metrics (JSON-safe)
        for k, v in m.items():
            if isinstance(v, float):
                assert math.isfinite(v), f"{k}={v} is not JSON-safe"

    def test_zero_trades_schema_parity(self):
        """Zero-trades metrics must have SAME keys as a normal run (no KeyError downstream)."""
        from backend.services.backtest_metrics import compute_all_metrics
        normal = compute_all_metrics(
            [_make_trade(pnl=100.0), _make_trade(pnl=-50.0)],
            _make_equity_curve([10000, 10050]),
            {"starting_capital": 10000.0},
        )
        empty = compute_all_metrics([], _make_equity_curve([10000]), {"starting_capital": 10000.0})
        # Symmetric parity: NEITHER path may have a key the other lacks (top-level)
        diff = set(normal.keys()) ^ set(empty.keys())
        assert not diff, f"Zero-trades schema drift (symmetric diff): {diff}"
        # And the nested by_direction sub-dicts must match key-for-key too
        for k in ("all", "long", "short"):
            ndiff = set(normal["by_direction"][k].keys()) ^ set(empty["by_direction"][k].keys())
            assert not ndiff, f"by_direction[{k}] schema drift: {ndiff}"

    def test_all_losses(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=-100.0), _make_trade(pnl=-50.0)]
        equity = _make_equity_curve([10000, 9850])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        assert m["win_rate"] == 0.0
        assert m["winners"] == 0
        assert m["losers"] == 2


class TestSharpeSortino:
    """Test risk-adjusted return metrics."""

    def test_sharpe_returns_float_or_none(self):
        from backend.services.backtest_metrics import compute_sharpe
        import math
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]
        result = compute_sharpe(returns)
        # Lock the exact value: mean=0.012, sample std (n-1), ×√365
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        expected = (mean / math.sqrt(var)) * math.sqrt(365)
        assert result is not None
        assert abs(result - expected) < 1e-9
        # Independent hardcoded ORACLE anchor (not derived from the impl's formula):
        # confirms the sample-std (n-1) + √365 convention, not just self-consistency.
        assert abs(result - 15.4567) < 0.001

    def test_sharpe_none_for_insufficient_data(self):
        from backend.services.backtest_metrics import compute_sharpe
        assert compute_sharpe([0.01]) is None
        assert compute_sharpe([]) is None

    def test_sharpe_none_for_zero_std(self):
        from backend.services.backtest_metrics import compute_sharpe
        # All-identical returns → std 0 → None (not inf/nan)
        assert compute_sharpe([0.01, 0.01, 0.01]) is None

    def test_sharpe_nonzero_risk_free(self):
        from backend.services.backtest_metrics import compute_sharpe
        import math
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]
        rf = 0.005
        result = compute_sharpe(returns, risk_free=rf)
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        expected = ((mean - rf) / math.sqrt(var)) * math.sqrt(365)
        assert result is not None
        assert abs(result - expected) < 1e-9
        # Non-zero rf must LOWER the ratio vs rf=0 (catches a dropped `- risk_free`)
        assert result < compute_sharpe(returns, risk_free=0.0)

    def test_sortino_nonzero_risk_free(self):
        from backend.services.backtest_metrics import compute_sortino
        import math
        returns = [0.01, 0.02, -0.01, 0.03, -0.02]
        rf = 0.005
        result = compute_sortino(returns, risk_free=rf)
        mean = sum(returns) / len(returns)
        downside = [r for r in returns if r < rf]  # note: threshold is rf, not 0
        dd = math.sqrt(sum((r - rf) ** 2 for r in downside) / len(returns))
        expected = ((mean - rf) / dd) * math.sqrt(365)
        assert result is not None
        assert abs(result - expected) < 1e-9

    def test_sortino_returns_float_or_none(self):
        from backend.services.backtest_metrics import compute_sortino
        import math
        returns = [0.01, 0.02, -0.01, 0.03, -0.02]
        result = compute_sortino(returns)
        # Lock exact value: downside={-0.01,-0.02}, downside_var=sum(r^2)/N(total), ×√365
        mean = sum(returns) / len(returns)
        downside = [r for r in returns if r < 0]
        dd = math.sqrt(sum(r ** 2 for r in downside) / len(returns))
        expected = (mean / dd) * math.sqrt(365)
        assert result is not None
        assert abs(result - expected) < 1e-9
        # Independent hardcoded ORACLE anchor (confirms downside-dev÷total-N × √365):
        assert abs(result - 11.4630) < 0.001

    def test_sortino_all_positive_returns_none(self):
        from backend.services.backtest_metrics import compute_sortino
        # No downside periods → Sortino undefined → None (consistent with
        # profit_factor's no-loss handling), NOT a giant arbitrary number.
        returns = [0.01, 0.02, 0.03]
        assert compute_sortino(returns) is None


class TestMaxDrawdown:
    """Test drawdown computation."""

    def test_max_drawdown_basic(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        # Peak 10300, trough 9800 → drawdown
        equity = _make_equity_curve([10000, 10300, 9800, 10100])
        result = compute_max_drawdown(equity)
        assert "max_dd_pct" in result
        assert "max_dd_usd" in result
        # Max DD = (10300 - 9800) / 10300 = 4.85%
        assert abs(result["max_dd_pct"] - 4.854) < 0.1

    def test_no_drawdown_when_monotonic(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        equity = _make_equity_curve([10000, 10100, 10200, 10300])
        result = compute_max_drawdown(equity)
        assert result["max_dd_pct"] == 0.0


class TestStreaks:
    """Test consecutive win/loss streaks."""

    def test_max_consecutive_wins(self):
        from backend.services.backtest_metrics import compute_streaks
        trades = [_make_trade(pnl=100), _make_trade(pnl=100), _make_trade(pnl=100),
                  _make_trade(pnl=-50), _make_trade(pnl=100)]
        result = compute_streaks(trades)
        assert result["max_consecutive_wins"] == 3
        assert result["max_consecutive_losses"] == 1

    def test_max_consecutive_losses(self):
        from backend.services.backtest_metrics import compute_streaks
        trades = [_make_trade(pnl=-50), _make_trade(pnl=-50), _make_trade(pnl=100),
                  _make_trade(pnl=-50), _make_trade(pnl=-50), _make_trade(pnl=-50)]
        result = compute_streaks(trades)
        assert result["max_consecutive_losses"] == 3


class TestSplitByDirection:
    """Test All/Long/Short metric split."""

    def test_split_separates_long_short(self):
        from backend.services.backtest_metrics import split_by_direction
        trades = [
            _make_trade(side="Buy", pnl=100),
            _make_trade(side="Sell", pnl=50),
            _make_trade(side="Buy", pnl=-30),
        ]
        result = split_by_direction(trades)
        assert "all" in result
        assert "long" in result
        assert "short" in result
        assert result["long"]["total_trades"] == 2
        assert result["short"]["total_trades"] == 1


class TestBuyHoldBenchmark:
    """Test Buy & Hold benchmark (Task 4.2)."""

    def test_buy_hold_return_positive(self):
        from backend.services.backtest_metrics import compute_buy_hold_return
        # BTC goes from 50000 to 55000 → +10%
        btc_klines = [
            {"open_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "close": 50000.0},
            {"open_time": datetime(2026, 1, 2, tzinfo=timezone.utc), "close": 55000.0},
        ]
        result = compute_buy_hold_return(btc_klines, starting_capital=10000.0)
        assert abs(result["return_pct"] - 10.0) < 0.01
        assert abs(result["final_value"] - 11000.0) < 0.01

    def test_buy_hold_empty_klines(self):
        from backend.services.backtest_metrics import compute_buy_hold_return
        result = compute_buy_hold_return([], starting_capital=10000.0)
        assert result["return_pct"] == 0.0
        assert result["final_value"] == 10000.0


class TestRound2Hardening:
    """Round 2 review fixes: JSON-safety, CAGR overflow, max_dd_usd, expectancy, parity.

    Uses the module-level _assert_json_safe helper (single source of truth).
    """

    def _assert_json_safe(self, m):
        # Thin delegate to the module-level helper so existing self._assert_json_safe
        # call sites keep working without a duplicated implementation that could drift.
        _assert_json_safe(m)

    def test_cagr_extreme_growth_short_span_no_overflow(self):
        """1000x gain compressed into <1 day must NOT overflow to Infinity."""
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Two points ~1 hour apart, equity 100 -> 100000
        equity = [
            {"ts": base, "equity": 100.0, "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=1), "equity": 100000.0, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=99900.0, entry_time=base, exit_time=base + timedelta(hours=1))]
        m = compute_all_metrics(trades, equity, {"starting_capital": 100.0})
        # 1000x in 1h: expm1 exponent overflows → OverflowError caught → None.
        # The key invariant is JSON-safety (never inf), whether via None or the cap.
        assert m["cagr"] is None
        self._assert_json_safe(m)

    def test_cagr_huge_but_finite_engages_cap(self):
        """A finite-but-enormous CAGR (>1e9%) must be clamped to CAGR_CAP_PCT, not inf."""
        from backend.services.backtest_metrics import compute_all_metrics, CAGR_CAP_PCT
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365)
        # 1e8x over exactly 1 year: expm1(ln(1e8))*100 ≈ 1e10% > 1e9 cap → clamped
        equity = [
            {"ts": start, "equity": 1.0, "drawdown_pct": 0.0},
            {"ts": end, "equity": 1.0e8, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=1.0e8, entry_time=start, exit_time=end)]
        m = compute_all_metrics(trades, equity, {"starting_capital": 1.0})
        assert m["cagr"] == CAGR_CAP_PCT
        self._assert_json_safe(m)

    def test_nan_inf_pnl_sanitized(self):
        """NaN/Inf in trade pnl must not leak into output."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [
            _make_trade(pnl=float("nan")),
            _make_trade(pnl=float("inf")),
            _make_trade(pnl=100.0),
            _make_trade(pnl=-50.0),
        ]
        equity = _make_equity_curve([10000, 10050])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        self._assert_json_safe(m)

    def test_none_equity_value_no_crash(self):
        """A None equity point must not crash drawdown/CAGR computation."""
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        equity = [
            {"ts": base, "equity": 10000.0, "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=1), "equity": None, "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=2), "equity": 10100.0, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=100.0)]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        self._assert_json_safe(m)
        assert m["total_trades"] == 1

    def test_max_dd_usd_independent_of_max_dd_pct(self):
        """Deepest $ drawdown can occur at a different point than deepest % drawdown."""
        from backend.services.backtest_metrics import compute_max_drawdown
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # 100 -> 50 (50%, $50), recover to 1000 -> 600 (40%, $400)
        equity = [
            {"ts": base, "equity": 100.0},
            {"ts": base + timedelta(hours=1), "equity": 50.0},
            {"ts": base + timedelta(hours=2), "equity": 1000.0},
            {"ts": base + timedelta(hours=3), "equity": 600.0},
        ]
        dd = compute_max_drawdown(equity)
        assert abs(dd["max_dd_pct"] - 50.0) < 0.01   # deepest % is the 100->50 leg
        assert abs(dd["max_dd_usd"] - 400.0) < 0.01  # deepest $ is the 1000->600 leg

    def test_all_losing_expectancy_computed(self):
        """An all-losing strategy must report a (negative) expectancy, not None."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=-30.0), _make_trade(pnl=-20.0)]
        equity = _make_equity_curve([10000, 9950])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        assert m["expectancy"] is not None
        assert abs(m["expectancy"] - (-25.0)) < 0.01  # avg of -30, -20

    def test_avg_trade_and_ratio_present(self):
        """TradingView parity: avg_trade and avg_win_loss_ratio must be emitted."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=-50.0)]
        equity = _make_equity_curve([10000, 10050])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        assert "avg_trade" in m and abs(m["avg_trade"] - 25.0) < 0.01  # (100-50)/2
        assert "avg_win_loss_ratio" in m and abs(m["avg_win_loss_ratio"] - 2.0) < 0.01  # 100/50
        # by_direction also carries avg_trade
        assert "avg_trade" in m["by_direction"]["all"]

    def test_zero_starting_capital_no_crash(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0)]
        equity = _make_equity_curve([0, 100])
        m = compute_all_metrics(trades, equity, {"starting_capital": 0.0})
        self._assert_json_safe(m)

    def test_zero_trades_missing_equity_key_no_crash(self):
        """Zero-trades path must not KeyError on an equity point lacking 'equity'."""
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        equity = [{"ts": base}]  # no 'equity' key
        m = compute_all_metrics([], equity, {"starting_capital": 10000.0})
        assert m["total_trades"] == 0
        assert m["final_equity"] == 10000.0  # falls back to starting_capital

    def test_mixed_tz_datetimes_no_crash(self):
        """Naive vs aware datetimes (durations + drawdown + CAGR) must not crash."""
        from backend.services.backtest_metrics import compute_all_metrics
        naive = datetime(2026, 1, 1)             # naive
        aware = datetime(2026, 1, 2, tzinfo=timezone.utc)  # aware
        trades = [_make_trade(pnl=100.0, entry_time=naive, exit_time=aware)]
        equity = [
            {"ts": naive, "equity": 10000.0, "drawdown_pct": 0.0},
            {"ts": aware, "equity": 10100.0, "drawdown_pct": 0.0},
        ]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        self._assert_json_safe(m)
        assert m["total_trades"] == 1

    def test_non_numeric_starting_capital_no_crash(self):
        """A string/None starting_capital from untrusted config must not crash."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0)]
        equity = _make_equity_curve([10000, 10100])
        for bad in ("10000", None, float("nan"), float("inf")):
            m = compute_all_metrics(trades, equity, {"starting_capital": bad})
            self._assert_json_safe(m)
            assert m["total_trades"] == 1

    def test_non_dict_list_elements_no_crash(self):
        """None / non-dict elements inside trades or equity_curve must not crash."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [None, _make_trade(pnl=100.0), 42]
        equity = [None, {"ts": datetime(2026, 1, 1, tzinfo=timezone.utc), "equity": 10000.0}, "x"]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        self._assert_json_safe(m)
        assert m["total_trades"] == 1  # only the one real dict trade counts


class TestHelpersDirect:
    """Direct unit tests for internal helpers (locks in subtle branches)."""

    def test_finite_accepts_decimal(self):
        """asyncpg returns NUMERIC columns as Decimal — must be accepted, not zeroed."""
        from backend.services.backtest_metrics import _finite
        from decimal import Decimal
        assert _finite(Decimal("100.5")) == 100.5
        assert _finite(Decimal("0")) == 0.0
        assert _finite(Decimal("NaN")) is None
        assert _finite(Decimal("Infinity")) is None

    def test_finite_rejects_bool_str_none_nonfinite(self):
        from backend.services.backtest_metrics import _finite
        assert _finite(True) is None
        assert _finite(False) is None
        assert _finite("100") is None
        assert _finite(None) is None
        assert _finite(float("nan")) is None
        assert _finite(float("inf")) is None
        assert _finite(5) == 5.0
        assert _finite(5.5) == 5.5

    def test_finite_overflow_to_inf_returns_none(self):
        """A huge Decimal/int whose float() overflows to inf (or raises) → None.

        Decimal('1e400').is_finite() is True, but float(Decimal('1e400')) == inf.
        A Python int >~1.8e308 raises OverflowError on float(). Both must map to None,
        guaranteeing _finite NEVER returns a non-finite float.
        """
        from backend.services.backtest_metrics import _finite
        from decimal import Decimal
        assert _finite(Decimal("1e400")) is None        # overflows float → inf
        assert _finite(Decimal("-1e400")) is None
        assert _finite(10 ** 400) is None               # huge int → OverflowError
        assert _finite(-(10 ** 400)) is None

    def test_compute_all_metrics_huge_int_capital_no_crash(self):
        """Untrusted config: a JSON integer literal becomes an unbounded Python int."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0)]
        equity = _make_equity_curve([10000, 10100])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10 ** 400})
        _assert_json_safe(m)
        assert m["total_trades"] == 1
        # capital coerced to None→0.0 → net_profit_pct undefined
        assert m["net_profit_pct"] is None

    def test_json_safe_converts_decimal_datetime_and_nonfinite(self):
        from backend.services.backtest_metrics import _json_safe
        from decimal import Decimal
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        out = _json_safe({
            "a": float("inf"), "b": float("nan"),
            "c": Decimal("3.5"), "d": base,
            "e": {1, 2}, "f": (1.0, float("inf")),
            "nested": {"x": Decimal("NaN")},
        })
        import json
        json.dumps(out, allow_nan=False)  # must not raise
        assert out["a"] is None and out["b"] is None
        assert out["c"] == 3.5
        assert out["d"] == base.isoformat()
        assert sorted(out["e"]) == [1, 2]
        assert out["f"] == [1.0, None]
        assert out["nested"]["x"] is None

    def test_json_safe_huge_finite_decimal_to_none(self):
        """A huge but finite Decimal (float() -> inf) must become None, not leak inf."""
        from backend.services.backtest_metrics import _json_safe
        from decimal import Decimal
        out = _json_safe({"big": Decimal("1e400"), "neg": Decimal("-1e400")})
        import json
        json.dumps(out, allow_nan=False)  # must not raise
        assert out["big"] is None
        assert out["neg"] is None

    def test_hours_between_tz_and_types(self):
        from backend.services.backtest_metrics import _hours_between
        naive = datetime(2026, 1, 1, 0, 0)
        aware = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert _hours_between(naive, naive + timedelta(hours=3)) == 3.0
        # naive vs aware must not raise — falls back to naive compare → 2h
        assert abs(_hours_between(naive, aware) - 2.0) < 0.01
        assert _hours_between(None, naive) is None
        assert _hours_between(naive, "x") is None
        # a date (not datetime) is not accepted
        assert _hours_between(datetime(2026, 1, 1).date(), naive) is None

    def test_compute_daily_returns_buckets_by_day(self):
        """Two points on the same calendar day collapse to one daily sample."""
        from backend.services.backtest_metrics import _compute_daily_returns
        d1 = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        d1b = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)  # same day, later
        d2 = datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)
        curve = [
            {"ts": d1, "equity": 1000.0},
            {"ts": d1b, "equity": 1100.0},  # last value for Jan 1 wins
            {"ts": d2, "equity": 1210.0},
        ]
        returns = _compute_daily_returns(curve)
        # Only ONE day-over-day return: (1210-1100)/1100 = 0.10
        assert len(returns) == 1
        assert abs(returns[0] - 0.10) < 1e-9

    def test_compute_daily_returns_fallback_no_timestamps(self):
        from backend.services.backtest_metrics import _compute_daily_returns
        curve = [{"equity": 100.0}, {"equity": 110.0}, {"equity": 99.0}]
        returns = _compute_daily_returns(curve)
        assert len(returns) == 2
        assert abs(returns[0] - 0.10) < 1e-9
        assert abs(returns[1] - (-0.1)) < 1e-9


class TestRound4Metrics:
    """Spec FR-006 additions: run-up, duration breakdown, per-trade cumulative."""

    def test_cagr_normal_range_passes_through(self):
        """A realistic ~45% annual growth must NOT be capped or nulled."""
        from backend.services.backtest_metrics import compute_all_metrics
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365)
        equity = [
            {"ts": start, "equity": 10000.0, "drawdown_pct": 0.0},
            {"ts": end, "equity": 14500.0, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=4500.0, entry_time=start, exit_time=end)]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        assert m["cagr"] is not None
        assert abs(m["cagr"] - 45.0) < 0.5  # ~45%, uncapped

    def test_max_run_up(self):
        from backend.services.backtest_metrics import compute_run_up
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # 1000 -> 800 (trough) -> 1500 → run-up $700 / 87.5%
        equity = [
            {"ts": base, "equity": 1000.0},
            {"ts": base + timedelta(hours=1), "equity": 800.0},
            {"ts": base + timedelta(hours=2), "equity": 1500.0},
        ]
        ru = compute_run_up(equity)
        assert abs(ru["max_run_up_usd"] - 700.0) < 0.01
        assert abs(ru["max_run_up_pct"] - 87.5) < 0.01

    def test_duration_breakdown(self):
        from backend.services.backtest_metrics import compute_durations
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [
            _make_trade(pnl=100.0, entry_time=base, exit_time=base + timedelta(hours=2)),   # win 2h
            _make_trade(pnl=-50.0, entry_time=base, exit_time=base + timedelta(hours=6)),    # loss 6h
            _make_trade(pnl=80.0, entry_time=base, exit_time=base + timedelta(hours=4)),     # win 4h
        ]
        d = compute_durations(trades)
        assert abs(d["avg_trade_duration_hours"] - 4.0) < 0.01     # (2+6+4)/3
        assert abs(d["avg_winner_duration_hours"] - 3.0) < 0.01    # (2+4)/2
        assert abs(d["avg_loser_duration_hours"] - 6.0) < 0.01     # 6/1
        assert abs(d["max_trade_duration_hours"] - 6.0) < 0.01

    def test_per_trade_cumulative_pnl(self):
        from backend.services.backtest_metrics import compute_per_trade_series
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=-30.0), _make_trade(pnl=50.0)]
        series = compute_per_trade_series(trades)
        assert [s["cumulative_pnl"] for s in series] == [100.0, 70.0, 120.0]
        assert [s["index"] for s in series] == [0, 1, 2]
        assert series[0]["close_reason"] == "tp"

    def test_all_metrics_includes_run_up_and_durations(self):
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [_make_trade(pnl=100.0, entry_time=base, exit_time=base + timedelta(hours=3))]
        equity = _make_equity_curve([10000, 10100])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        for key in ("max_run_up_pct", "max_run_up_usd", "avg_winner_duration_hours",
                    "avg_loser_duration_hours", "max_trade_duration_hours", "per_trade"):
            assert key in m, f"missing {key}"
        assert isinstance(m["per_trade"], list) and len(m["per_trade"]) == 1


class TestValueLocking:
    """Exact-value tests for recovery/calmar/by_direction/drawdown edges/streaks."""

    def test_recovery_factor_exact(self):
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # net_profit=100, max_dd_usd: peak 10000 -> trough 9900 = $100 → recovery = 1.0
        equity = [
            {"ts": base, "equity": 10000.0, "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=1), "equity": 9900.0, "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=2), "equity": 10100.0, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=-100.0, entry_time=base, exit_time=base + timedelta(hours=1)),
                  _make_trade(pnl=200.0, entry_time=base, exit_time=base + timedelta(hours=2))]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        assert abs(m["net_profit"] - 100.0) < 0.01
        assert abs(m["max_dd_usd"] - 100.0) < 0.01
        assert abs(m["recovery_factor"] - 1.0) < 0.01

    def test_calmar_exact(self):
        from backend.services.backtest_metrics import compute_all_metrics
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=365)
        # 1yr, 10000 -> 14500 (+45% CAGR), with a dip to 9000 (10% dd) along the way
        equity = [
            {"ts": start, "equity": 10000.0, "drawdown_pct": 0.0},
            {"ts": start + timedelta(days=100), "equity": 9000.0, "drawdown_pct": 0.0},
            {"ts": end, "equity": 14500.0, "drawdown_pct": 0.0},
        ]
        trades = [_make_trade(pnl=4500.0, entry_time=start, exit_time=end)]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        # calmar = cagr / max_dd_pct
        assert m["cagr"] is not None and m["max_dd_pct"] > 0
        assert abs(m["calmar"] - (m["cagr"] / m["max_dd_pct"])) < 1e-6

    def test_by_direction_values(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [
            _make_trade(side="Buy", pnl=100.0),
            _make_trade(side="Buy", pnl=-40.0),
            _make_trade(side="Sell", pnl=60.0),
        ]
        equity = _make_equity_curve([10000, 10120])
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        longs = m["by_direction"]["long"]
        shorts = m["by_direction"]["short"]
        assert longs["total_trades"] == 2
        assert abs(longs["net_profit"] - 60.0) < 0.01   # 100 - 40
        assert abs(longs["win_rate"] - 50.0) < 0.01      # 1/2
        assert abs(longs["avg_trade"] - 30.0) < 0.01     # 60/2
        assert shorts["total_trades"] == 1
        assert abs(shorts["net_profit"] - 60.0) < 0.01
        assert abs(shorts["win_rate"] - 100.0) < 0.01

    def test_decimal_equity_and_pnl_no_crash(self):
        """DB-sourced Decimal equity/pnl must not crash recovery_factor/calmar (float/Decimal)."""
        from backend.services.backtest_metrics import compute_all_metrics
        from decimal import Decimal
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Decimal equity with a real drawdown (10000 -> 9900 -> 10100)
        equity = [
            {"ts": base, "equity": Decimal("10000.0"), "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=1), "equity": Decimal("9900.0"), "drawdown_pct": 0.0},
            {"ts": base + timedelta(hours=2), "equity": Decimal("10100.0"), "drawdown_pct": 0.0},
        ]
        trades = [
            _make_trade(pnl=Decimal("-100.0"), entry_time=base, exit_time=base + timedelta(hours=1)),
            _make_trade(pnl=Decimal("200.0"), entry_time=base, exit_time=base + timedelta(hours=2)),
        ]
        m = compute_all_metrics(trades, equity, {"starting_capital": Decimal("10000.0")})
        _assert_json_safe(m)
        # max_dd_usd must be a float (not Decimal) and recovery_factor computed
        assert isinstance(m["max_dd_usd"], float)
        assert abs(m["max_dd_usd"] - 100.0) < 0.01
        assert m["recovery_factor"] is not None
        assert abs(m["recovery_factor"] - 1.0) < 0.01  # net 100 / dd 100

    def test_compute_max_drawdown_returns_floats_for_decimal_input(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        from decimal import Decimal
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        equity = [
            {"ts": base, "equity": Decimal("1000")},
            {"ts": base + timedelta(hours=1), "equity": Decimal("800")},
        ]
        dd = compute_max_drawdown(equity)
        assert isinstance(dd["max_dd_usd"], float)
        assert isinstance(dd["max_dd_pct"], float)
        assert abs(dd["max_dd_usd"] - 200.0) < 0.01
        assert abs(dd["max_dd_pct"] - 20.0) < 0.01

    def test_max_drawdown_empty_and_single(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        empty = compute_max_drawdown([])
        assert empty == {"max_dd_pct": 0.0, "max_dd_usd": 0.0,
                         "max_dd_duration_hours": 0.0, "avg_dd_pct": 0.0}
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        single = compute_max_drawdown([{"ts": base, "equity": 10000.0}])
        assert single["max_dd_pct"] == 0.0 and single["max_dd_usd"] == 0.0

    def test_run_up_empty_and_single(self):
        from backend.services.backtest_metrics import compute_run_up
        assert compute_run_up([]) == {"max_run_up_pct": 0.0, "max_run_up_usd": 0.0}
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        single = compute_run_up([{"ts": base, "equity": 5000.0}])
        assert single == {"max_run_up_pct": 0.0, "max_run_up_usd": 0.0}

    def test_streaks_breakeven_breaks_the_run(self):
        from backend.services.backtest_metrics import compute_streaks
        # win, win, breakeven(0), win → a breakeven is neither a win nor a loss and
        # BREAKS both runs, so the longest win streak is the first [W,W] = 2, not 3.
        # (Standard convention; the previous impl let the 0 pass through, over-reporting.)
        trades = [_make_trade(pnl=10.0), _make_trade(pnl=10.0),
                  _make_trade(pnl=0.0), _make_trade(pnl=10.0)]
        s = compute_streaks(trades)
        assert s["max_consecutive_wins"] == 2  # breakeven resets the run
        assert s["max_consecutive_losses"] == 0
        # The $ for the best 2-win run is 20, not 30 (the post-BE win starts a new run).
        assert abs(s["max_consecutive_wins_usd"] - 20.0) < 0.01

    def test_streaks_alternating_resets(self):
        from backend.services.backtest_metrics import compute_streaks
        trades = [_make_trade(pnl=10.0), _make_trade(pnl=-5.0),
                  _make_trade(pnl=10.0), _make_trade(pnl=10.0)]
        s = compute_streaks(trades)
        assert s["max_consecutive_wins"] == 2
        assert s["max_consecutive_losses"] == 1
        assert abs(s["max_consecutive_wins_usd"] - 20.0) < 0.01

    def test_streaks_consecutive_losses_usd(self):
        from backend.services.backtest_metrics import compute_streaks
        # Two consecutive losses (-30, -20) then a win → max loss streak = 2, usd = -50
        trades = [_make_trade(pnl=-30.0), _make_trade(pnl=-20.0), _make_trade(pnl=10.0)]
        s = compute_streaks(trades)
        assert s["max_consecutive_losses"] == 2
        assert abs(s["max_consecutive_losses_usd"] - (-50.0)) < 0.01

    def test_json_safe_total_unknown_type_coerced_to_str(self):
        from backend.services.backtest_metrics import _json_safe
        import json

        class Weird:
            def __str__(self):
                return "weird"

        out = _json_safe({"a": Weird(), "b": b"bytes"})
        json.dumps(out, allow_nan=False)  # must not raise
        assert out["a"] == "weird"
        assert isinstance(out["b"], str)


class TestGuardBranches:
    """Direct coverage of defensive guard branches (buy&hold, CAGR, None config)."""

    def test_buy_hold_zero_start_price_guard(self):
        from backend.services.backtest_metrics import compute_buy_hold_return
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        klines = [
            {"open_time": base, "close": 0.0},
            {"open_time": base + timedelta(days=1), "close": 5000.0},
        ]
        r = compute_buy_hold_return(klines, starting_capital=10000.0)
        assert r["return_pct"] == 0.0
        assert r["final_value"] == 10000.0

    def test_buy_hold_decimal_klines_no_crash(self):
        """DB-sourced Decimal close prices must not crash buy&hold."""
        from backend.services.backtest_metrics import compute_buy_hold_return
        from decimal import Decimal
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        klines = [
            {"open_time": base, "close": Decimal("50000")},
            {"open_time": base + timedelta(days=1), "close": Decimal("55000")},
        ]
        r = compute_buy_hold_return(klines, starting_capital=Decimal("10000"))
        import json
        json.dumps(r, allow_nan=False)  # must not raise (no Decimal leak)
        assert abs(r["return_pct"] - 10.0) < 0.01
        assert abs(r["final_value"] - 11000.0) < 0.01
        assert isinstance(r["start_price"], float)

    def test_compute_cagr_guards_return_none(self):
        from backend.services.backtest_metrics import _compute_cagr
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        curve2 = [
            {"ts": base, "equity": 10000.0},
            {"ts": base + timedelta(days=365), "equity": 14500.0},
        ]
        # <2 points
        assert _compute_cagr([{"ts": base, "equity": 1.0}], 10000.0, 1.0) is None
        # starting_capital <= 0
        assert _compute_cagr(curve2, 0.0, 14500.0) is None
        # final_equity <= 0
        assert _compute_cagr(curve2, 10000.0, 0.0) is None
        # no timestamps → hours None → None
        no_ts = [{"equity": 10000.0}, {"equity": 14500.0}]
        assert _compute_cagr(no_ts, 10000.0, 14500.0) is None
        # sanity: a valid curve yields ~45%
        val = _compute_cagr(curve2, 10000.0, 14500.0)
        assert val is not None and abs(val - 45.0) < 0.5

    def test_none_config_no_crash(self):
        from backend.services.backtest_metrics import compute_all_metrics
        m = compute_all_metrics([_make_trade(pnl=100.0)], _make_equity_curve([10000, 10100]), None)
        assert m["total_trades"] == 1
        # starting_capital defaults to 0.0 → net_profit_pct undefined (None)
        assert m["net_profit_pct"] is None


class TestProductionHardening:
    """12e production-hardening: diagnostics, deterministic bucketing, per_trade JSON-safety."""

    def test_diagnostics_clean_run_all_zero(self):
        from backend.services.backtest_metrics import compute_all_metrics
        m = compute_all_metrics(
            [_make_trade(pnl=100.0), _make_trade(pnl=-50.0)],
            _make_equity_curve([10000, 10050]),
            {"starting_capital": 10000.0},
        )
        assert m["diagnostics"] == {
            "trades_dropped_non_dict": 0,
            "equity_points_dropped_non_dict": 0,
            "trade_pnls_sanitized": 0,
            "equity_values_sanitized": 0,
        }

    def test_diagnostics_counts_sanitized_inputs(self):
        from backend.services.backtest_metrics import compute_all_metrics
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [
            None,                              # dropped non-dict
            _make_trade(pnl=float("nan")),     # pnl sanitized
            _make_trade(pnl=float("inf")),     # pnl sanitized
            _make_trade(pnl=100.0),            # clean
            "junk",                            # dropped non-dict
        ]
        equity = [
            None,                                          # dropped non-dict
            {"ts": base, "equity": 10000.0},
            {"ts": base + timedelta(hours=1), "equity": float("nan")},   # equity sanitized
            {"ts": base + timedelta(hours=2), "equity": 10100.0},
        ]
        m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
        d = m["diagnostics"]
        assert d["trades_dropped_non_dict"] == 2
        assert d["equity_points_dropped_non_dict"] == 1
        assert d["trade_pnls_sanitized"] == 2
        assert d["equity_values_sanitized"] == 1
        # And the result is still JSON-safe
        _assert_json_safe(m)

    def test_diagnostics_present_in_zero_trades_path(self):
        from backend.services.backtest_metrics import compute_all_metrics
        m = compute_all_metrics([], _make_equity_curve([10000]), {"starting_capital": 10000.0})
        assert "diagnostics" in m
        assert m["diagnostics"]["trades_dropped_non_dict"] == 0

    def test_daily_bucketing_utc_normalized(self):
        """Same instant from a naive vs aware source must bucket to the SAME day."""
        from backend.services.backtest_metrics import _compute_daily_returns
        # 23:30 UTC on Jan 1 expressed two ways: aware-UTC and naive(=UTC).
        aware = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
        naive_same_instant = datetime(2026, 1, 1, 23, 30)  # treated as UTC
        curve_aware = [
            {"ts": aware, "equity": 1000.0},
            {"ts": aware + timedelta(hours=2), "equity": 1100.0},  # 01:30 Jan 2 UTC
        ]
        curve_naive = [
            {"ts": naive_same_instant, "equity": 1000.0},
            {"ts": naive_same_instant + timedelta(hours=2), "equity": 1100.0},
        ]
        # Both span Jan 1 -> Jan 2 → exactly one daily return, identical value
        ra = _compute_daily_returns(curve_aware)
        rn = _compute_daily_returns(curve_naive)
        assert ra == rn
        assert len(ra) == 1

    def test_daily_bucketing_non_utc_zone_converts(self):
        """A NON-UTC tz-aware ts must bucket by its UTC date, not its local date.

        This is the mutation-catching test. Three points in a US-Eastern-like
        -05:00 zone, equities [1000, 1100, 1210]:
          x = Jan 1 23:30 -05:00  → UTC Jan 2 04:30   (local Jan 1, UTC Jan 2)
          y = Jan 2 00:30 -05:00  → UTC Jan 2 05:30   (local Jan 2, UTC Jan 2)
          z = Jan 2 23:30 -05:00  → UTC Jan 3 04:30   (local Jan 2, UTC Jan 3)

        WITH UTC normalization: buckets {Jan2: 1100 (last), Jan3: 1210}
          → one daily return (1210-1100)/1100 = 0.10.
        WITHOUT (local-date) normalization: buckets {Jan1: 1000, Jan2: 1210 (last)}
          → one daily return (1210-1000)/1000 = 0.21.
        The two answers differ, so removing the normalization fails this test.
        """
        from backend.services.backtest_metrics import _compute_daily_returns
        eastern = timezone(timedelta(hours=-5))
        x = datetime(2026, 1, 1, 23, 30, tzinfo=eastern)
        y = datetime(2026, 1, 2, 0, 30, tzinfo=eastern)
        z = datetime(2026, 1, 2, 23, 30, tzinfo=eastern)
        curve = [
            {"ts": x, "equity": 1000.0},
            {"ts": y, "equity": 1100.0},
            {"ts": z, "equity": 1210.0},
        ]
        r = _compute_daily_returns(curve)
        assert len(r) == 1
        assert abs(r[0] - 0.10) < 1e-9   # UTC-correct; local-date bug would give 0.21

    def test_per_trade_json_safe_after_restructure(self):
        """per_trade is attached after the _json_safe pass — verify it's still JSON-safe."""
        from backend.services.backtest_metrics import compute_all_metrics
        from decimal import Decimal
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [
            _make_trade(pnl=Decimal("100.0"), entry_time=base,
                        exit_time=base + timedelta(hours=1), mfe_pct=Decimal("5.0")),
        ]
        m = compute_all_metrics(trades, _make_equity_curve([10000, 10100]),
                                {"starting_capital": 10000.0})
        import json
        json.dumps(m, allow_nan=False)  # whole result incl per_trade must serialize
        pt = m["per_trade"][0]
        assert isinstance(pt["pnl"], float)
        assert isinstance(pt["entry_time"], str)  # ISO string, not datetime
        assert isinstance(pt["exit_time"], str)
        assert isinstance(pt["mfe_pct"], float)

    def test_json_safe_set_deterministic_order(self):
        from backend.services.backtest_metrics import _json_safe
        # A set must serialize in a stable (sorted) order, not hash-dependent
        out1 = _json_safe({"s": {"c", "a", "b"}})
        out2 = _json_safe({"s": {"b", "a", "c"}})
        assert out1["s"] == out2["s"]  # deterministic regardless of insertion order
        assert out1["s"] == sorted(["a", "b", "c"], key=lambda x: __import__("json").dumps(x))

    def test_negative_duration_skipped(self):
        """A trade with exit_time < entry_time (impossible) is skipped, not averaged."""
        from backend.services.backtest_metrics import compute_durations
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [
            _make_trade(pnl=100.0, entry_time=base, exit_time=base + timedelta(hours=4)),  # valid 4h
            _make_trade(pnl=50.0, entry_time=base + timedelta(hours=2), exit_time=base),    # negative -2h
        ]
        d = compute_durations(trades)
        # Only the valid 4h trade contributes — negative one skipped
        assert abs(d["avg_trade_duration_hours"] - 4.0) < 0.01
        assert abs(d["max_trade_duration_hours"] - 4.0) < 0.01

    def test_cumulative_pnl_overflow_guarded(self):
        """A running cumulative_pnl that overflows to inf must be emitted as None."""
        from backend.services.backtest_metrics import compute_per_trade_series
        # Two pnls near float max → sum overflows to inf
        big = 1.5e308
        trades = [_make_trade(pnl=big), _make_trade(pnl=big)]
        series = compute_per_trade_series(trades)
        import math, json
        json.dumps(series, allow_nan=False)  # must not raise
        assert series[0]["cumulative_pnl"] == big
        assert series[1]["cumulative_pnl"] is None  # inf → None


class TestBreakevenDilution:
    """Breakeven (pnl==0) trades must dilute denominators correctly (mutation gaps #4/#11)."""

    def test_win_rate_dilutes_with_breakeven(self):
        from backend.services.backtest_metrics import compute_all_metrics
        # [+100, 0, -50]: 1 winner / 3 total → win_rate 33.33 (NOT 50% of win/loss-only)
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=0.0), _make_trade(pnl=-50.0)]
        m = compute_all_metrics(trades, _make_equity_curve([10000, 10050]),
                                {"starting_capital": 10000.0})
        assert m["total_trades"] == 3
        assert m["winners"] == 1
        assert m["losers"] == 1  # breakeven is neither
        assert abs(m["win_rate"] - (100.0 / 3)) < 0.01   # 33.33, not 50.0
        # avg_trade = net/total = 50/3, NOT 50/2
        assert abs(m["avg_trade"] - (50.0 / 3)) < 0.01
        # expectancy == avg_trade
        assert abs(m["expectancy"] - (50.0 / 3)) < 0.01

    def test_by_direction_breakeven_counted_in_total(self):
        from backend.services.backtest_metrics import compute_all_metrics
        # Long: [+100, 0] → 2 trades, 1 winner, win_rate 50, avg_trade 50
        trades = [_make_trade(side="Buy", pnl=100.0), _make_trade(side="Buy", pnl=0.0)]
        m = compute_all_metrics(trades, _make_equity_curve([10000, 10100]),
                                {"starting_capital": 10000.0})
        longs = m["by_direction"]["long"]
        assert longs["total_trades"] == 2
        assert longs["winners"] == 1
        assert longs["losers"] == 0
        assert abs(longs["win_rate"] - 50.0) < 0.01   # 1/2, breakeven dilutes
        assert abs(longs["avg_trade"] - 50.0) < 0.01  # 100/2


class TestCoverageFill:
    """Fill value-locking gaps identified in 12f review (total_commission, largest,
    avg_dd_pct/duration, all-descending run-up, missing-side, all-non-finite equity)."""

    def test_total_commission_value(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0, fees_paid=2.5), _make_trade(pnl=-50.0, fees_paid=1.5)]
        m = compute_all_metrics(trades, _make_equity_curve([10000, 10050]),
                                {"starting_capital": 10000.0})
        assert abs(m["total_commission"] - 4.0) < 0.01  # 2.5 + 1.5

    def test_largest_win_and_loss_values(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=250.0),
                  _make_trade(pnl=-30.0), _make_trade(pnl=-90.0)]
        m = compute_all_metrics(trades, _make_equity_curve([10000, 10230]),
                                {"starting_capital": 10000.0})
        assert abs(m["largest_win"] - 250.0) < 0.01
        assert abs(m["largest_loss"] - (-90.0)) < 0.01  # most negative

    def test_avg_dd_pct_and_duration_values(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # ASYMMETRIC recovery so peak->trough != trough->end (kills the
        # "duration measured to end instead of to trough" mutation):
        #   t0 1000 (peak) -> t+1h 900 (trough, 10% dd) -> t+5h 1000 (recover)
        # peak->trough = 1h; trough->end = 4h. Duration must be the 1h (peak->trough).
        equity = [
            {"ts": base, "equity": 1000.0},
            {"ts": base + timedelta(hours=1), "equity": 900.0},
            {"ts": base + timedelta(hours=5), "equity": 1000.0},
        ]
        dd = compute_max_drawdown(equity)
        assert abs(dd["max_dd_pct"] - 10.0) < 0.01
        assert abs(dd["max_dd_usd"] - 100.0) < 0.01
        # duration peak(t0) -> trough(t+1h) = 1 hour (NOT 4h to end)
        assert abs(dd["max_dd_duration_hours"] - 1.0) < 0.01
        # avg_dd over points [0%, 10%, 0%] = 3.333%
        assert abs(dd["avg_dd_pct"] - (10.0 / 3)) < 0.01

    def test_run_up_zero_when_monotonic_descending(self):
        from backend.services.backtest_metrics import compute_run_up
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        equity = [
            {"ts": base, "equity": 1000.0},
            {"ts": base + timedelta(hours=1), "equity": 800.0},
            {"ts": base + timedelta(hours=2), "equity": 600.0},
        ]
        ru = compute_run_up(equity)
        assert ru["max_run_up_usd"] == 0.0
        assert ru["max_run_up_pct"] == 0.0

    def test_split_by_direction_missing_side(self):
        from backend.services.backtest_metrics import split_by_direction
        # A trade with no/unknown side → counted in 'all', neither long nor short
        trades = [
            _make_trade(side="Buy", pnl=100.0),
            _make_trade(side=None, pnl=50.0),     # unknown
            {"pnl": 30.0},                          # missing side entirely
        ]
        result = split_by_direction(trades)
        assert result["all"]["total_trades"] == 3
        assert result["long"]["total_trades"] == 1
        assert result["short"]["total_trades"] == 0

    def test_max_drawdown_all_non_finite_equity(self):
        from backend.services.backtest_metrics import compute_max_drawdown
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Non-empty curve but every equity is bad → filtered to empty → zero dict
        equity = [
            {"ts": base, "equity": float("nan")},
            {"ts": base + timedelta(hours=1), "equity": None},
        ]
        dd = compute_max_drawdown(equity)
        assert dd == {"max_dd_pct": 0.0, "max_dd_usd": 0.0,
                      "max_dd_duration_hours": 0.0, "avg_dd_pct": 0.0}

    def test_durations_missing_times_and_zero_duration(self):
        from backend.services.backtest_metrics import compute_durations
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Use plain dicts so a genuinely-missing entry_time stays None
        # (the _make_trade helper coerces entry_time=None back to a default).
        trades = [
            {"pnl": 100.0, "side": "Buy", "entry_time": base, "exit_time": base + timedelta(hours=4)},  # 4h
            {"pnl": 50.0, "side": "Buy", "entry_time": base, "exit_time": base},                          # 0h (kept)
            {"pnl": 20.0, "side": "Buy", "entry_time": None, "exit_time": base},                          # missing → skipped
        ]
        d = compute_durations(trades)
        # 4h and 0h kept (avg 2.0), missing skipped
        assert abs(d["avg_trade_duration_hours"] - 2.0) < 0.01
        assert abs(d["max_trade_duration_hours"] - 4.0) < 0.01

    def test_sortino_insufficient_data_none(self):
        from backend.services.backtest_metrics import compute_sortino
        assert compute_sortino([0.01]) is None
        assert compute_sortino([]) is None

    def test_final_equity_additive_fallback_no_equity_curve(self):
        """With trades but an EMPTY equity_curve, final_equity = starting_capital + net_profit."""
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=-30.0)]  # net +70
        m = compute_all_metrics(trades, [], {"starting_capital": 10000.0})
        assert m["total_trades"] == 2
        assert abs(m["net_profit"] - 70.0) < 0.01
        # No equity curve → fall back to starting_capital + net_profit = 10070
        assert abs(m["final_equity"] - 10070.0) < 0.01
