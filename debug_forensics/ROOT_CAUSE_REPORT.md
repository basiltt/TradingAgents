# Root-Cause Forensic Report — "Unni - Demo" Loss ($100 → $79.59)

**Account:** Unni - Demo (`3aca7442-2bd0-44c6-b4ef-bc46a9593f35`)
**Window:** 2026-06-13 17:06 UTC (funded ~$100.9) → 2026-06-14 04:13 UTC (equity $79.59)
**Net result:** **−$21.3 real equity loss (−21.1%)**
**Investigation type:** Read-only production forensics + production-parity LLM replay (MiniMax-M2.7-highspeed)
**Data sources:** prod DB (`157.173.124.192`), Bybit public klines, prod auto-trade & AI-manager code paths

---

## TL;DR — Executive Summary

The loss was **NOT** caused by the account name starting with "U", and **NOT** by a
bad scan, a broken signal pipeline, or wrong account config. The scan cycle ran
correctly (581/581 symbols analyzed, valid structured signals) and Unni's config was
applied exactly as specified.

**~$18.6 of the $21.3 loss came from a SINGLE position — a SHORT on ESPORTSUSDT** that
was placed into a violent reversal and then **orphaned by the exit machinery**: it was
ineligible for the AI manager's normal close path, missed by the AI manager's emergency
close, and finally force-closed by the position reconciler — which recorded its realized
PnL as **$0** even though the equity loss was real.

Three compounding failures, in order of impact:

| # | Failure | Layer | $ impact |
|---|---------|-------|----------|
| **1** | ESPORTS short left open through a +12.3% adverse move to its stop-loss | AI manager exit logic | **~−$18.6** |
| **2** | Realized loss booked as `net_pnl=$0` (`close_reason=external`) | Position reconciler | $0 P&L but **corrupts all reporting** |
| **3** | 6 small scanner trades, net | Signal/market | **−$1.64** |

The "name starts with U" hypothesis was **explicitly tested and refuted** (Section 4).

---

## 1. The Loss Anatomy — Where the $21 Went

Unni opened **7 scanner trades** across two auto-trade cycles. The trade ledger only
accounts for **−$1.64**, but real equity fell **−$21.3**. The gap is the ESPORTS short.

### Cycle 1 (scan `fe93f1a8`, run-now @ 19:03 UTC) — 3 trades, all shorts
| Symbol | Dir | Entry | Exit | net_pnl | Close path |
|--------|-----|-------|------|---------|-----------|
| GWEIUSDT | Short | 0.16812 | 0.16953 | **−1.48** | rule_triggered (SL) |
| NOKIAUSDT | Short | 14.807 | 14.905 | **−1.06** | rule_triggered (SL) |
| HMSTRUSDT | Short | 0.0001758 | 0.0001753 | **+0.36** | rule_triggered |

### Cycle 2 (scan `a9907e9a`, scheduled @ 00:32 UTC) — 4 trades
| Symbol | Dir | Entry | Exit | net_pnl | Close path |
|--------|-----|-------|------|---------|-----------|
| **ESPORTSUSDT** | **Short** | **0.06654** | **~0.0747 (SL)** | **$0.00 (BUG — real ≈ −18.6)** | **external (reconciler)** |
| B3USDT | Short | 0.0006056 | 0.0005918 | **+3.34** | rule_triggered |
| TSTBSCUSDT | Short | 0.015821 | 0.015669 | **+1.37** | rule_triggered |
| FOLKSUSDT | Long | 1.8725 | 1.823 | **−4.17** | rule_triggered |

### Equity trajectory (high_freq_snapshots) — the proof
```
00:32  eq=98.47  pos=0   (cycle 2 about to open)
01:34  eq=92.89  pos=4   (4 positions open)
02:25  eq=94.34  pos=4 → B3 closes
02:58  eq=84.05  pos=3 → TSTBSC+FOLKS close (emergency); ESPORTS LEFT OPEN
03:10  eq=83.75  pos=1   ← ESPORTS alone, upnl −15.0
03:15  eq=79.59  pos=0   ← ESPORTS hit stop-loss; equity crystallized
04:13  ——————          ← reconciler finally marks ESPORTS closed, net_pnl=$0
```
Between 02:58 and 03:15 the lone ESPORTS short bled the account from ~$94 to $79.59.

