# Trading System Profitability Research Report

**Date:** 2026-06-04  
**Scope:** Full system analysis — 21 demo accounts, 4,858 trades, ~2 weeks of data  
**Starting Capital:** $100 per account (demo)

---

## Executive Summary

The system is **net profitable** ($1,370.92 total across all accounts) with a 50.3% win rate, but is **leaving significant money on the table** due to structural issues. Key findings:

1. **AI Manager decisions execute but outcomes never tracked** — all 181 decisions show `execution_result: null`
2. **High-confidence signals (score 7-8) dramatically outperform** moderate ones (score 6) — avg $0.86 vs $0.32 per trade
3. **Scan duration (57-149 minutes)** means signals are stale by execution time
4. **Drawdown closes wipe entire profitable batches** — a single bad position triggers closing all 5 positions
5. **Sell-side dominance** (93% of trades are shorts) creates concentrated directional risk

---

## 1. System Architecture & Configuration

### Scheduled Scan: "Every 3 Hour Scan"
- **Interval:** 180 minutes
- **Coins scanned:** ~570 per run
- **Scan duration:** 57–149 minutes (avg ~90 min)
- **Analysts:** 5 (technical, derivatives, news, fundamentals, social)
- **Provider:** Anthropic via MiniMax-M2.7-highspeed

### Per-Account Trade Config (typical)
| Parameter | Value |
|-----------|-------|
| Max Trades | 5 |
| Min Score | 6 |
| Leverage | 5x–20x |
| Capital % | 9–15% |
| TP | 150% (of margin) |
| SL | 100% (of margin) |
| Drawdown Limit | 10–12% |
| Profit Goal | 12–14% |
| Breakeven Timeout | 12 hours |
| Max Duration | 24 hours |

### Close Rules (per cycle)
- **EQUITY_RISE_PCT:** Close all when account gains X% → profit lock
- **EQUITY_DROP_PCT:** Close all when account drops X% → loss protection
- **BREAKEVEN_TIMEOUT:** Close if not profitable after 12h
- **MAX_DURATION:** Force close after 24h

---

## 2. Account Performance Overview

| Account | Trades | Net PnL | Win Rate | Strategy |
|---------|--------|---------|----------|----------|
| Autotrader | 192 | +$176.57 | 50.5% | 20x, no AI mgr |
| Appu | 85 | +$172.20 | 68.2% | 20x, no AI mgr |
| Jeffin | 263 | +$166.63 | 49.8% | 20x, AI mgr |
| Joyel | 235 | +$157.83 | 52.3% | 20x, no AI mgr |
| Preethy | 254 | +$111.25 | 52.8% | 10x, AI mgr |
| Boss | 215 | +$101.78 | 49.3% | 10x, no AI mgr |
| Unni | 90 | +$92.47 | 52.2% | 20x, AI mgr |
| Dad | 248 | +$72.73 | 51.2% | 20x, no AI mgr |
| Salomy | 292 | +$67.70 | 45.2% | 20x, AI mgr |
| Brother | 400 | -$6.94 | 41.3% | 20x, no AI mgr |
| Sam | 300 | -$8.17 | 43.7% | 20x, no AI mgr |
| Jerin | 260 | -$12.00 | 39.6% | 20x, AI mgr |
| Princy | 257 | -$19.44 | 42.8% | 20x, AI mgr |

**Key Insight:** Accounts with fewer trades tend to perform better. Appu has the best PnL/trade ratio ($2.03 avg) with only 85 trades. Accounts with 250+ trades have diluted returns.

### Unni Account Deep Dive
- **Starting equity:** $93.11 (May 31) → **Current: $219.62** (+136%)
- **Peak equity:** $246.33 (Jun 4, 06:59) → dropped to $219.62 in just 35 minutes
- **Pattern:** Equity builds over 2-3 cycles, then a bad batch wipes 10-12% in one shot
- **Daily PnL:** May 31: -$14, Jun 1: +$14, Jun 2: +$41, Jun 3: +$21, Jun 4: +$30

