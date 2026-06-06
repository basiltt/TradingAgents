"""Unit tests for trading_rules.py — shared pure functions.

Tests written FIRST (TDD Red phase).
"""

import pytest
from decimal import Decimal


class TestDetermineSide:
    """Test side determination: signal + trade direction → Buy/Sell."""

    def test_buy_signal_straight_direction(self):
        from backend.services.trading_rules import determine_side
        assert determine_side("buy", "straight") == "Buy"

    def test_sell_signal_straight_direction(self):
        from backend.services.trading_rules import determine_side
        assert determine_side("sell", "straight") == "Sell"

    def test_buy_signal_reverse_direction(self):
        from backend.services.trading_rules import determine_side
        assert determine_side("buy", "reverse") == "Sell"

    def test_sell_signal_reverse_direction(self):
        from backend.services.trading_rules import determine_side
        assert determine_side("sell", "reverse") == "Buy"


class TestComputeTpSl:
    """Test TP/SL price calculation from leverage-adjusted percentages."""

    def test_long_tp_sl_20x_leverage(self):
        from backend.services.trading_rules import compute_tp_sl
        # tp_pct=100% at 20x → 5% price move; sl_pct=50% at 20x → 2.5% price move
        tp, sl = compute_tp_sl(entry=50000.0, side="Buy", tp_pct=100.0, sl_pct=50.0, leverage=20)
        assert abs(tp - 52500.0) < 0.01  # 50000 * 1.05
        assert abs(sl - 48750.0) < 0.01  # 50000 * 0.975

    def test_short_tp_sl_20x_leverage(self):
        from backend.services.trading_rules import compute_tp_sl
        tp, sl = compute_tp_sl(entry=50000.0, side="Sell", tp_pct=100.0, sl_pct=50.0, leverage=20)
        assert abs(tp - 47500.0) < 0.01  # 50000 * 0.95
        assert abs(sl - 51250.0) < 0.01  # 50000 * 1.025

    def test_100x_leverage_small_moves(self):
        from backend.services.trading_rules import compute_tp_sl
        # tp_pct=150% at 100x → 1.5% price move
        tp, sl = compute_tp_sl(entry=1000.0, side="Buy", tp_pct=150.0, sl_pct=100.0, leverage=100)
        assert abs(tp - 1015.0) < 0.01   # 1000 * 1.015
        assert abs(sl - 990.0) < 0.01    # 1000 * 0.99


class TestComputePositionSize:
    """Test position sizing: capital_pct × leverage / entry_price, rounded to qty_step."""

    def test_basic_sizing(self):
        from backend.services.trading_rules import compute_position_size
        # 10000 capital, 5% = 500 margin, ×20 leverage = 10000 notional, /50000 = 0.2 BTC
        qty = compute_position_size(sizing_capital=10000.0, capital_pct=5.0, leverage=20, price=50000.0, qty_step=0.001, min_qty=0.001)
        assert qty == 0.2

    def test_rounds_down_to_qty_step(self):
        from backend.services.trading_rules import compute_position_size
        # Would be 0.1234... but qty_step=0.01 → rounds to 0.12
        qty = compute_position_size(sizing_capital=1000.0, capital_pct=10.0, leverage=10, price=8111.0, qty_step=0.01, min_qty=0.01)
        assert qty == 0.12  # floor(1.2329.../0.01) * 0.01

    def test_below_min_qty_returns_none(self):
        from backend.services.trading_rules import compute_position_size
        # Tiny capital → qty too small
        qty = compute_position_size(sizing_capital=10.0, capital_pct=1.0, leverage=1, price=50000.0, qty_step=0.001, min_qty=0.001)
        assert qty is None  # 0.000002 < 0.001

    def test_insufficient_available_balance_returns_none(self):
        from backend.services.trading_rules import compute_position_size
        # sizing_capital=10000, 5% = 500 margin needed, but only 400 available
        qty = compute_position_size(sizing_capital=10000.0, capital_pct=5.0, leverage=20, price=50000.0, qty_step=0.001, min_qty=0.001, available_balance=400.0)
        assert qty is None

    def test_sufficient_available_balance_passes(self):
        from backend.services.trading_rules import compute_position_size
        # sizing_capital=10000, 5% = 500 margin needed, 600 available → OK
        qty = compute_position_size(sizing_capital=10000.0, capital_pct=5.0, leverage=20, price=50000.0, qty_step=0.001, min_qty=0.001, available_balance=600.0)
        assert qty == 0.2


