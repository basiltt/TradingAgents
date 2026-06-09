# Breakeven Watch-and-Close-All — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `BREAKEVEN_TIMEOUT` from a one-shot "set TP to breakeven" into a windowed, account-level watch that closes ALL positions once total open unrealised PnL clears a fee buffer, in both the live evaluator and the backtest engine.

**Architecture:** Live (`close_rule_evaluator.py`): reclassify `BREAKEVEN_TIMEOUT` into the equity sweep, make `_check_condition` require both elapsed-time AND `pnl >= buffer` (buffer computed by the caller from live positions and passed in), and route firing through the generic close-all path (delete the special TP-set branch + `_handle_breakeven_timeout`). Backtest (`backtest_engine.py`): replace the per-position breakeven-TP block in `_evaluate_time_rules` with an account-level "close all when Σ uPnL >= Σ notional·rate·1.5 after breakeven time".

**Tech Stack:** Python 3.12 / asyncio, pytest + pytest-asyncio, Decimal for money math.

**Spec:** `docs/superpowers/specs/2026-06-10-breakeven-watch-close-design.md`

---

## File Structure

- **Modify** `backend/services/close_rule_evaluator.py`
  - Trigger sets (L31–38): remove `BREAKEVEN_TIMEOUT` from `_NON_EQUITY_TRIGGERS`.
  - Add module constants `BREAKEVEN_TAKER_RATE_PCT = Decimal("0.055")`, `BREAKEVEN_FEE_SLIPPAGE_MULT = Decimal("1.5")`.
  - Add `_breakeven_fee_buffer(positions) -> Decimal` helper.
  - `_check_condition`: add `breakeven_buffer: Optional[Decimal] = None` param; new compound BREAKEVEN logic.
  - `_evaluate_account_rules_with_data`: lazily compute the buffer when a past-its-time BREAKEVEN rule is present; pass into `_check_condition`; delete the special TP-set branch (L293–310).
  - Delete `_handle_breakeven_timeout` (L534–591).
- **Modify** `backend/services/backtest_engine.py`
  - `_evaluate_time_rules` (~L1869–1921): replace per-position breakeven-TP block with account-level watch-and-close-all.
- **Modify** `tests/backend/test_close_rule_evaluator.py`
  - Update `TestTimeBasedTriggers` breakeven cases to pass a buffer; add new buffer/compound tests; **delete** `test_handle_breakeven_timeout_with_tick_size`.
- **Modify** `tests/backend/test_engine_advanced_rules.py`
  - Rewrite `test_breakeven_timeout_modifies_tp` → `test_breakeven_closes_all_when_recovered`; keep `test_breakeven_not_applied_without_timeout` (adjust assertion).
- **New tests** in `tests/backend/test_close_rule_evaluator.py` and `tests/backend/test_engine_close_rules.py` (or advanced_rules) per Tasks below.

---

## Task 1: Live — fee-buffer helper + compound `_check_condition`

**Files:**
- Modify: `backend/services/close_rule_evaluator.py`
- Test: `tests/backend/test_close_rule_evaluator.py`

- [ ] **Step 1: Write failing tests for the buffer helper and compound condition**

Add to `tests/backend/test_close_rule_evaluator.py` (after the existing
`TestTimeBasedTriggers` class):

```python
class TestBreakevenFeeBuffer:
    def test_buffer_uses_position_value_when_present(self, evaluator: CloseRuleEvaluator) -> None:
        # notional 10000 + 5000 = 15000; buffer = 15000 * 0.055/100 * 1.5 = 12.375
        positions = [
            {"symbol": "BTCUSDT", "positionValue": "10000"},
            {"symbol": "ETHUSDT", "positionValue": "5000"},
        ]
        buf = evaluator._breakeven_fee_buffer(positions)
        assert buf == Decimal("15000") * Decimal("0.055") / Decimal("100") * Decimal("1.5")

    def test_buffer_falls_back_to_size_times_mark(self, evaluator: CloseRuleEvaluator) -> None:
        # no positionValue → size * markPrice = 0.5 * 20000 = 10000
        positions = [{"symbol": "BTCUSDT", "size": "0.5", "markPrice": "20000"}]
        buf = evaluator._breakeven_fee_buffer(positions)
        assert buf == Decimal("10000") * Decimal("0.055") / Decimal("100") * Decimal("1.5")

    def test_buffer_empty_positions_is_zero(self, evaluator: CloseRuleEvaluator) -> None:
        assert evaluator._breakeven_fee_buffer([]) == Decimal("0")


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
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py::TestBreakevenFeeBuffer tests/backend/test_close_rule_evaluator.py::TestBreakevenCompound -q`
Expected: FAIL (`_breakeven_fee_buffer` missing; `_check_condition` has no `breakeven_buffer` kwarg; old behavior returns True on elapsed regardless of pnl).