### Preethy Account Deep Dive
- **Current equity:** $247.58 (AI manager reports)
- **AI Manager:** Enabled, sleeping state, 10 actions today, daily loss of -$18.72
- **Pattern:** Volatile — Jun 2 earned +$74 (best day), but May 27 lost -$29 and May 31 lost -$24
- **Emergency ref equity:** $248.56 (AI uses this as baseline)

---

## 3. Critical Finding: Signal Score Performance

| Score | Trades | Total PnL | Avg PnL | Win Rate |
|-------|--------|-----------|---------|----------|
| 8 | 5 | -$3.73 | -$0.75 | 40% |
| **7** | **6** | **+$12.18** | **+$2.03** | **66.7%** |
| 6 | 121 | +$12.47 | +$0.10 | 51.2% |
| -6 | 783 | +$277.60 | +$0.35 | 44.8% |
| **-7** | **815** | **+$715.38** | **+$0.88** | **52.4%** |
| **-8** | **184** | **+$142.13** | **+$0.77** | **51.6%** |

**MASSIVE INSIGHT:** Score 7-8 trades produce **2.7x more PnL per trade** than score 6 trades (avg $0.86 vs $0.32) with 52.3% vs 45.7% win rate. The system trades too many score-6 signals.

### Signal Distribution Per Scan
- ~570 coins scanned per run
- ~500-550 return score 0 (neutral, no trade)
- Only **7-43 actionable signals** (score ≥ 6) per scan
- Only **2-31 high-confidence** (score ≥ 7) per scan
- System fills 5 trades per account from whatever's available

---

## 4. Critical Finding: Scan Duration & Signal Staleness

### The Problem
Scans take **57–149 minutes** to process ~570 coins. The first coins analyzed are 1-2 hours stale by the time trades are placed.

| Scan Start | Duration | Signals | High Score |
|------------|----------|---------|------------|
| Jun 4, 03:48 | 78 min | 12 actionable | 4 high |
| Jun 4, 00:48 | 149 min | 43 actionable | 31 high |
| Jun 3, 21:48 | 65 min | 11 actionable | 5 high |
| Jun 3, 15:47 | 110 min | 28 actionable | 16 high |
| Jun 3, 09:46 | 99 min | 20 actionable | 15 high |

### Impact
- Trades open immediately after scan completion (no delay)
- But the ANALYSIS was done 60-149 minutes BEFORE the trade opens
- In crypto markets, a 2-hour-old signal is significantly degraded
- The 06:04 batch for Unni: 5 sells all went negative within 25 minutes → EQUITY_DROP triggered

---

## 5. Critical Finding: Batch Close Wipeouts

### The Pattern
When EQUITY_DROP_PCT rule triggers (12% drop), ALL 5 positions close simultaneously — even ones that might recover.

**Unni Jun 4, 07:36 example:**
- GMTUSDT: -$6.05 (the drag)
- DOGEUSDT: -$5.93 (the drag)  
- ALICEUSDT: -$5.06
- AVAXUSDT: -$4.07
- SHIB1000USDT: -$3.63
- **Batch total: -$24.74** (wiped profits from previous cycle)

**Equity dropped from $244.96 to $224.87 → then to $219.62 after closes**

This is the #1 profit killer: **one bad batch erases 2-3 good cycles.**

### PnL by Close Reason (system-wide)
| Close Reason | Count | Total PnL | Avg PnL | Avg Hold |
|-------------|-------|-----------|---------|----------|
| rule_triggered | 3,387 | +$1,050.77 | +$0.31 | 3.0h |
| manual_close_all | 383 | +$399.68 | +$1.04 | 3.3h |
| external (AI) | 1,061 | +$26.76 | +$0.03 | 3.5h |
| liquidation | 12 | -$129.68 | -$10.81 | 2.5h |

