# FIX-005 Research: Improving Trade-Signal Accuracy

Full research record for the signal-accuracy improvement. Companion to
`../FIX-005-short-bounce-signal-guard.md` (the original Unni finding).

**Goal:** more accurate signals AND reproducible (same input → same decision).
**Method:** offline backtest over real local signal data (no lookahead), production-parity LLM
replay (MiniMax-M2.7-highspeed), deterministic ground-truth outcome scoring, two disjoint
samples (seed 42 + held-out seed 99) to test generalization.

## Data & harness
- 89,066 local scan results (Jun 10-13); 2,550 actionable (|score|≥6); 5.43M 5m klines / 587
  symbols → 2,535 signals scorable.
- Ground truth = path-dependent TP/SL simulation over forward 5m candles + dir-accuracy (call vs
  8h fwd-return sign) + dir-PnL (mean fwd-return in called direction). Deterministic.

## Baseline
Production signals: win 56.7%, dir-acc 56.6%, dir-PnL +0.44%/trade, short bias ≈8:1.
Score IS predictive: score6=51%, score7=60%, score8+=71% win.

## What we tried

### Round 1 — rule-heavy LLM prompts → FAILED
rich-features / reversal-guard / regime-gate / bull-bear-debate / confluence-filter all drove
MiniMax to **over-abstain (79-100% No-Trade)**; when it traded, accuracy was poor (rich 38.7%).
More rules → "No Trade".

### Round 2 — lean decision-forcing prompts → did NOT generalize
final_v1 on seed42: dir-PnL +1.195% (2.7× baseline), short-bias fixed (1.8:1). On held-out
seed99: **dir-PnL −1.176%, dir-acc 50%, 91% abstain.** The train lift was noise.

### Reproducibility — LLM ensembles too unstable
5-vote ensemble @temp0.7: 63-64% identical calls across runs; trade counts 144 vs 98. A
single/small-ensemble LLM call is neither generalizable nor reproducible as a signal generator.

### The generalizable win — deterministic filters
Consistent across BOTH samples:

| Filter | Effect |
|--------|--------|
| score tier | score8+ ≈ 70-73% win on both seeds (vs score6 ≈ 55-57%) |
| trend alignment | shorts WITH 1h+4h downtrend 56%/+0.46%; counter-trend 39%/−0.60% |
| falling-knife veto | shorts into crashed+oversold/support 36%/−1.60% (the ESPORTS trap) |

Combined (min_score≥6 + trend-aligned + no-falling-knife): **win 60.7%→67.4%, dir-acc
57.6%→63.3%**, keep 59%. Generalizes (seed42 58→62.5%, seed99 63.3→70.1%). Deterministic →
100% reproducible.

## What shipped
- `backend/services/signal_quality_filter.py` — pure fail-open functions `trend_aligned`,
  `is_falling_knife_short`.
- Gates in `auto_trade_service._try_trade` (`counter_trend`, `falling_knife` skip reasons),
  per-scan kline cache, fail-open.
- Opt-in `AutoTradeConfig` knobs (default off): `require_trend_alignment`, `block_falling_knife`.
- 17 tests (12 unit + 5 gate integration).

## Lessons
1. Prompt-tuning one LLM call overfits — always hold out a sample.
2. LLM calls aren't reproducible enough for "same result on re-run"; deterministic rules are.
3. The system's own score is the most reliable signal — act on the high-conviction tier.
4. The short bias is real: ~35% of shorts were counter-trend and lost money.

## Not-yet-shipped upside
- Position-size weighting by score tier.
- Richer features (funding/OI/CVD) into the production multi-agent debate (which already beats a
  single call) rather than replacing it.
- Re-run the harness as the post-reset DB accumulates more data.
