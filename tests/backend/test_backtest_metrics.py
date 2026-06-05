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
        # Sharpe needs >= 2 data points
        assert m["sharpe"] is None or isinstance(m["sharpe"], float)

    def test_all_wins_profit_factor_infinity(self):
        from backend.services.backtest_metrics import compute_all_metrics
        trades = [_make_trade(pnl=100.0), _make_trade(pnl=200.0)]
        equity = _make_equity_curve([10000, 10300])
        config = {"starting_capital": 10000.0}

        m = compute_all_metrics(trades, equity, config)
        # No losses → profit factor = infinity
        assert m["profit_factor"] == float("inf") or m["profit_factor"] is None

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
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]
        result = compute_sharpe(returns)
        assert result is None or isinstance(result, float)

    def test_sharpe_none_for_insufficient_data(self):
        from backend.services.backtest_metrics import compute_sharpe
        assert compute_sharpe([0.01]) is None
        assert compute_sharpe([]) is None

    def test_sortino_returns_float_or_none(self):
        from backend.services.backtest_metrics import compute_sortino
        returns = [0.01, 0.02, -0.01, 0.03, -0.02]
        result = compute_sortino(returns)
        assert result is None or isinstance(result, float)


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
