# Profitability Research History

This document tracks all profitability research sessions, findings, recommendations, and their outcomes over time. Each research run appends to this file so future analyses can compare trends.

---

## 2026-06-04 — Initial Baseline Research

**Timestamp:** 2026-06-04 ~10:00 UTC  
**Total System PnL:** $1,370.92 across 4,858 closed trades  
**System Win Rate:** 50.3%  
**Avg PnL/Trade:** $0.33  
**Active Period:** ~2 weeks (May 20 – Jun 4, 2026)  
**Accounts:** 21 demo accounts, $100 starting capital each

### Configuration at Time of Research
- Scan interval: Every 3 hours (180 min)
- Coins scanned: ~570 per run
- Min score: 6
- Leverage: 5x–20x depending on account
- TP: 150% of margin (7.5% at 20x)
- SL: 100% of margin (5% at 20x)
- Drawdown limit: 10–12%
- Profit goal: 12–14%
- AI Manager: Enabled on 10 accounts

### Key Findings
1. **Score 7-8 signals dramatically outperform score 6** — $0.86 avg vs $0.32, 52.3% vs 45.7% win rate
2. **Scan duration (57-149 min) causes signal staleness** — early-analyzed coins are stale by execution
3. **Batch wipeouts from EQUITY_DROP_PCT rule** — one bad position closes all 5
4. **AI Manager execution pipeline is broken** — all 181 decisions have null execution_result
5. **5 toxic symbols cost -$418** (BIGTIMEUSDT, PLAYSOUTUSDT, SOXLUSDT, SPXUSDT, POWERUSDT)
6. **93% short bias** — system only works in bearish/ranging markets
7. **10x leverage has best risk-adjusted returns** — 52.8% win rate, $0.66 avg
8. **Manual close_all (profit lock) has best avg PnL** — $1.04 per trade

### Recommendations Made
| # | Recommendation | Priority | Status |
|---|---------------|----------|--------|
| 1 | Post-scan signal validation (price drift check) | HIGH | PENDING |
| 2 | Raise min_score from 6 to 7 | HIGH | PENDING |
| 3 | Per-position SL instead of batch EQUITY_DROP | HIGH | PENDING |
| 4 | Fix AI Manager execution pipeline | HIGH | PENDING |
| 5 | Symbol blacklist for toxic symbols | MEDIUM | PENDING |
| 6 | Reduce max_trades from 5 to 3 | MEDIUM | PENDING |
| 7 | Time-based signal weighting | MEDIUM | PENDING |
| 8 | Trailing stop after +2% profit | MEDIUM | PENDING |
| 9 | Lower EQUITY_RISE_PCT from 14% to 8% | LOW-MED | PENDING |
| 10 | AI Manager prevent-new-trades capability | LOW-MED | PENDING |

### Account Standings (sorted by PnL)
| Account | PnL | Trades | Win Rate |
|---------|-----|--------|----------|
| Autotrader | +$176.57 | 192 | 50.5% |
| Appu | +$172.20 | 85 | 68.2% |
| Jeffin | +$166.63 | 263 | 49.8% |
| Joyel | +$157.83 | 235 | 52.3% |
| Preethy | +$111.25 | 254 | 52.8% |
| Unni | +$92.47 | 90 | 52.2% |
| Brother | -$6.94 | 400 | 41.3% |
| Jerin | -$12.00 | 260 | 39.6% |
| Princy | -$19.44 | 257 | 42.8% |

### Notes
- Unni account grew from $93 to $219 (+136%) in 5 days
- Preethy peaked at $248 but AI Manager couldn't properly lock profits
- Appu has best PnL/trade ratio ($2.03) with fewest trades — evidence that quality > quantity
- 12 liquidations occurred ($129.68 lost) — these should be zero with proper SL

---

## 2026-06-04 — Implementation Session (Post-Research Fixes)

**Timestamp:** 2026-06-04 ~11:00–23:00 UTC  
**Type:** Code implementation (no new data analysis)  
**Trigger:** Implementing all recommendations from the 2026-06-04 initial baseline research

### Root Cause Fix: 93% Sell Signal Bias