- [ ] **Step 3: Add module constants**

In `backend/services/close_rule_evaluator.py`, after the trigger-set definitions
(after L38), add:

```python
# Breakeven watch-and-close: after breakeven_timeout_hours, the account closes ALL
# positions once total open unrealised PnL clears this fee buffer, so the mass close
# nets ~flat after taker fees rather than a small loss. Buffer = Σ notional × rate ×
# slippage_mult. Live wallet frames carry no config fee rate, so use the Bybit
# USDT-perp taker rate as a fixed conservative estimate.
BREAKEVEN_TAKER_RATE_PCT = Decimal("0.055")
BREAKEVEN_FEE_SLIPPAGE_MULT = Decimal("1.5")
```

(`Decimal` is already imported at L9.)

- [ ] **Step 4: Add the `_breakeven_fee_buffer` helper**

Add as a method on `CloseRuleEvaluator`, placed just above `_check_condition`:

```python
def _breakeven_fee_buffer(self, positions: list[dict]) -> Decimal:
    """Σ over open positions of notional × taker_rate × slippage_mult.

    Notional prefers the exchange-computed ``positionValue``; falls back to
    ``size × markPrice``. Returns Decimal("0") for an empty/missing book (then
    the watch closes as soon as total uPnL ≥ 0). Never raises — a malformed
    position contributes 0 rather than aborting the sweep.
    """
    total_notional = Decimal("0")
    for p in positions or []:
        try:
            pv = p.get("positionValue")
            if pv is not None and str(pv).strip() != "":
                notional = abs(Decimal(str(pv)))
            else:
                size = Decimal(str(p.get("size") or "0"))
                mark = Decimal(str(p.get("markPrice") or p.get("mark_price") or "0"))
                notional = abs(size * mark)
            total_notional += notional
        except (ValueError, TypeError, ArithmeticError):
            continue
    return total_notional * BREAKEVEN_TAKER_RATE_PCT / Decimal("100") * BREAKEVEN_FEE_SLIPPAGE_MULT
```

- [ ] **Step 5: Make `_check_condition` compound for BREAKEVEN_TIMEOUT**

In `_check_condition` (currently L385–396), change the signature and the
time-trigger branch. Replace:

```python
    def _check_condition(
        self,
        rule: dict,
        equity: Decimal,
        pnl: Decimal,
        balance: Decimal,
    ) -> bool:
        trigger_type = rule["trigger_type"]

        # Time-based rules: check elapsed time, don't parse reference as Decimal
        if trigger_type in _TIME_TRIGGERS:
            return self._check_time_elapsed(rule)
```

with:

```python
    def _check_condition(
        self,
        rule: dict,
        equity: Decimal,
        pnl: Decimal,
        balance: Decimal,
        breakeven_buffer: Optional[Decimal] = None,
    ) -> bool:
        trigger_type = rule["trigger_type"]

        # MAX_DURATION: pure elapsed-time force close.
        if trigger_type == "MAX_DURATION":
            return self._check_time_elapsed(rule)

        # BREAKEVEN_TIMEOUT: windowed account-level watch. After breakeven time
        # elapses, fire only when total open unrealised PnL has recovered to >= the
        # fee buffer (so the mass close nets ~flat). Before the time, never fire.
        # If the buffer is unknown (no position data passed by the caller), fail
        # safe and do NOT close — we cannot confirm breakeven without notional.
        if trigger_type == "BREAKEVEN_TIMEOUT":
            if not self._check_time_elapsed(rule):
                return False
            if breakeven_buffer is None:
                return False
            return pnl >= breakeven_buffer
```