class TestRoundPriceToTick:
    """round_price_to_tick rounds DOWN to the tick, mirroring production, but must
    NEVER return a non-positive price (which would fabricate a ~100% PnL)."""

    def test_rounds_down_to_tick(self):
        from backend.services.trading_rules import round_price_to_tick
        assert round_price_to_tick(52503.15, 5.0) == pytest.approx(52500.0)
        assert round_price_to_tick(52500.0, 5.0) == pytest.approx(52500.0)
        assert round_price_to_tick(0.012345, 0.0001) == pytest.approx(0.0123, abs=1e-9)

    def test_non_positive_tick_returns_unchanged(self):
        from backend.services.trading_rules import round_price_to_tick
        assert round_price_to_tick(123.45, 0.0) == 123.45
        assert round_price_to_tick(123.45, -1.0) == 123.45

    def test_tick_coarser_than_price_keeps_exact_price_not_zero(self):
        """A sub-tick price (e.g. a 0.005 perp with a 0.01 tick) must NOT floor to 0 —
        a 0 TP/SL would be treated as a real trigger and fabricate near-100% PnL.
        Regression guard: round returns the exact price instead of 0."""
        from backend.services.trading_rules import round_price_to_tick
        assert round_price_to_tick(0.00525, 0.01) == pytest.approx(0.00525)
        assert round_price_to_tick(0.005, 0.01) == pytest.approx(0.005)
        # Result is always strictly positive for a positive input.
        assert round_price_to_tick(0.00525, 0.01) > 0


class TestComputeLiquidationPrice:
    """Test liquidation price for isolated margin."""


    def test_long_20x(self):
        from backend.services.trading_rules import compute_liquidation_price
        # liq = entry × (1 - (1/leverage - MMR)) = 50000 × (1 - (0.05 - 0.005)) = 50000 × 0.955 = 47750
        liq = compute_liquidation_price(entry=50000.0, side="Buy", leverage=20)
        assert abs(liq - 47750.0) < 0.01

    def test_short_20x(self):
        from backend.services.trading_rules import compute_liquidation_price
        # liq = entry × (1 + (1/leverage - MMR)) = 50000 × (1 + 0.045) = 52250
        liq = compute_liquidation_price(entry=50000.0, side="Sell", leverage=20)
        assert abs(liq - 52250.0) < 0.01


class TestComputeUnrealizedPnl:
    """Test unrealized PnL calculation."""

    def test_long_profit(self):
        from backend.services.trading_rules import compute_unrealized_pnl
        pnl = compute_unrealized_pnl(entry=50000.0, current=51000.0, qty=0.1, side="Buy")
        assert abs(pnl - 100.0) < 0.001  # (51000-50000) * 0.1

    def test_short_profit(self):
        from backend.services.trading_rules import compute_unrealized_pnl
        pnl = compute_unrealized_pnl(entry=50000.0, current=49000.0, qty=0.1, side="Sell")
        assert abs(pnl - 100.0) < 0.001  # (50000-49000) * 0.1

    def test_long_loss(self):
        from backend.services.trading_rules import compute_unrealized_pnl
        pnl = compute_unrealized_pnl(entry=50000.0, current=49500.0, qty=0.2, side="Buy")
        assert abs(pnl - (-100.0)) < 0.001


class TestEquityChecks:
    """Test equity rise/drop threshold checks."""

    def test_equity_rise_triggers(self):
        from backend.services.trading_rules import check_equity_rise
        assert check_equity_rise(equity=10500.0, reference=10000.0, threshold=5.0) is True

    def test_equity_rise_below_threshold(self):
        from backend.services.trading_rules import check_equity_rise
        assert check_equity_rise(equity=10400.0, reference=10000.0, threshold=5.0) is False

    def test_equity_drop_triggers(self):
        from backend.services.trading_rules import check_equity_drop
        assert check_equity_drop(equity=9000.0, reference=10000.0, threshold=10.0) is True

    def test_equity_drop_below_threshold(self):
        from backend.services.trading_rules import check_equity_drop
        assert check_equity_drop(equity=9100.0, reference=10000.0, threshold=10.0) is False