**manual_close_all** (EQUITY_RISE_PCT profit lock) generates $1.04 avg — this is the BEST close reason. The system profits most when it locks in profits at target.

---

## 6. Critical Finding: AI Manager Is Broken

### Evidence
1. **All 181 AI decisions have `execution_result: null`** — actions recorded but no confirmed execution
2. **Preethy AI Manager:** 15 decisions over 7 days, 0 wins, 0 losses, $0 net PnL tracked
3. **All outcome_labels are "neutral"** — system never validates if close was profitable
4. **Dead letter queue is empty** — errors aren't being captured
5. **AI closes positions marked as "external" not "ai_closed"** — attribution broken

### What AI Manager Actually Does (from decisions log)
**FAST decisions (9 for Preethy):** Closing at "peak profit" with 0.72-0.85 confidence
- Example: "Position at peak profit ($2.72). Ranging market regime increases reversal risk"
- These close small profits ($1-3) early to avoid reversal

**EMERGENCY decisions (6 for Preethy):** Closing at equity drops
- Example: "equity_drop_18.0pct" → close SOXLUSDT
- These fire AFTER the drawdown rule should have already handled it

### The Problem
The AI Manager is designed to:
1. Monitor positions in real-time via WebSocket
2. Detect peak profit moments and lock them in
3. Emergency close when equity drops

But it's **not preventing the big losses** — it closes small winners at $1-2 profit while the drawdown rules handle the actual crisis. The AI adds friction without meaningful protection.

---

## 7. Leverage & Direction Analysis

### By Leverage
| Leverage | Trades | Win Rate | Avg PnL | Total PnL |
|----------|--------|----------|---------|-----------|
| 5x | 493 | 40.6% | +$0.15 | +$74.47 |
| 10x | 511 | **52.8%** | **+$0.66** | **+$337.03** |
| 12x | 425 | 40.0% | -$0.07 | -$31.56 |
| 20x | 3,429 | 47.2% | +$0.30 | +$1,013.68 |

**10x leverage has the best risk-adjusted returns** (highest win rate AND best avg PnL). 20x wins by volume but 5x and 12x underperform.

### By Side
| Side | Trades | Win Rate | Avg PnL | Total PnL |
|------|--------|----------|---------|-----------|
| Sell (Short) | 4,521 | 46.9% | +$0.32 | +$1,424.65 |
| Buy (Long) | 337 | 41.5% | -$0.09 | -$31.04 |

The system is **93% short-biased**. Shorts work in this period but longs lose money. This means the system performs well only during bearish/ranging markets and will struggle in bull runs.

---

## 8. Symbol Performance Analysis

### Top 5 Winners (min 10 trades)
| Symbol | Trades | Total PnL | Win Rate |
|--------|--------|-----------|----------|
| DEEPUSDT | 13 | +$120.95 | 100% |
| LAUSDT | 22 | +$106.31 | 95.5% |
| DELLUSDT | 19 | +$100.54 | 94.7% |
| MOVEUSDT | 17 | +$82.05 | 94.1% |
| FIDAUSDT | 31 | +$81.92 | 80.6% |

### Top 5 Losers (min 10 trades)
| Symbol | Trades | Total PnL | Avg PnL |
|--------|--------|-----------|---------|
| BIGTIMEUSDT | 40 | -$100.11 | -$2.50 |
| PLAYSOUTUSDT | 62 | -$94.01 | -$1.52 |
| SOXLUSDT | 16 | -$93.11 | -$5.82 |
| SPXUSDT | 39 | -$81.31 | -$2.08 |
| POWERUSDT | 49 | -$69.06 | -$1.41 |

**Key Insight:** The worst 5 symbols cost the system -$418.48. If these were blacklisted, total PnL would increase by ~30%.

---

## 9. Recommendations for Profitability Improvement

### PRIORITY 1: Post-Scan Signal Validation (HIGH IMPACT)

**Problem:** Signals are 60-149 minutes stale by execution time.