(`Optional` is already imported at L10. Note `_TIME_TRIGGERS` is still used by the
WS-path classification, so leave that frozenset as-is.)

- [ ] **Step 6: Run the new tests, verify they pass**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py::TestBreakevenFeeBuffer tests/backend/test_close_rule_evaluator.py::TestBreakevenCompound -q`
Expected: PASS.

- [ ] **Step 7: Update the pre-existing offset-naive time-trigger test**

`TestTimeBasedTriggers.test_offset_naive_datetime_fallback` (L177) asserts an
elapsed BREAKEVEN returns True with `pnl=0`. Under the new semantics that must now
pass a buffer + sufficient pnl. Replace that test body with:

```python
    def test_offset_naive_datetime_fallback(self, evaluator: CloseRuleEvaluator) -> None:
        from datetime import datetime, timezone, timedelta
        # Naive datetime 3 hours ago → still parsed as elapsed; with pnl >= buffer it fires.
        ref = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None).isoformat()
        rule = _make_rule("BREAKEVEN_TIMEOUT", "2", ref)
        assert evaluator._check_condition(
            rule, Decimal("0"), Decimal("100"), Decimal("0"), breakeven_buffer=Decimal("10")
        ) is True
```

`test_not_elapsed_yet` (BREAKEVEN, ref=now → False via time gate) and the
MAX_DURATION tests are unaffected — leave them.

- [ ] **Step 8: Run the full evaluator unit file**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py -q`
Expected: PASS. (`test_handle_breakeven_timeout_with_tick_size` still passes here —
the method is deleted in Task 2.)

- [ ] **Step 9: Commit**

```bash
git add backend/services/close_rule_evaluator.py tests/backend/test_close_rule_evaluator.py
git commit -m "feat(close-rules): breakeven fee buffer + compound time/PnL condition"
```

---

## Task 2: Live — wire buffer into the sweep, route breakeven through close-all, delete TP-set

**Files:**
- Modify: `backend/services/close_rule_evaluator.py`
- Test: `tests/backend/test_close_rule_evaluator.py`

- [ ] **Step 1: Write a failing integration test for the firing path**

Add to `tests/backend/test_close_rule_evaluator.py`:

```python
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
    # notional 1000 → buffer = 1000 * 0.055/100 * 1.5 = 0.825; pnl 5 clears it.
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
    """After breakeven time but uPnL below buffer → no close, rule stays active."""
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal as D
    from unittest.mock import AsyncMock
    from backend.services.close_rule_evaluator import CloseRuleEvaluator

    close_service = AsyncMock()
    accounts = AsyncMock()
    # notional 100000 → buffer = 100000 * 0.055/100 * 1.5 = 82.5; pnl 5 < 82.5.
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py::test_breakeven_fires_close_all_when_recovered tests/backend/test_close_rule_evaluator.py::test_breakeven_does_not_fire_when_pnl_below_buffer -q`
Expected: FAIL (caller doesn't compute/pass buffer; the old special branch sets TP
instead of calling close_all_for_rule).

- [ ] **Step 3: Compute and pass the buffer in `_evaluate_account_rules_with_data`**

At the top of the `for rule in rules:` loop body in
`_evaluate_account_rules_with_data` (currently L281), compute the buffer lazily and
pass it to `_check_condition`. Replace the existing call (L283):

```python
                triggered = self._check_condition(rule, equity=equity, pnl=pnl, balance=balance)
```

with:

```python
                breakeven_buffer = None
                if rule["trigger_type"] == "BREAKEVEN_TIMEOUT" and self._check_time_elapsed(rule):
                    # Past the breakeven window — fetch positions once to size the fee
                    # buffer. Fail safe: on any error leave buffer None (condition won't
                    # fire) rather than mass-closing on incomplete data.
                    try:
                        positions = await self._accounts_service.get_positions(account_id)
                        breakeven_buffer = self._breakeven_fee_buffer(positions or [])
                    except Exception:
                        logger.warning("breakeven_buffer_fetch_failed", extra={"account_id": account_id, "rule_id": rule.get("id")})
                        breakeven_buffer = None
                triggered = self._check_condition(
                    rule, equity=equity, pnl=pnl, balance=balance, breakeven_buffer=breakeven_buffer,
                )
```

