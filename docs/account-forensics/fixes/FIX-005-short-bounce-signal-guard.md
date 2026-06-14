# FIX-005 — Structured signal shorts oversold/bounce-prone coins

**Status:** fixed (2026-06-14) — deterministic filter + tight-geometry preset shipped end-to-end (backtest + live), backtest-validated; live gate interval bug fixed. Not yet prod-verified.
**Severity:** High (signal quality)
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (signal generation — all accounts that trade these signals)

## Symptom
6 of Unni's 7 trades were shorts, several into coins that had already crashed and were bouncing.
The worst — ESPORTS — was shorted at 0.06654 after a −72%/24h crash, sitting on the 0.060
support with RSI ~33, and it immediately ripped +15.7% into the stop. The signal shorted a
falling knife at the moment it reversed.

## Evidence — production-parity LLM replay
We re-ran each signal through the **exact production model** (MiniMax-M2.7-highspeed) on
point-in-time, no-look-ahead indicators. It **disagreed with 5 of 7** recorded signals, and in
every disagreement flagged **reversal/bounce risk**:

| Symbol | Prod | MiniMax replay | Rev-risk | Actual move after entry |
|--------|------|----------------|----------|-------------------------|
| ESPORTS | Short | **No Trade** | **HIGH** | +15.7% adverse |
| NOKIA | Short | No Trade | high | +0.7% |
| TSTBSC | Short | No Trade | high | +2.5% |
| B3 | Short | **Long** | low | (fell later — lucky) |
| FOLKS | Long | No Trade | medium | −4.5% |
| GWEI | Short | Short ✓ | medium | +3.0% |
| HMSTR | Short | Short ✓ | medium | −6.8% (favorable) |

ESPORTS verdict: *"Price near 0.060 support, no breakdown confirmed; RSI near 33 and bounce
possible; risk of reversal high."* The production model itself would not have opened the trade
that caused 88% of the loss.

## Root cause
The structured signal path (`tradingagents/agents/crypto_analysts.py` and the scanner's
structured-signal route) shorts on short-term EMA alignment without sufficiently weighting
mean-reversion/bounce risk on already-stretched, oversold, beaten-down coins. Counter-trend
shorts (B3 had EMA9>EMA21, RSI 60.8, +4.3%/24h) also slipped through.

## Fix (implemented) — a deterministic trade-selection filter
A full research program (`work/FIX-005/RESEARCH.md`) built an offline backtest harness over real
local signal data (no lookahead), replayed signals through the **production model**
(MiniMax-M2.7-highspeed), and scored outcomes against ground truth on two disjoint samples.

**Key research finding:** changing signal *generation* via LLM prompts **did not generalize** —
lean prompts that looked great on one sample (dir-PnL +1.195%) collapsed on held-out data
(−1.176%), and LLM calls were only ~63% reproducible. What DID generalize was a **deterministic
filter on the existing signals**, using three properties that predict outcomes consistently
across both samples:
- **score tier**: score8+ wins ~70-73% (vs score6 ~55-57%).
- **trend alignment**: shorts WITH the 1h+4h downtrend won 56% vs 39% counter-trend.
- **falling-knife veto**: shorts into a crashed (24h≤-15%) + oversold/on-support coin won 36%
  (the exact ESPORTS trap).

Combined (min_score≥6 + trend-aligned + no-falling-knife): win **60.7%→67.4%**, dir-acc
**57.6%→63.3%**, generalizing across both seeds (58→62.5% and 63.3→70.1%). Deterministic ⇒
**100% reproducible** (same signal → same decision).

Shipped as a **trade-selection filter** (not a generation change):
- `backend/services/signal_quality_filter.py` — pure, fail-open `trend_aligned`,
  `is_falling_knife_short`.
- Gates in `auto_trade_service._try_trade` emitting `counter_trend` / `falling_knife` skips
  (per-scan kline cache; fail-open on any error so a data glitch never blocks trading).
- Opt-in `AutoTradeConfig` knobs (default **off**, non-breaking): `require_trend_alignment`,
  `block_falling_knife`.
- Tests: `tests/backend/test_signal_quality_filter.py` (15) + 5 gate integration tests in
  `test_auto_trade_service_unit.py`. 47 pass.

