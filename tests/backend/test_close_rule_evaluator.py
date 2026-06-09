"""Tests for CloseRuleEvaluator._check_condition — pure logic, no I/O."""

from decimal import Decimal

import pytest

from backend.services.close_rule_evaluator import CloseRuleEvaluator


def _make_rule(trigger_type: str, threshold: str, reference: str | None = None) -> dict:
    rule = {"trigger_type": trigger_type, "threshold_value": threshold}
    if reference is not None:
        rule["reference_value"] = reference
    return rule


@pytest.fixture()
def evaluator():
    """CloseRuleEvaluator with None deps — only _check_condition is tested."""
    return CloseRuleEvaluator(close_service=None, accounts_service=None, db=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BALANCE_BELOW — uses equity <= threshold
# ---------------------------------------------------------------------------
class TestBalanceBelow:
    def test_below(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_BELOW", "1000")
        assert evaluator._check_condition(rule, Decimal("999"), Decimal("0"), Decimal("0")) is True

    def test_equal(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_BELOW", "1000")
        assert evaluator._check_condition(rule, Decimal("1000"), Decimal("0"), Decimal("0")) is True

    def test_above(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_BELOW", "1000")
        assert evaluator._check_condition(rule, Decimal("1001"), Decimal("0"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# BALANCE_ABOVE — uses equity >= threshold
# ---------------------------------------------------------------------------
class TestBalanceAbove:
    def test_above(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_ABOVE", "5000")
        assert evaluator._check_condition(rule, Decimal("5001"), Decimal("0"), Decimal("0")) is True

    def test_equal(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_ABOVE", "5000")
        assert evaluator._check_condition(rule, Decimal("5000"), Decimal("0"), Decimal("0")) is True

    def test_below(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_ABOVE", "5000")
        assert evaluator._check_condition(rule, Decimal("4999"), Decimal("0"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# PNL_BELOW — triggers when pnl <= -threshold
# ---------------------------------------------------------------------------
class TestPnlBelow:
    def test_loss_exceeds_threshold(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_BELOW", "200")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("-201"), Decimal("0")) is True

    def test_loss_equals_threshold(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_BELOW", "200")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("-200"), Decimal("0")) is True

    def test_loss_below_threshold(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_BELOW", "200")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("-199"), Decimal("0")) is False

    def test_positive_pnl(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_BELOW", "200")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("100"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# PNL_ABOVE — triggers when pnl >= threshold
# ---------------------------------------------------------------------------
class TestPnlAbove:
    def test_profit_exceeds(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_ABOVE", "500")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("501"), Decimal("0")) is True

    def test_profit_equals(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_ABOVE", "500")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("500"), Decimal("0")) is True

    def test_profit_below(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("PNL_ABOVE", "500")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("499"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# EQUITY_DROP_PCT — drop_pct = ((reference - equity) / reference) * 100
# ---------------------------------------------------------------------------
class TestEquityDropPct:
    def test_drop_exceeds(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT", "10", "1000")
        # equity 899 → drop_pct = 10.1%
        assert evaluator._check_condition(rule, Decimal("899"), Decimal("0"), Decimal("0")) is True

    def test_drop_exactly(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT", "10", "1000")
        assert evaluator._check_condition(rule, Decimal("900"), Decimal("0"), Decimal("0")) is True

    def test_drop_below_threshold(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT", "10", "1000")
        assert evaluator._check_condition(rule, Decimal("901"), Decimal("0"), Decimal("0")) is False

    def test_zero_reference_returns_false(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT", "10", "0")
        assert evaluator._check_condition(rule, Decimal("500"), Decimal("0"), Decimal("0")) is False

    def test_no_reference_returns_false(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT", "10")
        assert evaluator._check_condition(rule, Decimal("500"), Decimal("0"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# EQUITY_RISE_PCT — rise_pct = ((equity - reference) / reference) * 100
# ---------------------------------------------------------------------------
class TestEquityRisePct:
    def test_rise_exceeds(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_RISE_PCT", "20", "1000")
        assert evaluator._check_condition(rule, Decimal("1201"), Decimal("0"), Decimal("0")) is True

    def test_rise_exactly(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_RISE_PCT", "20", "1000")
        assert evaluator._check_condition(rule, Decimal("1200"), Decimal("0"), Decimal("0")) is True

    def test_rise_below_threshold(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_RISE_PCT", "20", "1000")
        assert evaluator._check_condition(rule, Decimal("1199"), Decimal("0"), Decimal("0")) is False

    def test_zero_reference_returns_false(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_RISE_PCT", "20", "0")
        assert evaluator._check_condition(rule, Decimal("1500"), Decimal("0"), Decimal("0")) is False

    def test_no_reference_returns_false(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_RISE_PCT", "20")
        assert evaluator._check_condition(rule, Decimal("1500"), Decimal("0"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# Unknown trigger type
# ---------------------------------------------------------------------------
class TestUnknownTrigger:
    def test_unknown_returns_false(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("NONSENSE", "100")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# BREAKEVEN_TIMEOUT & MAX_DURATION — time-based rules
# ---------------------------------------------------------------------------
class TestTimeBasedTriggers:
    def test_not_elapsed_yet(self, evaluator: CloseRuleEvaluator) -> None:
        from datetime import datetime, timezone
        # Set reference to current time
        ref = datetime.now(timezone.utc).isoformat()
        rule = _make_rule("BREAKEVEN_TIMEOUT", "2", ref)
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False

    def test_already_elapsed(self, evaluator: CloseRuleEvaluator) -> None:
        from datetime import datetime, timezone, timedelta
        # Set reference to 3 hours ago
        ref = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        rule = _make_rule("MAX_DURATION", "2", ref)
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is True

    def test_invalid_reference_format(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("MAX_DURATION", "2", "not-a-date")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False

    def test_offset_naive_datetime_fallback(self, evaluator: CloseRuleEvaluator) -> None:
        from datetime import datetime, timezone, timedelta
        # Naive datetime 3 hours ago → still parsed as elapsed; with pnl >= buffer it fires.
        ref = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None).isoformat()
        rule = _make_rule("BREAKEVEN_TIMEOUT", "2", ref)
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("100"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is True


class TestBreakevenFeeBuffer:
    def test_buffer_uses_position_value_when_present(self, evaluator: CloseRuleEvaluator) -> None:
        # notional 10000 + 5000 = 15000; buffer = 15000 * 0.055/100 * 1.5 = 12.375
        positions = [
            {"symbol": "BTCUSDT", "positionValue": "10000"},
            {"symbol": "ETHUSDT", "positionValue": "5000"},
        ]
        buf = evaluator._breakeven_fee_buffer(positions)
        assert buf == Decimal("12.375")

    def test_buffer_falls_back_to_size_times_mark(self, evaluator: CloseRuleEvaluator) -> None:
        # no positionValue → size * markPrice = 0.5 * 20000 = 10000; buffer = 8.25
        positions = [{"symbol": "BTCUSDT", "size": "0.5", "markPrice": "20000"}]
        buf = evaluator._breakeven_fee_buffer(positions)
        assert buf == Decimal("8.25")

    def test_buffer_empty_positions_is_zero(self, evaluator: CloseRuleEvaluator) -> None:
        assert evaluator._breakeven_fee_buffer([]) == Decimal("0")

    def test_buffer_short_negative_size_uses_abs(self, evaluator: CloseRuleEvaluator) -> None:
        # short position: size -0.5 * 20000 = -10000 → abs → 10000; buffer = 8.25
        positions = [{"symbol": "X", "size": "-0.5", "markPrice": "20000"}]
        assert evaluator._breakeven_fee_buffer(positions) == Decimal("8.25")

    def test_buffer_non_dict_element_returns_none(self, evaluator: CloseRuleEvaluator) -> None:
        # Fail-closed: a non-dict element cannot be parsed → None (do not close).
        assert evaluator._breakeven_fee_buffer([None]) is None

    def test_buffer_unparseable_value_returns_none(self, evaluator: CloseRuleEvaluator) -> None:
        # Fail-closed: a non-numeric notional → None (do not close).
        assert evaluator._breakeven_fee_buffer([{"positionValue": "abc"}]) is None

    def test_buffer_all_zero_fields_contributes_zero(self, evaluator: CloseRuleEvaluator) -> None:
        # All fields present and numerically 0 is legitimate → contributes 0, not None.
        assert evaluator._breakeven_fee_buffer([{"symbol": "X", "size": "0", "markPrice": "0"}]) == Decimal("0")


class TestBreakevenCompound:
    def _elapsed_rule(self):
        from datetime import datetime, timezone, timedelta
        ref = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        return _make_rule("BREAKEVEN_TIMEOUT", "2", ref)

    def _fresh_rule(self):
        from datetime import datetime, timezone
        return _make_rule("BREAKEVEN_TIMEOUT", "2", datetime.now(timezone.utc).isoformat())

    def test_before_time_never_fires_even_if_pnl_high(self, evaluator: CloseRuleEvaluator) -> None:
        rule = self._fresh_rule()
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("1000"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is False

    def test_after_time_pnl_below_buffer_does_not_fire(self, evaluator: CloseRuleEvaluator) -> None:
        rule = self._elapsed_rule()
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("5"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is False

    def test_after_time_pnl_at_buffer_fires(self, evaluator: CloseRuleEvaluator) -> None:
        rule = self._elapsed_rule()
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("10"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is True

    def test_after_time_pnl_above_buffer_fires(self, evaluator: CloseRuleEvaluator) -> None:
        rule = self._elapsed_rule()
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("50"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is True

    def test_after_time_no_buffer_provided_does_not_fire(self, evaluator: CloseRuleEvaluator) -> None:
        # Without position data the buffer is unknown → fail safe (do not close).
        rule = self._elapsed_rule()
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("1000"), Decimal("0")
        ) is False


# ---------------------------------------------------------------------------
# CRITICAL regression: equity<=0 must NEVER fire an equity-based close.
# A partial/bad WS wallet frame can yield equity=0; without this guard,
# EQUITY_DROP_PCT computes a 100% drop and BALANCE_BELOW fires → mass close.
# ---------------------------------------------------------------------------
class TestEquityZeroGuard:
    def test_balance_below_does_not_fire_on_zero_equity(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("BALANCE_BELOW", "1000")
        # equity=0 is below 1000 but must NOT trigger (bad reading, not a real drop)
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False

    def test_equity_drop_pct_does_not_fire_on_zero_equity(self, evaluator: CloseRuleEvaluator) -> None:
        # reference 5000, equity 0 → naive drop = 100% >= 10% would fire; guarded off
        rule = _make_rule("EQUITY_DROP_PCT", "10", reference="5000")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False

    def test_equity_drop_pct_smart_does_not_fire_on_zero_equity(self, evaluator: CloseRuleEvaluator) -> None:
        rule = _make_rule("EQUITY_DROP_PCT_SMART", "10", reference="5000")
        assert evaluator._check_condition(rule, Decimal("0"), Decimal("0"), Decimal("0")) is False

    def test_equity_drop_pct_still_fires_on_real_drop(self, evaluator: CloseRuleEvaluator) -> None:
        # a genuine drop (equity 4000 from reference 5000 = 20%) still triggers
        rule = _make_rule("EQUITY_DROP_PCT", "10", reference="5000")
        assert evaluator._check_condition(rule, Decimal("4000"), Decimal("0"), Decimal("0")) is True


# ---------------------------------------------------------------------------
# BREAKEVEN_TIMEOUT end-to-end: after the breakeven window, the rule closes ALL
# positions via the generic close path (close_all_for_rule) once total open
# unrealised PnL clears the fee buffer. These exercise the wiring added in Task 2
# (_evaluate_account_rules_with_data computes the buffer and passes it through).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_breakeven_fires_close_all_when_recovered():
    """After breakeven time, when total open uPnL >= fee buffer, the rule closes ALL
    via close_all_for_rule and transitions to executed."""
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal as D
    from unittest.mock import AsyncMock
    from backend.services.close_rule_evaluator import CloseRuleEvaluator

    close_service = AsyncMock()
    close_service.close_all_for_rule.return_value = {"closed": 2, "failed": 0}
    accounts = AsyncMock()
    # notional 1000 -> buffer = 1000 * 0.055/100 * 1.5 = 0.825; pnl 5 clears it.
    accounts.get_positions.return_value = [{"symbol": "BTCUSDT", "positionValue": "1000"}]
    db = AsyncMock()
    db.atomic_trigger_rule.return_value = True
    db.deactivate_rules_for_account.return_value = 0

    ev = CloseRuleEvaluator(close_service=close_service, accounts_service=accounts, db=db)
    ref = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    rule = {"id": "r1", "account_id": "acc1", "trigger_type": "BREAKEVEN_TIMEOUT",
            "threshold_value": "2", "reference_value": ref}

    await ev._evaluate_account_rules_with_data(
        "acc1", [rule], equity=D("1000"), pnl=D("5"), balance=D("1000")
    )
    close_service.close_all_for_rule.assert_awaited_once_with("acc1", "r1")
    db.update_close_rule.assert_any_await("r1", status="executed")


@pytest.mark.asyncio
async def test_breakeven_does_not_fire_when_pnl_below_buffer():
    """After breakeven time but uPnL below buffer -> no close, no trigger."""
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal as D
    from unittest.mock import AsyncMock
    from backend.services.close_rule_evaluator import CloseRuleEvaluator

    close_service = AsyncMock()
    accounts = AsyncMock()
    # notional 100000 -> buffer = 82.5; pnl 5 < 82.5.
    accounts.get_positions.return_value = [{"symbol": "BTCUSDT", "positionValue": "100000"}]
    db = AsyncMock()

    ev = CloseRuleEvaluator(close_service=close_service, accounts_service=accounts, db=db)
    ref = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    rule = {"id": "r1", "account_id": "acc1", "trigger_type": "BREAKEVEN_TIMEOUT",
            "threshold_value": "2", "reference_value": ref}

    await ev._evaluate_account_rules_with_data(
        "acc1", [rule], equity=D("1000"), pnl=D("5"), balance=D("1000")
    )
    close_service.close_all_for_rule.assert_not_awaited()
    db.atomic_trigger_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_breakeven_fails_closed_when_positions_unreadable():
    """If positions can't be fetched/parsed, buffer is None -> rule does NOT fire."""
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal as D
    from unittest.mock import AsyncMock
    from backend.services.close_rule_evaluator import CloseRuleEvaluator

    close_service = AsyncMock()
    accounts = AsyncMock()
    accounts.get_positions.side_effect = RuntimeError("api down")
    db = AsyncMock()

    ev = CloseRuleEvaluator(close_service=close_service, accounts_service=accounts, db=db)
    ref = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    rule = {"id": "r1", "account_id": "acc1", "trigger_type": "BREAKEVEN_TIMEOUT",
            "threshold_value": "2", "reference_value": ref}

    await ev._evaluate_account_rules_with_data(
        "acc1", [rule], equity=D("1000"), pnl=D("9999"), balance=D("1000")
    )
    close_service.close_all_for_rule.assert_not_awaited()
    db.atomic_trigger_rule.assert_not_awaited()
