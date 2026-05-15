# Phase 6: Comprehensive Testing

## Goal
Fill remaining test coverage gaps, add regression tests for existing functionality, edge case tests, security tests, and full lifecycle integration tests. Target 90%+ coverage on new code.

## Entry Criteria
- Phases 1-5 complete and passing

## Files to Create
- `tests/test_trade_lifecycle.py` — end-to-end lifecycle tests
- `tests/test_trade_security.py` — security-specific tests

## Files to Modify
- `tests/test_trade_repository.py` — add any missing edge cases
- `tests/test_trade_api.py` — add any missing edge cases
- `tests/test_trade_service.py` — add any missing edge cases

## Tasks

### TASK-048: Full lifecycle integration tests
**File:** `tests/test_trade_lifecycle.py`

1. `test_place_open_close_lifecycle` — AC-001 + AC-002: place trade → status=open → close → status=closed with PnL
2. `test_place_fail_lifecycle` — AC-018: place trade → Bybit reject → status=failed
3. `test_close_all_lifecycle` — AC-003: place 3 trades → close-all → all closed with close_reason=manual_close_all
4. `test_rule_triggered_close_lifecycle` — AC-004: place trades → trigger rule → all closed with close_reason=rule_triggered
5. `test_partial_close_lifecycle` — AC-010: place trade qty=1.0 → partial close qty=0.5 → parent=partially_closed, child=closed
6. `test_cancel_pending_lifecycle` — AC-011: place trade → cancel before fill → status=cancelled
7. `test_reconciliation_tp_lifecycle` — AC-005: place trade → simulate TP fill on Bybit → reconciliation detects → close_reason=take_profit
8. `test_reconciliation_sl_lifecycle` — AC-006: same for stop_loss
9. `test_orphan_cleanup_lifecycle` — AC-007: insert pending trade with no order_id → wait → reconciliation marks failed
10. `test_concurrent_close_lifecycle` — AC-009: two concurrent close attempts → one succeeds, one gets 409

### TASK-049: Security tests
**File:** `tests/test_trade_security.py`

1. `test_idor_cross_account_trade_access` — AC-013: access trade from wrong account → 404
2. `test_idor_cross_account_list` — list trades with wrong account_id → empty (not other account's trades)
3. `test_idor_cross_account_stats` — stats for wrong account → empty stats (not other account's data)
4. `test_sort_injection_blocked` — AC-014: sort=id → 400
5. `test_sort_sql_injection` — sort="created_at; DROP TABLE trades" → 400
6. `test_cursor_forged_cross_account` — forged cursor with different account_id's trade → not returned
7. `test_jsonb_key_allowlist` — metadata with invalid key → rejected
8. `test_jsonb_size_limit` — metadata > 8KB → rejected
9. `test_symbol_injection` — symbol="'; DROP TABLE" → 400
10. `test_trade_events_immutable_update` — AC-015: UPDATE trade_event → exception
11. `test_trade_events_immutable_delete` — DELETE trade_event without purge_mode → exception
12. `test_api_keys_not_in_error_responses` — Bybit error response contains no API keys

### TASK-050: Edge case tests
**File:** `tests/test_trade_lifecycle.py` (additional)

1. `test_close_on_pending_trade_409` — close a pending trade → INVALID_STATUS_TRANSITION
2. `test_close_on_failed_trade_409` — close a failed trade → INVALID_STATUS_TRANSITION
3. `test_partial_close_qty_exceeds_remaining_400` — partial close qty > remaining → 400
4. `test_partial_close_qty_zero_400` — qty=0 → 400
5. `test_duplicate_order_link_id_rejected` — unique constraint
6. `test_delete_account_with_trades_409` — ON DELETE RESTRICT → 409
7. `test_close_failure_position_gone_reconciles` — FR-055: Bybit close fails but position already gone → reconcile_close
8. `test_close_failure_position_exists_reverts_to_open` — Bybit close fails, position still exists → revert to open with version increment and event

### TASK-051: Regression tests for existing functionality
**File:** `tests/test_trade_lifecycle.py` (additional)

1. `test_existing_place_trade_still_works` — verify existing trade placement flow works with new DB write
2. `test_existing_close_all_still_works` — verify close-all still functions
3. `test_existing_cycle_trades_still_work` — verify cycle engine still functions
4. `test_existing_close_rules_still_trigger` — verify close rule evaluator still triggers

### TASK-052: Coverage verification
**Action:** Run pytest with coverage and verify 90%+ on new files

```bash
python -m pytest tests/test_trade_*.py --cov=backend/services/trade_repository --cov=backend/services/trade_service --cov=backend/services/trade_reconciliation --cov-report=term-missing -q
```

Verify:
- `trade_repository.py` ≥ 90%
- `trade_service.py` ≥ 90%
- `trade_reconciliation.py` ≥ 90%

If below 90%, add targeted tests for uncovered lines.

## Exit Criteria
- All test files pass
- 90%+ coverage on new service files
- No regressions on existing tests
- All 18 ACs verified by at least one test
- All security tests pass

## Verification Commands
```bash
python -m pytest tests/ -x -q --tb=short
python -m pytest tests/test_trade_*.py --cov=backend/services/trade_repository --cov=backend/services/trade_service --cov=backend/services/trade_reconciliation --cov-report=term-missing -q
```

## Traceability (AC coverage)
| AC | Test |
|----|------|
| AC-001 | test_place_open_close_lifecycle |
| AC-002 | test_place_open_close_lifecycle |
| AC-003 | test_close_all_lifecycle |
| AC-004 | test_rule_triggered_close_lifecycle |
| AC-005 | test_reconciliation_tp_lifecycle |
| AC-006 | test_reconciliation_sl_lifecycle |
| AC-007 | test_orphan_cleanup_lifecycle |
| AC-008 | test_list_trades_pagination_cursor (Phase 3) |
| AC-009 | test_concurrent_close_lifecycle |
| AC-010 | test_partial_close_lifecycle |
| AC-011 | test_cancel_pending_lifecycle |
| AC-012 | test_cancel_partially_filled (Phase 4) |
| AC-013 | test_idor_cross_account_trade_access |
| AC-014 | test_sort_injection_blocked |
| AC-015 | test_trade_events_immutable_update/delete |
| AC-016 | test_close_failure_checks_position (Phase 4) |
| AC-017 | test_reconcile_stuck_closing (Phase 5) |
| AC-018 | test_place_fail_lifecycle |