- [ ] **Step 4: Delete the special BREAKEVEN_TIMEOUT branch**

Remove the entire block at L293–310 (the `# BREAKEVEN_TIMEOUT: modify TP instead of
closing` branch — from `if rule["trigger_type"] == "BREAKEVEN_TIMEOUT":` through its
trailing `continue`). After deletion, a triggered BREAKEVEN_TIMEOUT falls straight
into the generic close path (the `try:` at the old L311) exactly like MAX_DURATION:
`close_all_for_rule(account_id, rule["id"])` → `status="executed"` →
`deactivate_rules_for_account(exclude_rule_id=rule["id"])` → `break`.

- [ ] **Step 5: Delete the now-dead `_handle_breakeven_timeout` method**

Remove the whole `async def _handle_breakeven_timeout(self, account_id, rule)`
method (currently L534–591). It has no remaining caller after Step 4.

- [ ] **Step 6: Remove the now-unused trailing-skip reference (if any) and verify imports**

Confirm `compute_breakeven_price` is NOT imported in this file (it was only used by
the deleted method — grep). The live import line at L12 imports
`check_trailing_trigger` only; leave it. Run a syntax check:

Run: `python -c "import ast; ast.parse(open('backend/services/close_rule_evaluator.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Delete the obsolete TP-set unit test**

Remove `test_handle_breakeven_timeout_with_tick_size` (L187–end of that function)
from `tests/backend/test_close_rule_evaluator.py` — it tests the deleted method.

- [ ] **Step 8: Run the new integration tests + full evaluator file**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py tests/backend/test_close_rule_evaluator_ws.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/services/close_rule_evaluator.py tests/backend/test_close_rule_evaluator.py
git commit -m "feat(close-rules): breakeven watch closes all via generic path; drop one-shot TP-set"
```

---

## Task 3: Backtest — account-level breakeven watch-and-close-all

**Files:**
- Modify: `backend/services/backtest_engine.py`
- Test: `tests/backend/test_engine_advanced_rules.py`

- [ ] **Step 1: Rewrite the existing breakeven backtest test to the new behavior**

In `tests/backend/test_engine_advanced_rules.py`, replace
`test_breakeven_timeout_modifies_tp` (L160–192) with:

```python
    def test_breakeven_closes_all_when_recovered(self):
        """After breakeven time, once total open uPnL >= fee buffer the position is
        force-closed with reason 'breakeven' (not 'tp', not 'max_duration')."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            breakeven_timeout_hours=1.0,
            take_profit_pct=500.0,   # wide → never hit
            stop_loss_pct=500.0,     # wide → never hit
            max_trade_duration_hours=5.0,  # backstop, later than the recovery
            leverage=20, capital_pct=5.0, fee_rate_pct=0.055, slippage_bps=0,
        )
        signals = [_make_signal()]

        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Underwater through breakeven time (1h), then recovers above entry → uPnL
        # clears the tiny fee buffer → close all as 'breakeven'.
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50000.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=30), "open": 50000.0, "high": 50000.0, "low": 49500.0, "close": 49600.0, "volume": 100.0},
            # 90 min: past breakeven time, still slightly under water → no close yet
            {"open_time": base_time + timedelta(minutes=90), "open": 49600.0, "high": 49900.0, "low": 49500.0, "close": 49800.0, "volume": 100.0},
            # 120 min: recovers above entry → uPnL positive, clears buffer → breakeven close
            {"open_time": base_time + timedelta(minutes=120), "open": 49800.0, "high": 50200.0, "low": 49800.0, "close": 50100.0, "volume": 100.0},
        ]}

        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "breakeven", result.trades[0]["close_reason"]

    def test_breakeven_never_recovers_force_closes_at_max_duration(self):
        """If uPnL never recovers, the position is force-closed at max_duration, not breakeven."""
        from backend.services.backtest_engine import BacktestEngine

        engine = BacktestEngine()
        config = _make_config(
            breakeven_timeout_hours=1.0,
            take_profit_pct=500.0, stop_loss_pct=500.0,
            max_trade_duration_hours=2.0,
            leverage=20, capital_pct=5.0, fee_rate_pct=0.055, slippage_bps=0,
        )
        signals = [_make_signal()]
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        # Stays underwater the whole time → never breaks even → max_duration at 2h.
        klines = {"BTCUSDT": [
            {"open_time": base_time, "open": 50000.0, "high": 50000.0, "low": 49900.0, "close": 50000.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=60), "open": 50000.0, "high": 49800.0, "low": 49000.0, "close": 49200.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=120), "open": 49200.0, "high": 49300.0, "low": 49000.0, "close": 49100.0, "volume": 100.0},
            {"open_time": base_time + timedelta(minutes=180), "open": 49100.0, "high": 49200.0, "low": 49000.0, "close": 49100.0, "volume": 100.0},
        ]}
        result = engine.run(config, signals, klines)
        assert len(result.trades) == 1
        assert result.trades[0]["close_reason"] == "max_duration", result.trades[0]["close_reason"]
```