class TestTrailingTrigger:
    """Test trailing profit trigger check."""

    def test_triggers_at_50_percent_drawdown(self):
        from backend.services.trading_rules import check_trailing_trigger
        # Peak was 10, current is 4.9 → below 50% → triggers
        assert check_trailing_trigger(per_unit_pnl=4.9, peak=10.0) is True

    def test_does_not_trigger_above_50_percent(self):
        from backend.services.trading_rules import check_trailing_trigger
        assert check_trailing_trigger(per_unit_pnl=5.1, peak=10.0) is False

    def test_exactly_at_boundary(self):
        from backend.services.trading_rules import check_trailing_trigger
        # At exactly 50% — should NOT trigger (need to be strictly below)
        assert check_trailing_trigger(per_unit_pnl=5.0, peak=10.0) is False


class TestApplySlippage:
    """Test slippage application to entry price."""

    def test_buy_slippage_increases_price(self):
        from backend.services.trading_rules import apply_slippage
        result = apply_slippage(price=50000.0, side="Buy", slippage_bps=2)
        assert result == 50010.0  # 50000 * (1 + 2/10000)

    def test_sell_slippage_decreases_price(self):
        from backend.services.trading_rules import apply_slippage
        result = apply_slippage(price=50000.0, side="Sell", slippage_bps=2)
        assert result == 49990.0  # 50000 * (1 - 2/10000)

    def test_zero_slippage(self):
        from backend.services.trading_rules import apply_slippage
        assert apply_slippage(price=100.0, side="Buy", slippage_bps=0) == 100.0


class TestComputeFee:
    """Test fee calculation."""

    def test_standard_taker_fee(self):
        from backend.services.trading_rules import compute_fee
        # 0.1 BTC × $50000 × 0.055% = $2.75
        fee = compute_fee(qty=0.1, price=50000.0, fee_rate_pct=0.055)
        assert abs(fee - 2.75) < 0.001


class TestComputeBreakevenPrice:
    """Test breakeven TP price after timeout."""

    def test_long_breakeven(self):
        from backend.services.trading_rules import compute_breakeven_price
        # entry × (1 + 1/(leverage×100)) = 50000 × (1 + 1/2000) = 50000 × 1.0005 = 50025
        be = compute_breakeven_price(entry=50000.0, side="Buy", leverage=20)
        assert abs(be - 50025.0) < 0.01

    def test_short_breakeven(self):
        from backend.services.trading_rules import compute_breakeven_price
        # entry × (1 - 1/(leverage×100)) = 50000 × (1 - 1/2000) = 50000 × 0.9995 = 49975
        be = compute_breakeven_price(entry=50000.0, side="Sell", leverage=20)
        assert abs(be - 49975.0) < 0.01


class TestCloseOnProfit:
    """Test close_on_profit_pct threshold check with target_goal_value."""

    def test_triggers_with_target_goal(self):
        from backend.services.trading_rules import check_close_on_profit
        # close_on_profit_pct=50, target_goal_value=10 → effective_threshold = 5%
        # equity=10500, start=10000 → 5% gain → triggers
        assert check_close_on_profit(equity=10500.0, cycle_start_equity=10000.0, close_on_profit_pct=50.0, target_goal_value=10.0) is True

    def test_does_not_trigger_below_effective_threshold(self):
        from backend.services.trading_rules import check_close_on_profit
        # close_on_profit_pct=50, target_goal_value=10 → effective_threshold = 5%
        # equity=10400, start=10000 → 4% < 5% → does not trigger
        assert check_close_on_profit(equity=10400.0, cycle_start_equity=10000.0, close_on_profit_pct=50.0, target_goal_value=10.0) is False

    def test_default_target_goal_100(self):
        from backend.services.trading_rules import check_close_on_profit
        # With default target_goal_value=100: effective_threshold = (5/100)*100 = 5%
        assert check_close_on_profit(equity=10500.0, cycle_start_equity=10000.0, close_on_profit_pct=5.0) is True
        assert check_close_on_profit(equity=10400.0, cycle_start_equity=10000.0, close_on_profit_pct=5.0) is False


