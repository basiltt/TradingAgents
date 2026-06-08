"""Golden-set validation tests for the backtest engine (Phase 7, Task 7.2).

These freeze a small set of deterministic scenarios with hand-verified expected
outputs. The backtest engine is pure and synchronous (all data pre-loaded), so
these run without a database. Any change that shifts a golden output by more than
the tolerance fails CI — guarding the <1% deviation requirement (AC) against
silent regressions in fee/PnL/close-rule math.

Each scenario fixes: config, signals, klines → asserts trade count, close
reasons, and net profit / final equity within a tight relative tolerance.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from backend.services.backtest_engine import BacktestEngine


BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

# Relative tolerance for monetary golden values. The engine is deterministic, so
# this only absorbs float rounding (well under the 1% deviation budget).
REL_TOL = 1e-6


def _config(**overrides):
    cfg = {
        "starting_capital": 10000.0,
        "leverage": 10,
        "capital_pct": 10.0,
        "take_profit_pct": 5.0,
        "stop_loss_pct": 50.0,
        "direction": "straight",
        "fee_rate_pct": 0.055,
        "slippage_bps": 0,
        "funding_rate_model": "none",
        "execution_mode": "batch",
        "max_trades": 999,
        "skip_if_positions_open": False,
    }
    cfg.update(overrides)
    return cfg


def _signal(ticker="BTCUSDT", direction="buy", price=50000.0, minute=0, sid=1):
    return {
        "id": sid,
        "ticker": ticker,
        "direction": direction,
        "confidence": "high",
        "score": 8,
        "signal_time": BASE + timedelta(minutes=minute),
        "scan_id": "s1",
        "signal_source": "structured",
        "analysis_price": price,
    }


def _candle(minute, open_, high, low, close, vol=100.0):
    return {
        "open_time": BASE + timedelta(minutes=minute),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    }


def _assert_reconciles(result, config):
    """The core accounting invariant: summed trade PnL equals the equity change.
    net_profit must be net of ALL commissions (both entry and exit fees), matching
    TradingView's "Net Profit" = final_equity - starting_capital. This guards the
    fee-accounting consistency the golden values alone cannot."""
    net_profit = result.metrics["net_profit"]
    final_equity = result.metrics["final_equity"]
    starting = config["starting_capital"]
    assert net_profit == pytest.approx(final_equity - starting, abs=1e-6), (
        f"net_profit {net_profit} != final_equity-start {final_equity - starting} "
        f"(commission accounting must be self-consistent)"
    )


def _rising_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    """Monotonically rising 5m candles — a long TP scenario."""
    return {
        symbol: [
            _candle(5 * i, start + i * step, start + i * step + 200, start + i * step - 50, start + i * step)
            for i in range(n)
        ]
    }


def _falling_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    """Monotonically falling 5m candles — a long SL scenario."""
    return {
        symbol: [
            _candle(5 * i, start - i * step, start - i * step + 50, start - i * step - 200, start - i * step)
            for i in range(n)
        ]
    }


class TestGoldenScenarios:
    """Frozen scenarios with hand-verified expected outputs (>0.1% deviation fails)."""

    def test_golden_long_take_profit(self):
        """A long signal on monotonically rising price hits TP for a known profit."""
        result = BacktestEngine().run(_config(), [_signal()], _rising_klines())
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "tp"
        # net_profit is net of BOTH entry and exit fees (TradingView semantics).
        assert result.metrics["net_profit"] == pytest.approx(38.9725, rel=REL_TOL)
        assert result.metrics["final_equity"] == pytest.approx(10038.9725, rel=REL_TOL)
        # Winning trade → win rate 100%.
        assert result.metrics["win_rate"] == pytest.approx(100.0, rel=REL_TOL)
        _assert_reconciles(result, _config())

    def test_golden_long_stop_loss(self):
        """A long signal on monotonically falling price hits SL for a known loss."""
        result = BacktestEngine().run(_config(), [_signal()], _falling_klines())
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "sl"
        assert result.metrics["net_profit"] == pytest.approx(-510.725, rel=REL_TOL)
        assert result.metrics["final_equity"] == pytest.approx(9489.275, rel=REL_TOL)
        assert result.metrics["net_profit"] < 0
        _assert_reconciles(result, _config())

    def test_golden_reverse_direction(self):
        """Reverse mode inverts a buy signal to a short; on rising price it stops out."""
        result = BacktestEngine().run(_config(direction="reverse"), [_signal()], _rising_klines())
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "sl"
        assert result.trades[0]["side"].lower() in ("sell", "short")
        assert result.metrics["net_profit"] == pytest.approx(-511.275, rel=REL_TOL)
        _assert_reconciles(result, _config(direction="reverse"))

    def test_golden_missing_klines_no_trade(self):
        """A signal whose symbol has no kline coverage produces zero trades."""
        result = BacktestEngine().run(_config(), [_signal(ticker="ETHUSDT")], _rising_klines())
        assert result.trades == []
        assert result.metrics["net_profit"] == pytest.approx(0.0, abs=1e-9)
        assert result.metrics["final_equity"] == pytest.approx(10000.0, rel=REL_TOL)

    def test_golden_max_trades_caps_concurrency(self):
        """max_trades=1 admits one of two simultaneous signals; =2 admits both."""
        sigs = [
            _signal(sid=1, minute=0),
            _signal(ticker="ETHUSDT", sid=2, minute=0, price=3000.0),
        ]
        klines = {**_rising_klines(), **_rising_klines("ETHUSDT", start=3000.0, step=10.0)}

        one = BacktestEngine().run(_config(max_trades=1), sigs, klines)
        assert len(one.trades) == 1
        assert one.metrics["net_profit"] == pytest.approx(38.9725, rel=REL_TOL)

        two = BacktestEngine().run(_config(max_trades=2), sigs, klines)
        assert len(two.trades) == 2
        assert two.metrics["net_profit"] == pytest.approx(77.941103, rel=REL_TOL)
        _assert_reconciles(two, _config(max_trades=2))

    def test_golden_determinism_repeated_runs(self):
        """The engine is deterministic: identical inputs → byte-identical metrics."""
        cfg, sigs, klines = _config(), [_signal()], _rising_klines()
        first = BacktestEngine().run(cfg, sigs, klines).metrics
        second = BacktestEngine().run(cfg, sigs, klines).metrics
        assert first["net_profit"] == second["net_profit"]
        assert first["final_equity"] == second["final_equity"]
        assert first["max_dd_pct"] == second["max_dd_pct"]

    def test_golden_max_duration_close_on_flat_price(self):
        """On a flat price with TP/SL out of reach, max_trade_duration_hours forces
        a time-based close. The only PnL is the round-trip commission, so this
        directly pins the fee accounting: pnl == -fees_paid."""
        cfg = _config(
            take_profit_pct=500.0, stop_loss_pct=500.0, max_trade_duration_hours=1.0
        )
        klines = {
            "BTCUSDT": [_candle(5 * i, 50000.0, 50010.0, 49990.0, 50000.0) for i in range(36)]
        }
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["close_reason"] == "max_duration"
        # Per-trade field assertions (sizing + fees) catch mutations that preserve
        # net_profit but corrupt qty/fees.
        assert trade["qty"] == pytest.approx(0.2, rel=REL_TOL)
        assert trade["fees_paid"] == pytest.approx(11.0, rel=REL_TOL)
        # Flat price → the entire loss is commission: pnl == -fees_paid.
        assert trade["pnl"] == pytest.approx(-11.0, rel=REL_TOL)
        assert trade["pnl"] == pytest.approx(-trade["fees_paid"], rel=REL_TOL)
        _assert_reconciles(result, cfg)

    def test_golden_single_trade_drawdown_from_anchor(self):
        """A single losing trade must still show drawdown: the equity curve is
        anchored at (start, starting_capital), so the start→close drop is visible.
        Regression guard for the missing starting-capital anchor."""
        result = BacktestEngine().run(_config(), [_signal()], _falling_klines())
        assert len(result.trades) == 1
        # Curve = [anchor @ starting_capital, close @ lower equity].
        assert len(result.equity_curve) == 2
        assert result.equity_curve[0]["equity"] == pytest.approx(10000.0, rel=REL_TOL)
        # The loss is now captured as drawdown (was 0 before the anchor fix).
        assert result.metrics["max_dd_pct"] == pytest.approx(5.10725, rel=1e-4)
        assert result.metrics["max_dd_usd"] == pytest.approx(510.725, rel=REL_TOL)
        _assert_reconciles(result, _config())

    def test_golden_equity_curve_has_intermediate_points(self):
        """The equity curve must record a point at each trade close (not just
        start/end), so path-dependent metrics (max drawdown, Sharpe, run-up) are
        real rather than degenerate zeros on a 2-point line. Regression guard for
        the equity-curve sampling."""
        cfg = _config(max_trades=5, take_profit_pct=2.0, stop_loss_pct=2.0,
                      skip_if_positions_open=False)
        # Distinct scan_ids → separate scan batches → multiple sequential trades.
        sigs = []
        for k in range(8):
            s = _signal(sid=k, minute=k * 120, direction="buy" if k % 2 == 0 else "sell")
            s["scan_id"] = f"scan{k}"
            sigs.append(s)
        import math
        klines = {
            "BTCUSDT": [
                _candle(
                    5 * i,
                    50000 + 1200 * math.sin(i / 10),
                    50000 + 1200 * math.sin(i / 10) + 400,
                    50000 + 1200 * math.sin(i / 10) - 400,
                    50000 + 1200 * math.sin(i / 10 + 0.2),
                )
                for i in range(240)
            ]
        }
        result = BacktestEngine().run(cfg, sigs, klines)
        assert len(result.trades) >= 3
        # One equity point per close (+ possibly start/terminal) → strictly > 2.
        assert len(result.equity_curve) > 2
        assert len(result.equity_curve) >= len(result.trades)
        # With wins AND losses, drawdown must be a real positive number, and the
        # risk ratios must be computed (not None from a degenerate curve).
        assert result.metrics["max_dd_pct"] > 0
        assert result.metrics["sharpe"] is not None
        # Each equity point must carry a real (non-placeholder) drawdown_pct so the
        # frontend drawdown chart renders correctly. At least one point is below
        # peak → has a negative drawdown_pct, and the deepest matches max_dd_pct.
        dds = [p.get("drawdown_pct") for p in result.equity_curve]
        assert all(d is not None for d in dds)
        assert any(d < 0 for d in dds)
        assert min(dds) == pytest.approx(-result.metrics["max_dd_pct"], rel=1e-3)
        _assert_reconciles(result, cfg)

    def test_golden_multi_symbol_uneven_coverage_reconciles(self):
        """Two symbols held to backtest_end with UNEVEN kline coverage: the
        force-close tail stamps each position with its own symbol's last candle
        time, which can be out of chronological order. The terminal equity point
        must still be the authoritative final wallet so net_profit reconciles with
        final_equity (regression guard for the equity-curve sort interaction)."""
        cfg = _config(
            max_trades=5, take_profit_pct=500.0, stop_loss_pct=500.0,
            skip_if_positions_open=False,
        )
        sigs = [
            _signal(sid=1, ticker="BTCUSDT", price=50000.0),
            _signal(sid=2, ticker="ETHUSDT", price=3000.0),
        ]
        for s in sigs:
            s["scan_id"] = "scanA"
        # BTC: 60 rising candles (later last-ts). ETH: 30 falling candles (earlier last-ts).
        klines = {
            "BTCUSDT": [
                _candle(5 * i, 50000.0 + i * 100, 50000.0 + i * 100 + 50, 50000.0 + i * 100 - 50, 50000.0 + i * 100)
                for i in range(60)
            ],
            "ETHUSDT": [
                _candle(5 * i, 3000.0 - i * 10, 3000.0 - i * 10 + 5, 3000.0 - i * 10 - 5, 3000.0 - i * 10)
                for i in range(30)
            ],
        }
        result = BacktestEngine().run(cfg, sigs, klines)
        assert len(result.trades) == 2
        # The last equity point must equal the final wallet (authoritative).
        assert result.equity_curve[-1]["equity"] == pytest.approx(
            result.metrics["final_equity"], rel=REL_TOL
        )
        _assert_reconciles(result, cfg)

    def test_golden_trailing_profit_close(self):
        """A position that rallies (activating the trailing stop) then pulls back
        closes via TRAILING_PROFIT and reconciles. Covers the trailing close-rule
        path (previously untested)."""
        cfg = _config(take_profit_pct=500.0, stop_loss_pct=500.0, trailing_profit_pct=2.0)
        prices = [50000 + i * 150 for i in range(40)] + [56000 - i * 100 for i in range(40)]
        klines = {"BTCUSDT": [_candle(5 * i, p, p + 100, p - 100, p) for i, p in enumerate(prices)]}
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "trailing_profit"
        _assert_reconciles(result, cfg)

    def test_golden_equity_drop_close(self):
        """A position whose equity falls past max_drawdown_pct closes via
        EQUITY_DROP. Covers the equity-based close-rule path (previously untested)."""
        cfg = _config(take_profit_pct=500.0, stop_loss_pct=500.0, max_drawdown_pct=3.0)
        prices = [50000 - i * 100 for i in range(60)]
        klines = {"BTCUSDT": [_candle(5 * i, p, p + 50, p - 50, p) for i, p in enumerate(prices)]}
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "equity_drop"
        _assert_reconciles(result, cfg)

    def test_golden_liquidation_close(self):
        """A high-leverage position with an adverse move beyond the liquidation
        distance closes via LIQUIDATION (full margin + entry-fee loss) and still
        reconciles. Covers the liquidation path (previously untested)."""
        cfg = _config(leverage=100, take_profit_pct=500.0, stop_loss_pct=500.0)
        prices = [50000 - i * 60 for i in range(40)]
        klines = {"BTCUSDT": [_candle(5 * i, p, p + 20, p - 100, p) for i, p in enumerate(prices)]}
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "liquidation"
        assert result.trades[0]["pnl"] < 0
        _assert_reconciles(result, cfg)

    def test_golden_funding_reconciles(self):
        """With the fixed_8h funding model, a position held across several funding
        windows accrues funding that mutates the wallet. The recorded trade pnl
        must fold in that funding so net_profit still reconciles with final_equity
        (regression guard for funding-vs-trade accounting drift)."""
        cfg = _config(
            take_profit_pct=500.0,
            stop_loss_pct=500.0,
            max_trade_duration_hours=48.0,
            funding_rate_model="fixed_8h",
            funding_rate_fixed_pct=0.01,
        )
        # 50 hours of flat 5m candles → crosses several 0/8/16 UTC funding times.
        klines = {
            "BTCUSDT": [_candle(5 * i, 50000.0, 50010.0, 49990.0, 50000.0) for i in range(600)]
        }
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        # Flat price → loss is entirely commission + funding; pnl == -fees_paid.
        assert trade["pnl"] == pytest.approx(-trade["fees_paid"], rel=REL_TOL)
        # Funding (long pays) makes the total cost exceed pure round-trip fees (11.0).
        assert trade["fees_paid"] > 11.0
        _assert_reconciles(result, cfg)

    def test_golden_price_drift_filter(self):
        """The price-drift filter (max_price_drift_pct) rejects a signal whose
        analysis price diverged too far from the kline price at signal time, and
        admits one within tolerance. Regression guard: this path references the
        klines map inside the filter chain, which must be threaded through."""
        # Signal anchored at 50000 but klines start at 60000 → 20% drift > 1% cap → filtered.
        filtered = BacktestEngine().run(
            _config(max_price_drift_pct=1.0), [_signal(price=50000.0)], _rising_klines(start=60000.0)
        )
        assert filtered.trades == []

        # Same signal with a generous 50% cap and matching prices → trades.
        admitted = BacktestEngine().run(
            _config(max_price_drift_pct=50.0), [_signal(price=50000.0)], _rising_klines(start=50000.0)
        )
        assert len(admitted.trades) == 1

    def test_golden_price_drift_is_directional(self):
        """Price drift is DIRECTION-AWARE, matching production (auto_trade_service):
        only reject when price already moved too far IN the signal's direction (the
        move is "consumed"/chasing). A buy whose price has DROPPED below the analysis
        price is a BETTER entry and must be ADMITTED — the old symmetric abs() check
        wrongly rejected it, diverging from real trading. Regression guard for that fix.
        """
        # BUY, price DROPPED 20% (analysis 60000, klines at 48000) → favorable entry.
        # Old abs() logic: |drift|=20% > 1% → WRONGLY filtered. New signed logic: a buy
        # only rejects on a POSITIVE drift past the cap, so this is ADMITTED.
        admitted_buy = BacktestEngine().run(
            _config(max_price_drift_pct=1.0),
            [_signal(direction="buy", price=60000.0)],
            _rising_klines(start=48000.0),
        )
        assert len(admitted_buy.trades) == 1, "a buy that got a better (lower) entry must be admitted"

        # BUY, price RAN UP 20% past the cap (analysis 50000, klines 60000) → chasing → rejected.
        rejected_buy = BacktestEngine().run(
            _config(max_price_drift_pct=1.0),
            [_signal(direction="buy", price=50000.0)],
            _rising_klines(start=60000.0),
        )
        assert rejected_buy.trades == [], "a buy chasing a consumed up-move must be rejected"

        # SELL, price DROPPED 20% past the cap (analysis 60000, klines 48000) → move
        # consumed downward → rejected (mirror of the buy-up case). score<0 → sell side.
        rejected_sell = BacktestEngine().run(
            _config(max_price_drift_pct=1.0),
            [_signal(direction="sell", price=60000.0, sid=2)],
            _falling_klines(start=48000.0),
        )
        assert rejected_sell.trades == [], "a sell chasing a consumed down-move must be rejected"

    def test_golden_slippage_anchors_tp_sl_and_qty_to_unslipped_mark(self):
        """Slippage parity with production: the entry FILLS at the slipped price (used
        for PnL), but qty and TP/SL TRIGGERS are anchored to the UN-SLIPPED mark —
        exactly like production (accounts_service: qty = usdt×lev/mark_price; tp =
        mark×(1±pct)). The exit then FILLS with adverse round-trip slippage, since
        production closes via a Bybit market reduce-only order.

        Regression guard: the engine previously anchored qty AND TP/SL to the slipped
        entry, handing the trader the full nominal move PLUS the slippage on every
        exit — a systematic favorable bias (~lev×slippage per trade) that breaches the
        <1% deviation requirement over many trades.

        Setup: mark 50000, slippage 10 bps. Entry fill = 50050. leverage 10,
        capital_pct 20 → qty 0.4 (off the 50000 mark, NOT 0.3996 off the 50050 fill).
        TP 50% at 10x = +5% → TRIGGER anchored to mark = 52500 (NOT 50050×1.05). The
        exit FILLS with adverse slippage on the sell-to-close: 52500×(1−0.001)=52447.5.
        Fees off (0%) to isolate the price math. Realized PnL =
        0.4×(52447.5−50050) = 959.0.
        """
        cfg = _config(
            leverage=10, capital_pct=20.0,
            take_profit_pct=50.0, stop_loss_pct=500.0,
            slippage_bps=10, fee_rate_pct=0.0,
        )
        # Rising candles that reach the mark-anchored TP trigger (52500); the exit
        # then fills slightly below it due to exit slippage.
        klines = {"BTCUSDT": [
            _candle(5 * i, 50000.0 + i * 100, 50000.0 + i * 100 + 300, 50000.0 + i * 100 - 50, 50000.0 + i * 100)
            for i in range(40)
        ]}
        result = BacktestEngine().run(cfg, [_signal(price=50000.0)], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["close_reason"] == "tp"
        # Entry fill is the SLIPPED price (for PnL) — production fills the market order
        # at avgPrice.
        assert trade["entry_price"] == pytest.approx(50050.0, rel=REL_TOL)
        # qty anchored to the UN-SLIPPED mark (0.4), not the slipped fill (~0.3996).
        assert trade["qty"] == pytest.approx(0.4, rel=REL_TOL)
        # TP TRIGGER anchored to the un-slipped mark (50000×1.05 = 52500), but the
        # recorded exit FILL is slipped down by 10 bps on the sell-to-close: 52447.5.
        assert trade["exit_price"] == pytest.approx(52447.5, rel=REL_TOL)
        # Realized PnL = qty × (slipped_exit − slipped_entry) = 0.4 × (52447.5 − 50050)
        # = 959.0 — slightly LESS than anchoring to the un-slipped mark (980), and far
        # less than the buggy slipped-anchor (~1000); matches round-trip live trading.
        assert trade["pnl"] == pytest.approx(959.0, rel=REL_TOL)
        _assert_reconciles(result, cfg)

    def test_golden_exit_slippage_applied_adversely_on_close(self):
        """Exit fills incur adverse round-trip slippage — production closes via Bybit
        market reduce-only orders that fill worse than the trigger/close price. A long
        sells to close → the fill slips DOWN from the SL trigger. The recorded
        exit_price and PnL must reflect that slipped fill (not the exact trigger).

        Regression guard: the engine previously applied slippage only on entry, never
        on exit, handing the trader a systematic favorable ~slippage per close — the
        symmetric counterpart of the entry slippage. (User-confirmed: slippage_bps is
        a round-trip cost, overriding the spec's exact-exit-fill wording.)

        Setup: mark 50000, slippage 20 bps → entry fill 50100. leverage 10,
        capital_pct 20 → qty 0.4. SL 40% at 10x = -4% → SL TRIGGER at mark×0.96 =
        48000; the sell-to-close exit FILLS slipped down: 48000×(1−0.002) = 47904.
        Fees off. Realized PnL = 0.4×(47904 − 50100) = -878.4.
        """
        cfg = _config(
            leverage=10, capital_pct=20.0,
            take_profit_pct=500.0, stop_loss_pct=40.0,
            slippage_bps=20, fee_rate_pct=0.0,
        )
        # Falling candles that breach the SL trigger (48000).
        klines = {"BTCUSDT": [
            _candle(5 * i, 50000.0 - i * 200, 50000.0 - i * 200 + 50, 50000.0 - i * 200 - 300, 50000.0 - i * 200)
            for i in range(40)
        ]}
        result = BacktestEngine().run(cfg, [_signal(price=50000.0)], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["close_reason"] == "sl"
        assert trade["entry_price"] == pytest.approx(50100.0, rel=REL_TOL)
        # Exit fill is the SL trigger (48000) slipped DOWN by 20 bps on the close: 47904.
        assert trade["exit_price"] == pytest.approx(47904.0, rel=REL_TOL)
        # Realized PnL reflects the slipped exit: 0.4 × (47904 − 50100) = -878.4. Under
        # the bug (exact 48000 fill) it would be a smaller loss: 0.4×(48000−50100)=-840.
        assert trade["pnl"] == pytest.approx(-878.4, rel=REL_TOL)
        assert trade["pnl"] < -840.0  # strictly worse than the no-exit-slippage loss
        _assert_reconciles(result, cfg)

    def test_golden_equity_rise_profit_goal_close(self):
        """A profit_pct target goal closes the whole cycle via EQUITY_RISE_PCT when
        cycle equity rises goal_value% from the reference — mirroring production, which
        maps a profit_pct target goal to an EQUITY_RISE_PCT close rule (reference =
        base_capital, threshold = goal_value). Regression guard: check_equity_rise
        existed but was never wired into the engine, so a profit_pct goal previously
        ran to backtest_end instead of closing on the rise.

        Setup: target_goal_type=profit_pct, target_goal_value=5 → fire at +5% cycle
        equity. leverage 10 / capital_pct 20 → 0.4 BTC; a rising price crosses +$500
        (+5% of 10000) well before the wide 500% TP, closing via equity_rise.
        """
        cfg = _config(
            take_profit_pct=500.0, stop_loss_pct=500.0,
            target_goal_type="profit_pct", target_goal_value=5.0,
            leverage=10, capital_pct=20.0,
        )
        prices = [50000.0 + i * 200.0 for i in range(40)]
        klines = {"BTCUSDT": [_candle(5 * i, p, p + 250, p - 50, p) for i, p in enumerate(prices)]}
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "equity_rise"
        assert result.trades[0]["pnl"] > 0  # closed BECAUSE the cycle rose into profit
        _assert_reconciles(result, cfg)

    def test_golden_funding_charges_once_per_boundary_dense_candles(self):
        """Funding must charge exactly ONCE per 0/8/16h boundary regardless of candle
        density. Guards against the funding `minute < 5` window multi-charging if a
        sub-5m interval is ever introduced: with 1-minute candles, the [hh:00, hh:05)
        window holds 5 candles, but only the first may charge.

        A long held ~10h over 1-minute candles crosses the 00:00 (fires at 00:01, the
        00:00 entry candle is excluded) and 08:00 boundaries → exactly 2 charges, not
        the ~9 the old per-candle logic would bill.
        """
        cfg = _config(
            take_profit_pct=500.0, stop_loss_pct=500.0, max_trade_duration_hours=48.0,
            funding_rate_model="fixed_8h", funding_rate_fixed_pct=0.01,
            leverage=10, capital_pct=20.0, fee_rate_pct=0.0,
        )
        # 600 one-minute candles (00:00 → 09:59), flat price.
        klines = {"BTCUSDT": [_candle(0, 50000.0, 50010.0, 49990.0, 50000.0)]}
        klines["BTCUSDT"] = [
            {**_candle(0, 50000.0, 50010.0, 49990.0, 50000.0), "open_time": BASE + timedelta(minutes=i)}
            for i in range(600)
        ]
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        # qty = 20% × 10000 × 10 / 50000 = 0.4. Per-boundary funding = 0.4×50000×0.0001 = 2.0.
        # Exactly 2 boundaries (00:00→fires 00:01, 08:00) → fees = 2 × 2.0 = 4.0 (fees off).
        assert trade["fees_paid"] == pytest.approx(4.0, rel=1e-6), (
            f"funding fees {trade['fees_paid']} — expected exactly 2 boundary charges; "
            "the minute<5 window is multi-charging on dense candles"
        )
        _assert_reconciles(result, cfg)

    def test_golden_close_on_profit_close(self):
        """A cycle whose equity rises past the close_on_profit threshold closes via
        CLOSE_ON_PROFIT (the EQUITY_RISE-style take-profit-on-cycle rule) and
        reconciles. Covers the close_on_profit equity path with the golden
        exact-reconciliation guard the other close rules get."""
        # effective threshold = (close_on_profit_pct/100) * target_goal_value
        #                     = (5/100) * 100 = 5.0  → fires at +5% cycle equity.
        # target_goal_value is now REQUIRED with close_on_profit_pct (production parity:
        # the threshold is undefined without it), so set it explicitly to 100.
        # A long at lev 10 / 10% capital holds 0.2 BTC; a ~$2.5k price rise yields
        # ~+$500 (>5% of 10k) before the wide 500% TP (needs +50% price) is reached.
        cfg = _config(take_profit_pct=500.0, stop_loss_pct=500.0,
                      close_on_profit_pct=5.0, target_goal_value=100.0)
        result = BacktestEngine().run(cfg, [_signal()], _rising_klines())
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "close_on_profit"
        # It is a winning cycle (closed BECAUSE equity rose past the threshold).
        assert result.metrics["net_profit"] > 0
        _assert_reconciles(result, cfg)

    def test_golden_breakeven_timeout_close(self):
        """BREAKEVEN_TIMEOUT does NOT force-close; it lowers TP to the breakeven
        price after the timeout. A subsequent small uptick then closes the position
        via that breakeven TP for a roughly flat result. Covers the breakeven path
        with the golden exact-reconciliation guard."""
        # Wide TP/SL (500% → needs a 50% move) so only the breakeven-lowered TP can
        # fire. breakeven_timeout_hours=1.0 → after 12 flat 5m candles TP drops to
        # ~entry*(1+1/(lev*100)) = 50050; a later 50100 candle then hits it.
        cfg = _config(
            take_profit_pct=500.0, stop_loss_pct=500.0, breakeven_timeout_hours=1.0
        )
        klines = {
            "BTCUSDT": (
                [_candle(5 * i, 50000.0, 50010.0, 49990.0, 50000.0) for i in range(14)]
                + [_candle(5 * i, 50100.0, 50150.0, 50050.0, 50100.0) for i in range(14, 30)]
            )
        }
        result = BacktestEngine().run(cfg, [_signal()], klines)
        assert len(result.trades) == 1
        trade = result.trades[0]
        # The engine realises breakeven by moving the TP, so the close_reason is "tp"
        # (at the breakeven price), and the net result is approximately flat.
        assert trade["close_reason"] == "tp"
        assert trade["exit_price"] == pytest.approx(50050.0, rel=1e-3)
        # Near-breakeven: the result is a small fraction of starting capital.
        assert abs(result.metrics["net_profit"]) < 0.005 * cfg["starting_capital"]
        _assert_reconciles(result, cfg)


class TestDrilldownByteIdentical:
    """The 1m drill-down feature must NEVER change engine output unless 1m data is
    actually injected. In particular the engine must branch ONLY on the presence of
    fine_klines — NEVER on config['drilldown_enabled'] — so a golden config can carry
    the flag without shifting any result. This is the guarantee that keeps every
    golden scenario above stable now that the engine accepts fine_klines.
    """

    def _scenarios(self):
        # A representative spread: TP win, SL loss, reverse, multi-trade.
        return [
            (_config(), [_signal()], _rising_klines()),
            (_config(), [_signal()], _falling_klines()),
            (_config(direction="reverse"), [_signal()], _rising_klines()),
        ]

    def test_flag_true_vs_false_identical_without_fine_data(self):
        for cfg, sigs, klines in self._scenarios():
            cfg_on = dict(cfg); cfg_on["drilldown_enabled"] = True
            cfg_off = dict(cfg); cfg_off["drilldown_enabled"] = False
            on = BacktestEngine().run(cfg_on, sigs, klines)
            off = BacktestEngine().run(cfg_off, sigs, klines)
            assert on.trades == off.trades
            assert on.metrics.get("net_profit") == off.metrics.get("net_profit")
            assert on.metrics.get("final_equity") == off.metrics.get("final_equity")

    def test_none_and_empty_fine_klines_identical_to_omitted(self):
        for cfg, sigs, klines in self._scenarios():
            omitted = BacktestEngine().run(cfg, sigs, klines)
            none = BacktestEngine().run(cfg, sigs, klines, fine_klines=None)
            empty = BacktestEngine().run(cfg, sigs, klines, fine_klines={})
            assert omitted.trades == none.trades == empty.trades
            for m in ("net_profit", "final_equity", "win_rate", "total_trades"):
                assert omitted.metrics.get(m) == none.metrics.get(m) == empty.metrics.get(m)