Also update `test_breakeven_not_applied_without_timeout` (L194): its assertion
`close_reason != "tp"` is still valid; leave it (control case unaffected).

- [ ] **Step 2: Run, verify the new tests fail**

Run: `python -m pytest tests/backend/test_engine_advanced_rules.py -k breakeven -q`
Expected: FAIL — current engine sets TP to breakeven (closes via 'tp') instead of a
'breakeven' force-close.

- [ ] **Step 3: Replace the breakeven block in `_evaluate_time_rules`**

In `backend/services/backtest_engine.py`, the current loop (L1893–1913) sets a
per-position breakeven TP. Replace the BREAKEVEN_TIMEOUT handling so it becomes an
account-level watch. Change the per-position loop body — remove the breakeven-TP
branch (the `if breakeven_hours and elapsed_hours >= breakeven_hours:` block at
L1906–1913) — and after the existing per-position loop that appends MR/MAX_DURATION
closes, add an account-level breakeven evaluation. Concretely, after the
`for pos in list(state.open_positions):` loop (which still handles MR time-stop and
MAX_DURATION), insert:

```python
        # BREAKEVEN_TIMEOUT (account-level): once the cycle has aged past the breakeven
        # window, close ALL remaining open positions the moment total open unrealised
        # PnL clears the fee buffer (Σ notional × fee_rate × 1.5), so the mass close
        # nets ~flat after taker fees. Mirrors live close_rule_evaluator. Positions
        # already queued for MR/MAX_DURATION close above are excluded.
        if breakeven_hours:
            from backend.services.trading_rules import compute_unrealized_pnl
            already = {id(p) for p, _ in positions_to_close}
            remaining = [p for p in state.open_positions if id(p) not in already]
            if remaining:
                oldest_elapsed = max(
                    (candle_time - p.entry_time).total_seconds() / 3600.0 for p in remaining
                )
                if oldest_elapsed >= breakeven_hours:
                    total_upnl = 0.0
                    total_buffer = 0.0
                    for p in remaining:
                        mark = (latest_prices or {}).get(p.symbol, p.entry_price)
                        ref = p.equity_ref_entry or p.entry_price
                        total_upnl += compute_unrealized_pnl(ref, mark, p.qty, p.side)
                        total_buffer += p.qty * mark * (fee_rate / 100.0) * 1.5
                    if total_upnl >= total_buffer:
                        for p in remaining:
                            positions_to_close.append((p, "breakeven"))
```

`fee_rate` is the method parameter (do NOT re-read it from config — `_evaluate_time_rules(self, config, state, candle_time, fee_rate, latest_prices)` already receives it). Also update the method docstring (L1872) from "BREAKEVEN_TIMEOUT: modifies TP to breakeven (does NOT close)." to "BREAKEVEN_TIMEOUT: account-level — closes ALL remaining positions once total open uPnL ≥ fee buffer, after the breakeven window."

- [ ] **Step 4: Confirm `compute_breakeven_price` import is removed if now unused**

The old block imported `compute_breakeven_price` (L1879). After removing the
breakeven-TP branch, check whether it's still referenced in this method. If not,
delete the `from backend.services.trading_rules import compute_breakeven_price`
line at L1879.

Run: `grep -n "compute_breakeven_price" backend/services/backtest_engine.py`
Expected: no remaining usage in `_evaluate_time_rules` (remove the import if the
only hit was that method).