## Pushing win-rate >75% — the TP/SL geometry lever
A follow-up search found the *filter-stacking* ceiling was ~72% (worst seed). The further
lift came from **trade geometry**, not selection. The filtered signals had the right
direction but production exits were very wide (`take_profit_pct=150`/`stop_loss_pct=100` at
leverage 7 ≈ 21% TP / 14% SL **price** move), so correct trades ran past their edge and got
chopped out. Re-simulating the same filtered signals with a **tight, asymmetric geometry**
(TP ≈ 0.8% / SL ≈ 1.8% price move) won **77.1% / 81.6% on both held-out seeds** (96 & 87
trades), **net-profitable after fees** (+13% / +19% total). Helper:
`signal_quality_filter.recommended_exit_pcts(leverage)` → production `take_profit_pct` /
`stop_loss_pct` (e.g. lev 7 → TP 5.6% / SL 12.6%). Applied per-account via scan config (no
behavior-code change); roll out carefully (paper/subset first). Full numbers + per-leverage
table in `work/FIX-005/RESEARCH.md`.

> Note: the original "fix approach" proposed editing the LLM prompt; the research showed that
> over-abstains and doesn't generalize, so we filter deterministically instead. The prompt-side
> upside (richer features into the multi-agent debate) remains a future option — see RESEARCH.md.

## Productization & hardening (2026-06-14) — "Best Winrate" preset + live bug fix
The research filter was turned into a usable, end-to-end product. Full detail with file
citations and tests: **[`work/FIX-005/CHANGELOG.md`](work/FIX-005/CHANGELOG.md)**. Summary:

- **"Best Winrate" preset** bundling the gates + tight geometry, applied in one click:
  a "Best Winrate Config" button in the backtest form and an "Apply Best Winrate" button on
  each scanner auto-trade card (Scheduled + Market Scan). Frontend: `referencePresets.ts`
  (`BEST_WINRATE_CONFIG`), `configSchema.ts`, `BacktestConfigForm.tsx`, `AutoTradeSection.tsx`,
  `applyReferencePreset.ts`, `FiltersAdvancedTab.tsx`, `tabMeta.ts`, `client.ts`.
- **Backtest engine now runs the gates** (`backtest_engine._apply_filter_chain` step 18 +
  `_resample_klines`), reusing the same `signal_quality_filter` functions — so a backtest
  finally reflects the gates' effect (previously they existed only in live).
- **🔴 Live correctness bug fixed:** the live gate (`auto_trade_service._sq_klines`) used
  Bybit-style interval strings `"60"`/`"240"`/`"5"` where the fetcher expects
  `"1h"`/`"4h"`/`"5m"` → it fetched nothing and **fail-opened, so the gates were never firing
  in production**. Fixed the strings + added `"5m"` to `scanner_service._fetch`'s window map.
- **5 review-hardening fixes** (all with regression tests): backtest pre-window kline buffer
  so the gate isn't a silent no-op at window start (parity); `try/except → allow` + tolerant
  accessors so the backtest fails-open like live instead of crashing; preset gates no longer
  "stick ON" when switching presets; clock-aligned resample; exhaustive `getReferencePreset`.
- **Status:** implemented + fully tested locally (470 FE + 404 BE relevant tests pass, `tsc`
  clean). **Not yet verified in prod.** Opt-in + default-off → no behavior change until applied.
- **Operational caveat:** the live trend gate reads 1h/4h from a cache with no fetch-on-miss;
  it fail-opens for symbols whose 1h/4h candles aren't cached. See CHANGELOG §6 for the
  follow-up candidate (a live 1h/4h warm path).

## Verification — done
- ✅ Backtest: combined filter lifts win-rate +6.7pts and dir-acc +5.7pts, on BOTH held-out samples.
- ✅ Production filter functions reproduce the lift end-to-end (58→62.5%, 63.3→70.1%).
- ✅ Deterministic ⇒ reproducible by construction. Unit + integration tests pass; gates fail-open.

## Cross-references
- Full research record: `work/FIX-005/RESEARCH.md`
- Productization + hardening changelog: `work/FIX-005/CHANGELOG.md`
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §4 (LLM signal replay)
- Code (filter): `backend/services/signal_quality_filter.py`
- Code (live gate): `auto_trade_service._try_trade` / `_sq_klines`; `scanner_service._fetch`
- Code (backtest gate): `backtest_engine._apply_filter_chain` + `_resample_klines`;
  `backtest_service._signal_quality_lookback`
- Preset surface: `frontend/.../referencePresets.ts` (`BEST_WINRATE_CONFIG`),
  `BacktestConfigForm.tsx`, `scanner/AutoTradeSection.tsx`, `scanner/applyReferencePreset.ts`