The most critical discovery: the **Crypto Portfolio Manager** (`tradingagents/agents/crypto_analysts.py`) had NO rating scale definition in its prompt. The LLM filled the `PortfolioDecision.rating` field using training priors where "Sell" meant "avoid/exit" rather than "go short." This caused 93% of all PM decisions to output "Sell" regardless of the underlying analysis.

**Fix applied:**
- Added explicit 5-tier rating scale to the crypto PM prompt (Buy/Overweight/Hold/Underweight/Sell) with clear directional semantics for futures trading
- Clarified that "Sell = strong conviction to go SHORT" and "Buy = strong conviction to go LONG"
- Fixed `_rating_to_direction()` mapping: Underweight now correctly maps to "sell" (was mapping to "hold")

**Files changed:** `tradingagents/agents/crypto_analysts.py`, `backend/services/scanner_service.py`

### Code Implementations from Report Recommendations

| # | Recommendation | Implementation | Files |
|---|---------------|---------------|-------|
| 1 | Post-scan signal validation | `max_price_drift_pct` config + drift check in `_try_trade` comparing `analysis_price` (from trader's entry_price) vs current mark price. Skips trade if price already moved >X% in signal direction. | `auto_trade_service.py`, `scanner_service.py`, `accounts_service.py`, `schemas/__init__.py` |
| 4 | Fix AI Manager execution pipeline | (a) ADJUST_TP_SL decisions now record immediate `{"status": "trailing_started"}` outcome. (b) Added `dry_run` gate before CLOSE execution — was missing, meaning dry_run=True still executed real closes. (c) Fixed test mocks that were masking the real test failures. | `ai_manager_task.py`, `test_ai_manager_task.py`, `test_ai_manager_sweep_defense.py` |
| 5 | Adaptive blacklist | `adaptive_blacklist_enabled` config + `_compute_adaptive_blacklist()` queries `signal_performance` table for symbols with <30% win rate over configurable lookback. Pre-injected into executor configs at scan start. | `scanner_service.py`, `auto_trade_service.py`, `schemas/__init__.py` |
| 7 | Time-based signal weighting | `execute_batch` sort key changed to `(abs(score), completed_at)` descending — at equal score, fresher signals are prioritized over staler ones. | `auto_trade_service.py` |
| New | Sector concentration limit | `max_same_sector` config limits how many positions can be in the same crypto sector (l1, l2, defi, meme, ai, gaming, infra, exchange). | `auto_trade_service.py`, `sector_map.py` (new), `schemas/__init__.py` |
| New | Dynamic sector classification | `SectorService` class: CoinGecko categories + LLM fallback + PostgreSQL DB cache (7-day TTL). Hot path is sync dict lookup (zero I/O). Symbols classified at scan start, capped at 50/batch to avoid rate limit delays. | `sector_service.py` (new), `sector_map.py` (new), `coingecko_data.py`, `scanner_service.py`, `main.py`, `persistence.py`, `async_persistence.py` |
| New | Orphan position alerting | Position reconciler now broadcasts WebSocket alert when exchange has positions with no matching DB trade record. | `position_reconciler.py` |

### Pre-Existing Features Verified Working (No Code Change Needed)

| Feature | Location | Notes |
|---------|----------|-------|
| Static blacklist/whitelist | `auto_trade_service.py:925-931` | `symbol_blacklist` and `symbol_whitelist` in AutoTradeConfig |
| Per-position trailing stop | close_rule_evaluator `_evaluate_trailing_profit` | `trailing_profit_pct` config creates `TRAILING_PROFIT` rule |
| AI pause-new-trades | `ai_manager_task.py:838-855` | `PAUSE_TRADING` action creates rule checked by auto-trade executor |
| max_same_direction limit | `auto_trade_service.py:952-960` | Prevents all positions being same direction |
| min_profit_to_close_ratio | `ai_manager_task.py:914-936` | Default 0.3 = AI won't close if profit < 30% of TP target |
| Per-trade TP/SL at order time | `accounts_service.py:286-301` | SL/TP prices set on Bybit at `place_market_order` |

### Items Requiring Config Changes Only (No Code Needed)

| Change | Config Field | Current | Recommended |
|--------|-------------|---------|-------------|
| Raise minimum score | `min_score` | 6 | 7 |
| Reduce positions per cycle | `max_trades` | 5 | 3 |
| Increase capital per trade | `capital_pct` | 9-15% | 18-20% |
| Relax drawdown threshold | `max_drawdown_pct` | 10-12% | 18-20% |
| Lower profit lock threshold | `target_goal_value` | 12-14% | 8% |

### New Config Fields Added

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_price_drift_pct` | float (0-50) | None (disabled) | Skip trade if price moved >X% in signal direction since analysis |
| `max_same_sector` | int (1-10) | None (disabled) | Max positions in same crypto sector |
| `adaptive_blacklist_enabled` | bool | false | Enable automatic symbol exclusion based on win rate |
| `adaptive_blacklist_min_trades` | int (2-50) | 5 | Min trades before symbol can be blacklisted |
| `adaptive_blacklist_max_win_rate` | float (0-100) | 30.0 | Win rate threshold below which symbol is excluded |
| `adaptive_blacklist_lookback_hours` | int (1-720) | 48 | How far back to look at trade history |

### Database Migrations Added

| Version | Table | Purpose |
|---------|-------|---------|
| v34 (sync) / v36 (async) | `symbol_sectors` | Caches sector classifications (symbol PK, sector, source, coingecko_categories, classified_at) |

### Tests Added/Fixed

| File | Tests | Notes |
|------|-------|-------|
| `tests/backend/test_sector_service.py` | 24 new tests | CG mapping, LLM fallback, cache behavior, ensure_classified |
| `tests/backend/test_ai_manager_task.py` | 49 tests (3 fixed) | Added `_llm_logger` AsyncMock, `_model_name` to fixture |
| `tests/backend/test_ai_manager_sweep_defense.py` | 4 tests (1 fixed) | Added `_ws_buffer` with positions to fixture |
| `tests/test_scanner_signal_structured.py` | Updated | `test_underweight_uses_sell` — asserts "sell" not "hold" |

### Safety Bugs Fixed

1. **`dry_run` mode was NOT preventing CLOSE actions** — only ADJUST_TP_SL had the dry_run gate. Fixed: added dry_run check before close execution path.
2. **Sweep defense test passing falsely** — `_ws_buffer` mock was wrong, causing `_handle_sweep_resolved` to silently skip SL restoration.
3. **Sector map had fictitious tokens** — JABORAUSDT, GABORAUSDT, ABORAUSDT were non-existent tokens in the static dict. Removed.
4. **DOGEUSDT duplicated** in sector map. IMXUSDT had conflicting sector assignments. Cleaned.

### Final Test Results

- **Total:** 423 passed, 0 failed (all previously failing tests now pass)
- **Previously failing:** `test_evaluate_close_executes`, `test_execution_exception_records_dead_letter`, `test_transition_to_resolved` — all now pass

### Recommendation Status Update

| # | Recommendation | Previous Status | New Status |
|---|---------------|----------------|------------|
| 1 | Post-scan signal validation (price drift) | PENDING | **IMPLEMENTED** (code) |
| 2 | Raise min_score from 6 to 7 | PENDING | READY (config change only) |
| 3 | Per-position SL / relax batch close | PENDING | PARTIALLY READY (trailing exists; config change for drawdown threshold) |
| 4 | Fix AI Manager execution pipeline | PENDING | **IMPLEMENTED** (code) |
| 5 | Symbol blacklist (adaptive) | PENDING | **IMPLEMENTED** (code) |
| 6 | Reduce max_trades from 5 to 3 | PENDING | READY (config change only) |
| 7 | Time-based signal weighting | PENDING | **IMPLEMENTED** (code) |
| 8 | Trailing stop after +2% profit | PENDING | ALREADY EXISTS (feature pre-dates report) |
| 9 | Lower EQUITY_RISE_PCT from 14% to 8% | PENDING | READY (config change only) |
| 10 | AI Manager prevent-new-trades | PENDING | ALREADY EXISTS (PAUSE_TRADING action) |
| New | Sector concentration limit | — | **IMPLEMENTED** (code) |
| New | Dynamic sector classification | — | **IMPLEMENTED** (code) |
| New | Orphan position alerting | — | **IMPLEMENTED** (code) |

---

<!-- NEXT RESEARCH ENTRY GOES BELOW THIS LINE -->