- [ ] **Step 5: Run the breakeven backtest tests, verify pass**

Run: `python -m pytest tests/backend/test_engine_advanced_rules.py -k breakeven -q`
Expected: PASS.

- [ ] **Step 5b: Rewrite the golden breakeven test to the new semantics**

`tests/backend/test_backtest_golden.py::TestGolden...::test_golden_breakeven_timeout_close`
(L575–601) is a HAND-WRITTEN golden assertion of the OLD TP-drop behavior
(`close_reason == "tp"`, exit ≈ 50050). It is NOT an auto-generated snapshot — edit
it directly. With the new semantics the same scenario (flat ~breakeven then a
+0.2% uptick after the breakeven window) closes ALL via `"breakeven"` at the candle
where uPnL clears the buffer. Replace the assertion tail (L595–600) with:

```python
        # The engine now closes the whole account at breakeven (not via a lowered TP):
        # once total open uPnL clears the fee buffer after the breakeven window, the
        # position force-closes with reason "breakeven" at the candle's mark.
        assert trade["close_reason"] == "breakeven"
        # Near-breakeven: net result is a small fraction of starting capital.
        assert abs(result.metrics["net_profit"]) < 0.01 * cfg["starting_capital"]
        _assert_reconciles(result, cfg)
```

Update the docstring (L576–579) to describe the watch-and-close-all behavior. Keep
`_assert_reconciles(result, cfg)` — the engine's PnL reconciliation guard must still
hold (Σ trade pnl == wallet delta) regardless of the close reason. If the exact
candle/exit price differs from the old run, that is expected; the reconciliation +
the `net_profit` bound are the invariants, not the specific exit price.

- [ ] **Step 6: Run the broader engine + golden suites**

Run: `python -m pytest tests/backend/test_engine_advanced_rules.py tests/backend/test_engine_close_rules.py tests/backend/test_backtest_engine.py tests/backend/test_backtest_golden.py -q`
Expected: PASS. Any other golden scenario that does NOT set
`breakeven_timeout_hours` must be byte-identical (unchanged) — if an unrelated
golden breaks, STOP and investigate; the breakeven change must not touch
non-breakeven paths.

- [ ] **Step 7: Commit**

```bash
git add backend/services/backtest_engine.py tests/backend/test_engine_advanced_rules.py tests/backend/test_backtest_golden.py
git commit -m "feat(backtest): breakeven watch-and-close-all for live parity"
```

---

## Task 4: Cross-cutting regression + verification

**Files:** none (verification only)

- [ ] **Step 1: Full blast-radius regression**

Run: `python -m pytest tests/backend/test_close_rule_evaluator.py tests/backend/test_close_rule_evaluator_ws.py tests/backend/test_close_positions_service_unit.py tests/backend/test_engine_advanced_rules.py tests/backend/test_engine_close_rules.py tests/backend/test_backtest_engine.py tests/backend/test_backtest_golden.py tests/backend/test_auto_trade_service_unit.py tests/backend/test_mr_time_stop.py -p no:cacheprovider -q --timeout=90`
Expected: all PASS.

- [ ] **Step 2: Confirm no dead references remain**

Run: `grep -rn "_handle_breakeven_timeout" backend/ tests/`
Expected: no hits (method + its test fully removed).

- [ ] **Step 3: Collect-only sanity**

Run: `python -m pytest tests/ --collect-only -q -p no:cacheprovider`
Expected: no import/collection errors.

---

## Notes for the implementer

- `_TIME_TRIGGERS` still includes BREAKEVEN_TIMEOUT (time gating) — do NOT remove it
  there. Only remove it from `_NON_EQUITY_TRIGGERS`.
- Rule creation in `auto_trade_service.py` is UNCHANGED — the rule's
  `threshold_value`/`reference_value` are already exactly what the new logic needs.
- The live buffer uses a fixed 0.055% taker rate (wallet frames carry no fee rate);
  the backtest uses the config's `fee_rate_pct`. This is an intentional, documented
  asymmetry (see spec); both clear typical round-trip taker cost.
- UI helper copy in `AutoTradeSection.tsx` ("Move to breakeven after") now slightly
  misdescribes the behavior — out of scope here, flagged as a follow-up.