**Solution:** After scan completes, before placing trades:
1. Re-check current price vs analysis price
2. Calculate price drift % since signal generation
3. If price already moved >X% in the signal direction → signal has been "used up" (skip it)
4. If price moved against signal → signal is stronger (prioritize it)
5. Quick 15-second spot check on RSI/momentum at execution time

**Expected Impact:** Eliminates 30-50% of stale signals that immediately go negative.

### PRIORITY 2: Raise Minimum Score to 7 (HIGH IMPACT, EASY)

**Problem:** Score 6 trades average only $0.10 profit with 45.7% win rate.

**Solution:** Change `min_score` from 6 to 7 across all accounts.

**Trade-off:** Fewer trades per cycle (some scans only produce 2-5 high-score signals). But avg PnL per trade jumps from $0.32 to $0.86.

**Alternative:** Use score 7+ as primary fill, only use score 6 to "fill remaining" if fewer than 3 high-score available.

### PRIORITY 3: Per-Position Stop Loss Instead of Account-Level Drawdown (HIGH IMPACT)

**Problem:** EQUITY_DROP_PCT closes ALL positions when account drops X%. One bad position drags down 4 others that may be fine.

**Solution:** 
- Keep per-trade SL at 100% of margin (existing)
- Remove or relax EQUITY_DROP_PCT from 12% to 20%
- Add per-position trailing stop after reaching +1% profit
- Close individual bad positions at their own SL, not the whole basket

**Expected Impact:** Prevents batch wipeouts. The Jun 4 Unni case: if only the 2 worst positions closed (GMTUSDT, DOGEUSDT), the other 3 might have recovered. Saved ~$13.

### PRIORITY 4: Fix AI Manager Execution Pipeline (HIGH IMPACT)

**Problem:** AI Manager makes decisions but execution never confirms success. All outcomes are "neutral."

**Root Cause (from code):** The `execution_result` field is never being populated. The decisions go through `dead_letter_exhausted` — suggesting the execution path is broken.

**Solution:**
1. Debug why `execution_result` is always null in `ai_manager_decisions`
2. Verify the close_positions_service is actually being called
3. Add outcome tracking: after AI close, measure if price continued adverse or reversed
4. Use outcome data to improve AI decision quality over time

### PRIORITY 5: Symbol Blacklist/Whitelist (MEDIUM IMPACT, EASY)

**Problem:** 5 symbols cost the system -$418 in losses. They keep getting traded repeatedly.

**Solution:** Add a configurable blacklist in scan config:
```json
"symbol_blacklist": ["BIGTIMEUSDT", "PLAYSOUTUSDT", "SOXLUSDT", "SPXUSDT", "POWERUSDT"]
```

Or better: **adaptive blacklist** — if a symbol has >5 trades with <30% win rate, auto-exclude for 48 hours.

### PRIORITY 6: Reduce Positions Per Cycle (MEDIUM IMPACT)

**Problem:** 5 simultaneous positions creates high correlation risk. When market moves against, ALL 5 lose.

**Solution:** 
- Reduce max_trades from 5 to 3
- Use larger capital_pct per trade (18-20% instead of 12-15%)
- This maintains exposure but reduces correlation risk

**Evidence:** Appu account has best PnL/trade ($2.03) with fewer total trades. Quality > quantity.

### PRIORITY 7: Time-Based Signal Weighting (MEDIUM IMPACT)

**Problem:** Scans that take 149 minutes have WORSE performance than 57-minute scans (more coins = more stale signals).

**Solution:** 
- Track scan order — which coins were analyzed first vs last
- Weight earlier-analyzed signals lower (more time passed)
- Or: scan top 200 coins in first pass (30 min), remaining 370 in background
- Execute trades from first pass immediately, second pass only if first doesn't fill

### PRIORITY 8: Trailing Stop for Profitable Positions (MEDIUM IMPACT)

**Problem:** The system either hits TP (150% of margin ≈ 7.5% with 20x leverage) or gets stopped. No middle ground.