---

## 2. Scan Cycle — Did the system scan and select correctly? YES.

Both scans that fed Unni were **complete and healthy**:

| Scan | Trigger | Symbols | Completed | Failed | Signal dist (actionable / high-conf) |
|------|---------|---------|-----------|--------|--------------------------------------|
| `fe93f1a8` | run_now | 581 | 581 | 0 | 6 / 4 |
| `a9907e9a` | scheduled | 581 | 581 | 0 | 14 / 8 |

- **All 581 symbols analyzed both times** — no truncation, no partial scan.
- Every signal Unni traded was a **structured, schema-valid** signal (`signal_source=structured`)
  with confidence "high" and `|score|` of 7–8 (the actionable tier).
- Unni's selection respected its config exactly: `min_score=7`, `max_trades=4`,
  `capital_pct=22`, `leverage=7`, `execution_mode=batch`, `confidence_filter=moderate`.
  In cycle 2 it correctly took the top-4 highest-|score| signals.

**The selection used all available data and applied the configured gates correctly.**
There is no scan-side or selection-side defect. (One *signal-quality* nuance — counter-
trend shorts — is covered in Section 5, but that is signal logic, not selection logic.)

### Config confirmed from prod (NOT assumed)
Unni is **Cohort B**: `leverage=7, max_trades=4, TP=150%, SL=100%,
max_drawdown_pct=100 (protection OFF), smart_drawdown_close=false, target_goal=12%,
ai_manager_enabled=TRUE, emergency_close=TRUE, max_price_drift=6%, max_signal_age=150min`.
This is the intended configuration — applied correctly.

---

## 3. The Root Cause — How ESPORTS Was Orphaned (AI Manager Forensics)

The AI manager (`ai_manager_enabled=true`) took **5 decisions**. The first four were
reasonable single-position closes. The fifth — an EMERGENCY — is where it broke.

| # | Time | Type | Action | Symbol | Result |
|---|------|------|--------|--------|--------|
| 1 | 20:05 | standard/FAST | FULL_CLOSE | HMSTRUSDT | +0.80 (profit-preserve) |
| 2 | 22:09 | standard/FAST | FULL_CLOSE | GWEIUSDT | −0.60 (close losing short) |
| 3 | 00:46 | standard/FAST | FULL_CLOSE | NOKIAUSDT | −1.04 (RSI 90, close) |
| 4 | 02:25 | standard/FAST | FULL_CLOSE | B3USDT | −1.56 (trend reversal) |
| 5 | **02:58:05** | **emergency** | **EMERGENCY_CLOSE** | **TSTBSC,FOLKS** | **ESPORTS MISSING** |

Decisions 1–4 are individually defensible — each reasons "short fighting a confirmed
uptrend, close to preserve capital." But notice: **ESPORTS was never the subject of any
standard decision**, and the emergency closed everything *except* ESPORTS.

### Why the standard path NEVER closed ESPORTS — the 3% loss cap
`ai_manager_task.py:1001` enforces `max_single_decision_loss_pct = 3.0`:
```python
if not _is_urgent and self._config.max_single_decision_loss_pct:
    loss_pct = abs(upnl) / equity * 100
    if loss_pct > self._config.max_single_decision_loss_pct:
        return   # <-- SKIP: refuse to close, "loss too big for one decision"
```
ESPORTS' unrealized loss reached **5%–15% of equity**. Every time the standard evaluator
looked at it, `loss_pct > 3%` → it **returned without closing**. The gate intended to
prevent the AI from realizing a large loss on a single call instead **guaranteed the
largest loser could only ever grow** — the standard path was structurally incapable of
exiting ESPORTS.