class TestLiquidationPnl:
    """Test liquidation PnL (full margin loss)."""

    def test_full_margin_loss(self):
        from backend.services.trading_rules import compute_liquidation_pnl
        # margin=500, entry_fee=2.75 → loss = -502.75
        pnl = compute_liquidation_pnl(initial_margin=500.0, entry_fee=2.75)
        assert abs(pnl - (-502.75)) < 0.001


class TestTrailingActivation:
    """Test trailing profit activation guard."""

    def test_activates_when_profitable_and_above_threshold(self):
        from backend.services.trading_rules import check_trailing_activation
        # Price moved 5% from entry, upnl > 0, threshold = 3% → activates
        assert check_trailing_activation(current_price=52500.0, entry_price=50000.0, threshold_pct=3.0, upnl=250.0) is True

    def test_does_not_activate_when_upnl_negative(self):
        from backend.services.trading_rules import check_trailing_activation
        # Even if price distance is high, upnl <= 0 → guard prevents activation
        assert check_trailing_activation(current_price=52500.0, entry_price=50000.0, threshold_pct=3.0, upnl=-10.0) is False

    def test_does_not_activate_below_threshold(self):
        from backend.services.trading_rules import check_trailing_activation
        # Only 1% price move, threshold is 3% → not activated
        assert check_trailing_activation(current_price=50500.0, entry_price=50000.0, threshold_pct=3.0, upnl=50.0) is False

    def test_works_for_short_side(self):
        from backend.services.trading_rules import check_trailing_activation
        # Short: entry=50000, current=47500 → 5% move (abs), upnl>0
        assert check_trailing_activation(current_price=47500.0, entry_price=50000.0, threshold_pct=3.0, upnl=250.0) is True


class TestLockedMargin:
    """Test locked margin calculation."""

    def test_basic_locked_margin(self):
        from backend.services.trading_rules import compute_locked_margin
        # 0.2 BTC × $50000 / 20x leverage = $500
        margin = compute_locked_margin(qty=0.2, entry_price=50000.0, leverage=20)
        assert abs(margin - 500.0) < 0.001

    def test_high_leverage(self):
        from backend.services.trading_rules import compute_locked_margin
        # 1 BTC × $50000 / 100x = $500
        margin = compute_locked_margin(qty=1.0, entry_price=50000.0, leverage=100)
        assert abs(margin - 500.0) < 0.001


class TestLttbDownsample:
    """Test Largest Triangle Three Buckets downsampling."""

    def test_returns_target_n_points(self):
        from backend.services.trading_rules import lttb_downsample
        points = [{"x": i, "y": float(i)} for i in range(1000)]
        result = lttb_downsample(points, target_n=100)
        assert len(result) == 100

    def test_preserves_first_and_last(self):
        from backend.services.trading_rules import lttb_downsample
        points = [{"x": i, "y": float(i * i)} for i in range(500)]
        result = lttb_downsample(points, target_n=50)
        assert result[0] == points[0]
        assert result[-1] == points[-1]

    def test_returns_all_if_fewer_than_target(self):
        from backend.services.trading_rules import lttb_downsample
        points = [{"x": i, "y": float(i)} for i in range(10)]
        result = lttb_downsample(points, target_n=100)
        assert len(result) == 10

    def test_empty_list_returns_empty(self):
        from backend.services.trading_rules import lttb_downsample
        result = lttb_downsample([], target_n=100)
        assert result == []

    def test_single_point_returns_single(self):
        from backend.services.trading_rules import lttb_downsample
        points = [{"x": 0, "y": 42.0}]
        result = lttb_downsample(points, target_n=100)
        assert len(result) == 1
        assert result[0]["y"] == 42.0

    def test_two_points_returns_both(self):
        from backend.services.trading_rules import lttb_downsample
        points = [{"x": 0, "y": 1.0}, {"x": 1, "y": 2.0}]
        result = lttb_downsample(points, target_n=100)
        assert len(result) == 2