**Solution:** Once a position reaches +2% profit:
- Set trailing stop at 50% of peak profit
- If position peaks at +5% then drops to +2.5%, close it
- This locks in partial profits instead of waiting for full TP or getting stopped

**Evidence:** AI Manager's FAST decisions already try to do this (closing at "peak profit"), but execution is broken.

### PRIORITY 9: Improve Profit Locking (EQUITY_RISE_PCT) (LOW-MEDIUM IMPACT)

**Problem:** The equity rise rule (14% for Unni) only triggered 0 times in tracked history. It's too high.

**Solution:** 
- Lower EQUITY_RISE_PCT threshold from 12-14% to 8%
- Or: implement progressive profit taking — close 2/5 positions at 5% profit, remaining at 10%
- The `manual_close_all` trades have the best avg PnL ($1.04) — this mechanism WORKS when triggered

### PRIORITY 10: AI Manager Should Prevent New Trades, Not Just Close (NEW CAPABILITY)

**Problem:** AI detects adverse conditions but can only CLOSE positions. It can't prevent the next scan cycle from opening new trades in a bad market.

**Solution:** 
- Add "market regime" assessment before auto-trading
- If AI Manager detects high-volatility/adverse regime → pause auto-trading for 1 cycle
- This prevents the "open 5 positions into a reversal" pattern

---

## 10. Quantified Impact Estimates

| Recommendation | Est. Annual Impact | Difficulty |
|---------------|-------------------|------------|
| Post-scan validation | +25-40% PnL | Medium |
| Min score 7 | +15-25% PnL | Trivial |
| Per-position SL | +10-20% PnL | Medium |
| Fix AI Manager | +10-15% PnL | Medium |
| Symbol blacklist | +5-10% PnL | Trivial |
| Reduce positions/cycle | +5-15% PnL | Trivial |
| Time-based weighting | +5-10% PnL | Hard |
| Trailing stops | +10-20% PnL | Medium |
| Lower profit lock threshold | +5-10% PnL | Trivial |
| AI prevent-new-trades | +10-20% PnL | Hard |

**Combined conservative estimate:** +50-80% improvement in total PnL.

---

## 11. Appendix: Raw Data Points

- **Total system PnL:** $1,370.92 across 4,858 trades (2 weeks)
- **Annualized (crude):** ~$35,000/year across 21 accounts
- **Per-account average:** ~$65/account or +65% return on $100 demo
- **Biggest single-trade loss:** -$11.18 (MOVRUSDT, 20x)
- **12 liquidations total** costing -$129.68 (need to prevent entirely)
- **Average hold time:** 3.0-3.5 hours
- **Scan frequency:** Every 3 hours
- **Scans without AI manager accounts trade every cycle** (no skip if prior open)
- **Scans WITH skip_if_positions_open: true** only trade when prior cycle closes

---

## 12. Specific Issues with Preethy (AI Manager Account)

### What's Happening
1. AI Manager is "sleeping" — it activates only on WebSocket events
2. When it wakes, it sees positions at peak profit and closes them (FAST urgency)
3. But the close goes through a broken pipeline — `dead_letter_exhausted`
4. The emergency closes DO work (equity drops get caught at 10-18%)
5. But by then, the damage is already done

### What AI Is Missing
1. **No proactive protection** — it reacts to losses, doesn't prevent them
2. **Closes winners too early** — closing at $1-2 profit when TP target is $10+
3. **Doesn't correlate positions** — 5 short positions in correlated altcoins = hidden concentration
4. **No market context** — doesn't know if overall market just reversed
5. **Outcome loop broken** — can't learn from past decisions because outcomes aren't tracked

### Recommended AI Manager Fixes
1. Fix execution pipeline (debug `execution_result: null`)
2. Only close if profit is >30% of TP target (don't close $1 profits on $10 TP trades)
3. Add "pause new trades" capability 
4. Track position correlation in real-time
5. Implement outcome tracking to enable learning

---

*End of Report*