### Why the EMERGENCY path EXCLUDED ESPORTS — a WS buffer race
At 02:58:05 the equity-drop emergency fired (`equity_drop_12.6pct`). The code
(`ai_manager_task.py:1555`) is supposed to "close ALL losing positions":
```python
if trigger_reason.startswith("equity_drop"):
    for pos in positions:           # <-- positions = self._ws_buffer["positions"]
        if upnl < 0: close_symbols.append(symbol)
```
But the recorded `state_snapshot` for decision #5 lists **`symbols: [TSTBSCUSDT,
FOLKSUSDT]` only**. At that instant, TSTBSC and FOLKS were *simultaneously* closing on
their own per-trade stop rules (both `closed_at = 02:58:05`). The emergency evaluated a
WS positions buffer that — mid-cascade — **did not contain the ESPORTS frame**. The code
comment at line 1609 even admits the hazard: *"WS events may remove positions from buffer
during await."* ESPORTS fell through the gap.

### Why it was never retried — cooldown + circuit breaker lockout
After the emergency, `ai_manager_state` shows:
- `emergency_cooldown_until = 02:58:35` → 30s suppression of equity-drop re-trigger
- `emergency_ref_equity` cleared → re-initializes from the *next* (post-close, lower)
  wallet update, so the new reference equity becomes ~$84 and the drop "resets"
- `circuit_breaker_active = true, circuit_breaker_count = 3` → the LLM eval path was
  tripped

With the standard path blocked (3% cap), the emergency reference reset, and the breaker
tripped, **nothing re-evaluated ESPORTS**. It rode its short from 0.06654 up to its
+12.3% stop-loss (0.07474) and closed on the exchange ~03:11–03:15. **Lone-position loss:
~$18.6.**

---

## 3b. Second Defect — The Loss Was Booked as $0 (Data Integrity)

ESPORTS was closed on the exchange at ~03:15, but the DB trade row stayed `status=open`
(`filled_qty=0`) until **04:13:56**, when the **position reconciler** finally force-closed
it as stale:
```
close_reason = external,  exit_price = 0,  realized_pnl = 0,  net_pnl = 0,  fees = 0
```
The reconciler (`position_reconciler.py`) detects "exchange has no position but DB says
open" and marks the trade closed — but on this path it writes **zeroes for PnL** rather
than reconstructing the realized loss from the fill/exit. So:

- **Real equity loss:** −$21.3 (the wallet truly lost the money)
- **Trade-ledger sum:** −$1.64 (ESPORTS contributes **$0**)
- **Discrepancy: ~$18.6 of real losses are INVISIBLE to all trade-based reporting**

This is not unique to Unni. The **"Brother - Demo"** account hit the identical bug on the
*same* ESPORTS short (`close_reason=external, net_pnl=0.00`). The other 5 accounts that
shorted ESPORTS closed via the per-trade stop rule (`rule_triggered`) and **correctly**
booked −$2 to −$8. **Any position the reconciler force-closes has its loss zeroed** →
`/profitability-research` and every PnL dashboard systematically under-count losses.

> ⚠️ This means historical profitability numbers are **optimistically biased** by however
> many positions exited via the reconciler's `external` path.

---

## 4. LLM Signal Simulation (Production Parity — MiniMax-M2.7-highspeed)

I replayed each of the 7 signals through the **exact production model**
(`MiniMax-M2.7-highspeed` via `api.minimax.io/anthropic`), feeding it the **point-in-time
indicators reconstructed with NO look-ahead** (klines strictly up to each signal's analysis
timestamp, from Bybit). The model was given the system's own Short/Long/No-Trade rubric.

| Symbol | Prod | MiniMax replay | Rev-risk | Agree? | Actual move after entry | Outcome |
|--------|------|----------------|----------|--------|-------------------------|---------|
| GWEIUSDT | Short | **Short** (7) | medium | ✅ | +3.0% adverse | −1.48 |
| NOKIAUSDT | Short | **No Trade** (4) | **high** | ❌ | +0.7% adverse | −1.06 |
| HMSTRUSDT | Short | **Short** (7) | medium | ✅ | −6.8% favorable | +0.36 |
| **ESPORTSUSDT** | **Short** | **No Trade** (5) | **HIGH** | ❌ | **+15.7% adverse** | **≈ −18.6** |
| B3USDT | Short | **Long** (7) | low | ❌ | (fell later) | +3.34 (lucky) |
| TSTBSCUSDT | Short | **No Trade** (5) | **high** | ❌ | +2.5% adverse | +1.37 (lucky) |
| FOLKSUSDT | Long | **No Trade** (5) | medium | ❌ | −4.5% adverse | −4.17 |

**Agreement: only 2 of 7.** The production MiniMax model, re-run on the same data,
**disagreed with 5 of its own recorded signals** — and in every disagreement it flagged
**reversal/bounce risk** that the recorded signal ignored.

### The ESPORTS verdict — the decisive finding
> **MiniMax replay: "No Trade", confidence 5, reversal_risk = HIGH.**
> *"Price near 0.060 support, no breakdown confirmed; EMA9<EMA21 bearish but RSI near 33
> and bounce possible; risk of reversal high."*

Given the identical point-in-time data, **the production model would NOT have opened the
ESPORTS short that caused 88% of the loss.** At 00:38 ESPORTS had already crashed −72%
in 24h and was bottoming at the 0.060 support (low 0.06001 printed minutes earlier, RSI
~33). The recorded signal shorted a falling knife at the moment it reversed; price then
ripped +15.7% into the stop.

### Why the divergence? (signal-quality contributor)
This is a known failure mode: **the structured signal path shorts oversold, beaten-down
coins on short-term EMA alignment without weighting mean-reversion/bounce risk.** 6 of
Unni's 7 trades were shorts; the model on replay wanted "No Trade" on the most stretched
ones. Several recorded shorts (B3, TSTBSC) only profited because price later fell — they
were *not* well-founded at entry (the model called them Long / No-Trade). This is a
**signal-robustness issue**, separate from (but compounding) the exit-machinery root cause.

> Caveat: LLMs are non-deterministic and the replay used a distilled single-prompt rubric
> rather than the full multi-agent debate graph, so exact scores will vary run-to-run. The
> *direction* of the finding is robust: independent re-evaluation repeatedly flagged the
> ESPORTS short as high reversal risk / No-Trade.

---

## 5. The "Name Starts With U" Hypothesis — TESTED & REFUTED

**The claim:** because the account is named "Unni", it gets low priority and worse trades.

**What is true:** account processing order IS alphabetical. `auto_trade_configs` is stored
as an ordered array sorted by label, and the batch executor iterates accounts in that
order. **Unni is position 20 of 21** (only "Wife" is later). Unni's trades are placed
~520s after the first account (Anju) on each shared symbol.

**Why it does NOT cause the loss — three independent disproofs:**

1. **Late placement did not worsen Unni's fills.** In batch mode the `traded` set is keyed
   by `(account_id, symbol)`, so accounts never contend for the same symbol — each places
   its own order. On the shared symbols, Unni's short fills were frequently **equal or
   better** than early accounts (e.g. GWEI: Unni filled 0.16812 vs Anju 0.16811, and far
   better than mid-list accounts that filled 0.1697; NOKIA: all 21 filled identical
   14.807). A later short fill in a *rising* market is a *higher* (better) entry.

2. **Alphabetical rank does not predict performance.** Across all 21 accounts since the
   reset, Pearson r(alpha-rank, equity) = **−0.28** on n=8 with settled equity — not
   significant. The two **worst** ledger performers are **Jerin (−12.40, rank 9)** and
   **Salomy (−11.34, rank 17)** — both mid-alphabet. Early-alphabet "Appu" (rank 3) is
   −8.77. The losses are scattered, not back-loaded.

3. **The actual loss mechanism is symbol- and exit-specific, not order-specific.** Unni's
   −$18.6 came entirely from the ESPORTS exit failure (Section 3). "Brother" (rank 6,
   early alphabet) hit the *same* reconciler-zeroing bug on the same symbol. Order was
   irrelevant.

> Position-20 does mean Unni is consistently **last to be evaluated** and could see
> marginally staler signals, but the measured fill impact is ~0 and uncorrelated with
> P&L. **The name is not why Unni lost money.**

---

## 6. Root-Cause Summary & Recommendations

### Causal chain (what actually happened)
```
Scanner correctly produces ESPORTS short signal (defensible-but-risky: oversold bounce)
   │  (MiniMax replay would have said No-Trade / HIGH reversal risk)
   ▼
