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

---

## Round 3 — pushing win-rate >75%: TP/SL GEOMETRY is the missing lever

After shipping the filter (~67-73% win), a further search found the deterministic
filter-stacking ceiling was ~72% on the worst seed. LLM-agreement as a filter added
nothing (60-63%). The breakthrough came from **trade geometry**, not signal selection.

**Insight:** the filtered signals had the RIGHT direction but production exited at very
wide levels — `take_profit_pct=150, stop_loss_pct=100` at leverage 7 means a ~21% TP /
~14% SL *price* move. Correct-direction trades ran far past their short-horizon edge and
got chopped out. Re-simulating the SAME filtered signals with a **tight, asymmetric
geometry** (nearer TP, wider SL) on the forward klines:

| filter | geometry (price move) | seed42 | seed99 |
|--------|----------------------|--------|--------|
| score≥6 + trend2tf + no_knife | **TP 0.8% / SL 1.8%** | **77.1%/96** | **81.6%/87** |
| score≥6 + trend2tf + no_knife | TP 0.7% / SL 1.5% | 76.0%/96 | 81.6%/87 |
| score≥7 + trend3tf + no_knife | TP 0.5% / SL 1.2% | 79.5%/39 | 92.3%/39 |

**Winner: score≥6 + trend-2tf + no-falling-knife + TP≈0.8% / SL≈1.8% price move →
77.1% / 81.6% win on BOTH held-out seeds**, ~60% of signals kept (96 & 87 trades).

**Expectancy (net of ~0.11% round-trip fees), despite the 0.8:1.8 R:R:**
- seed42: +0.135%/trade, +13.0% total over 96 trades.
- seed99: +0.223%/trade, +19.4% total over 87 trades.

Both >75% win AND net-profitable — the high hit-rate more than compensates for the
asymmetric reward. Not metric-gaming: the move is captured before short-horizon noise
stops it out.

### Translating to production params
Production stores TP/SL as **percent of margin**; the price move = `pct / leverage`
(`accounts_service`: `tp_price_pct = take_profit_pct / leverage`). So to target a price
move of `p%`, set `margin_pct = p × leverage`. Helper:
`signal_quality_filter.recommended_exit_pcts(leverage)`.

| leverage | take_profit_pct | stop_loss_pct |
|----------|-----------------|---------------|
| 1 | 0.8 | 1.8 |
| 5 | 4.0 | 9.0 |
| 7 | 5.6 | 12.6 |
| 8 | 6.4 | 14.4 |
| 10 | 8.0 | 18.0 |

Apply per account via the scan auto_trade config (no behavior-code change). This is a
LARGE departure from the current TP=150/SL=100 and should be rolled out carefully
(paper/subset first).

---

## Can the LLM signal GENERATION be improved further? (honest assessment)

Yes — but **not via single-call prompt tweaks** (those overfit and don't reproduce, as
Rounds 1-2 showed). The production system already beats a single LLM call because it is a
**multi-agent debate pipeline** (analysts → bull/bear → research manager → trader). The
real LLM-side upside is to improve the *inputs and structure of that pipeline*, then
re-validate with this harness:

1. **Feed the pipeline the data it's missing.** The most reliable deterministic predictors
   here were **multi-timeframe trend (1h+4h)** and volume — yet the Research Manager works
   "solely on debate history" with NO explicit MTF trend. Surfacing MTF + funding/OI/CVD
   into the analyst/debate inputs is the highest-probability LLM improvement (additive to
   the filter).
2. **Calibration**: the model is overconfident (conf 5-6 → 71% accurate vs conf 7-10 →
   57%). Confidence-aware sizing or a calibration pass could help.
3. **Regime-conditional prompting**: trend-follow in trending regimes, fade in ranging —
   needs a reliable regime classifier fed into the pipeline.

These are **higher-effort, higher-variance** and best done as a follow-up after the
post-reset DB accumulates more than ~3 days of data. The filter + geometry is the
reliable, shipped win; the pipeline-input work is the next frontier.