Batch executor places ESPORTS short for Unni @ 0.06654 (config applied correctly)
   ▼
Price reverses +15% (dead-cat bounce off 0.060 support)
   ▼
AI manager standard path CANNOT close it  ── blocked by max_single_decision_loss_pct=3%
   ▼                                           (ESPORTS loss was 5–15% of equity)
02:58 EMERGENCY fires, "close ALL losers"  ── but WS buffer race omits ESPORTS;
   ▼                                           only TSTBSC+FOLKS closed
Cooldown(30s)+ref-equity reset + circuit breaker(count=3) ── no further re-trigger
   ▼
ESPORTS rides alone to +12.3% stop-loss  ── lone-position loss ≈ −$18.6
   ▼
Reconciler force-closes row @ 04:13 with net_pnl=$0  ── loss real in equity, $0 in ledger
```

### Findings ranked
| Rank | Finding | Type | Severity |
|------|---------|------|----------|
| 1 | `max_single_decision_loss_pct=3%` makes the AI manager structurally unable to close the *biggest* losers in the standard path | Logic flaw | **Critical** |
| 2 | Emergency "close all losers" reads a racy WS buffer mid-cascade → omits positions that should be closed | Race condition | **Critical** |
| 3 | Reconciler `external` close writes `net_pnl=0` instead of reconstructing realized PnL → all reporting under-counts losses | Data integrity | **High** |
| 4 | Structured signal shorts oversold/bounce-prone coins; MiniMax replay disagreed 5/7, flagging reversal risk | Signal quality | **High** |
| 5 | Post-emergency ref-equity reset + cooldown + circuit breaker can fully disarm protection while a large loser is still open | Logic gap | **High** |
| 6 | Alphabetical account order (Unni 20/21) | Cosmetic | **None** (refuted) |

### Recommended fixes (NO code changed — analysis only)
1. **Decouple the loss cap from the close decision.** `max_single_decision_loss_pct` should
   cap *position size at entry*, not *block exits*. A position already losing >3% is
   exactly the one that most needs closing — invert/remove this gate on the exit path, or
   force-route it to the emergency path.
2. **Make emergency close authoritative against the exchange, not the WS buffer.** On an
   equity-drop trigger, fetch live positions (or union the WS buffer with the DB open-trade
   set) before deciding which symbols to close, so a mid-cascade buffer can't orphan a loser.
3. **Reconciler must reconstruct realized PnL.** On an `external`/stale close, derive PnL
   from the last mark/exit fill (or exchange closed-PnL endpoint) instead of writing `0`.
   Backfill the historical `external`-closed rows so analytics are correct.
4. **Re-arm protection after an emergency while losers remain open.** Don't fully reset
   `emergency_ref_equity` to the post-close (lower) equity if open positions still carry
   large unrealized losses; keep a floor reference, and let the circuit breaker half-open
   sooner when a position exceeds a hard loss threshold.
5. **Add bounce/mean-reversion guard to short signals.** Penalize shorts on coins already
   down >X% in 24h sitting on support with RSI<35 (the exact ESPORTS setup). The
   production model itself rejects these on replay.

### Validation note
The screenshot ("$79.59 equity, −$19.98 today, 0 positions") reconciles exactly with this
analysis: equity bottomed at $79.59 when ESPORTS hit its stop, and "today" −$19.98 ≈ the
ESPORTS loss plus the small net of the other six trades. The trade ledger's −$1.64 is the
*under-counted* figure caused by finding #3.

---
*Forensic scripts: `debug_forensics/s1`–`s5` (read-only prod queries) + `s4b/s4c` (MiniMax
production-parity replay). No production data or code was modified.*
