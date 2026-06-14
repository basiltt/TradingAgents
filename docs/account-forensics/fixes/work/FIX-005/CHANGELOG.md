# FIX-005 — Productization & Hardening Changelog

This log records the work that turned the FIX-005 **research result** (a deterministic
signal-quality filter + tight TP/SL geometry) into a **usable, end-to-end product**: a
"Best Winrate" preset wired through the backtest engine, the live auto-trader, and both
scanner forms — plus a live correctness bug found along the way and five review-driven
hardening fixes.

It complements the parent ledger entry
[`../../FIX-005-short-bounce-signal-guard.md`](../../FIX-005-short-bounce-signal-guard.md)
(root cause, research, original filter) and the research record
[`RESEARCH.md`](RESEARCH.md). Read those first for *why*; this file is *what shipped after*.

- **Date:** 2026-06-14
- **Scope:** backend (backtest engine + service + live gate), frontend (preset surface),
  tests. No DB migration.
- **Status:** implemented + fully tested locally (470 frontend, 205 backtest backend, 199
  scanner/auto-trade backend tests pass; `tsc --noEmit` clean). Not yet verified in prod.

---

## 1. Background — what already existed (committed)

The FIX-005 core was already merged before this session:

| Commit | What |
|--------|------|
| `6b70949` | `signal_quality_filter.py` (pure `trend_aligned`, `is_falling_knife_short`, `trend_direction`); live gates in `auto_trade_service._try_trade`; opt-in `AutoTradeConfig` knobs `require_trend_alignment` / `block_falling_knife` (default **off**); 15 + 5 tests. |
| `8a78277` | TP/SL geometry helper `recommended_exit_pcts(leverage)` (tight 0.8% TP / 1.8% SL price move → win-rate >75% on held-out samples). |

At that point the filter existed and the live gate *called* it, but: (a) there was **no
way to apply the researched config** from the UI, (b) the **backtest engine did not run
the gates**, so a backtest couldn't show their effect, and (c) the live gate had a latent
interval-string bug (below) that silently disabled it in production.

This session closed all three.

---

## 2. The "Best Winrate" preset (productization)

A new preset that bundles the researched configuration so a user can apply it in one click —
both for a backtest and for a live auto-trade account.

### 2.1 Preset definition
- **`frontend/src/components/backtest/referencePresets.ts`** — added `BEST_WINRATE_CONFIG`.
  It spreads `OPTIMIZED_REFERENCE_CONFIG` and overrides four knobs:
  - `take_profit_pct: 5.6`, `stop_loss_pct: 12.6` — the tight geometry at leverage 7
    (0.8% TP / 1.8% SL **price** move = move% × leverage; see RESEARCH.md geometry table).
  - `require_trend_alignment: true`, `block_falling_knife: true` — the two signal gates ON.
- The preset's doc comment states the **win-rate vs profit-per-trade trade-off** explicitly:
  this maximizes win-rate (~80%, many small wins ~+0.20%/trade), whereas the wider Optimized
  geometry wins less often (~58%) but earns more per trade (~+0.73%). "Best Winrate" by name
  → the highest-win-rate geometry, which is the correct choice for this preset's purpose.

### 2.2 Backtest form — "Best Winrate Config" button
- **`BacktestConfigForm.tsx`** — `applyBestWinrate` handler + button (beside "Reference
  Config" / "Optimized Reference").
- **`configSchema.ts`** — `buildBestWinrateDefaults()`; added the 2 bool fields to the zod
  schema + the `buildDefaults` seed map; re-exports `BEST_WINRATE_CONFIG`.
- **`config-form/FiltersAdvancedTab.tsx`** — two visible Checkbox toggles (Require trend
  alignment / Block falling-knife shorts) so the gates are editable, not just preset-set.
- **`config-form/tabMeta.ts`** — both fields registered under the `filters` tab (satisfies
  the "every schema field maps to exactly one tab" invariant test).
- **`types.ts`** — added the 2 fields to `BacktestCreateRequest`.

### 2.3 Scanner auto-trade cards — "Apply Best Winrate" button
Appears on each account card in **Scheduled Market Scan** and **Market Scan**.
- **`scanner/applyReferencePreset.ts`** — extended `ReferencePresetId` union with
  `"best_winrate"`; added the 2 fields to `MAPPABLE_KEYS`; `getReferencePreset` returns
  `BEST_WINRATE_CONFIG`.
- **`scanner/AutoTradeSection.tsx`** — "Apply Best Winrate" button; `PRESET_LABELS` map for
  the confirm-dialog title; two `ToggleRow` switches; `DEFAULT_CONFIG` seeds the 2 fields.
- **`api/client.ts`** — added the 2 fields to the `AutoTradeConfig` type so they persist.

### 2.4 Backend backtest engine — actually run the gates
Without this, a backtest of a gate-on config would be identical to gate-off (the gates
existed only in live).
- **`backend/services/backtest_engine.py`** — `_apply_filter_chain` step 18 runs the gates,
  reusing the **same production `signal_quality_filter` functions** (single source of truth).
  Skipped for MR and relaxed/fill mode, exactly like live. New `_resample_klines` helper
  builds 1h/4h candles from the loaded 5m series.
- **`backend/schemas/backtest_schemas.py`** — added `require_trend_alignment` /
  `block_falling_knife` to `BacktestCreateRequest` (default off; `extra="forbid"` safe).

---

## 3. 🔴 Live correctness bug found & fixed — the gate was a silent no-op in prod

While wiring the backtest, we discovered the **live** gate (shipped in `6b70949`) was calling
the kline fetcher with the **wrong interval strings**, so it silently fetched nothing and
fail-opened — i.e. FIX-005's trend/knife gates were **never actually firing in production**.

- **Root cause:** `auto_trade_service._sq_klines` passed Bybit-style numeric strings
  `"60"` / `"240"` / `"5"`, but the production fetcher (`scanner_service._fetch` → the kline
  cache) expects `"1h"` / `"4h"` / `"5m"`. Wrong string → empty list → gate fail-opens (allow).
- **Fix (`auto_trade_service.py`):** `"60"→"1h"`, `"240"→"4h"`, `"5"→"5m"`.
- **Fix (`scanner_service.py`):** added `"5m"` to the `_fetch` window-sizing map
  (`{"5m": 5, "15m": 15, "1h": 60, "4h": 240}`) so a 5m request sizes its fetch window
  correctly (it previously fell back to the 60-min default → too few candles).

**Impact:** this is the difference between "Best Winrate is a real live feature" and "the
gates were inert." It is the single most important correctness fix in this batch.

---

## 4. Review-driven hardening (5 fixes)

After implementation, the feature was put through two independent adversarial reviewers
(backend correctness/parity + TypeScript). Every finding was verified against source before
fixing. Five real issues were fixed; all have regression tests.

### 4.1 🔴 HIGH — Backtest gate silently no-op'd at every window start (parity gap)
The engine resamples 5m→1h/4h, but the main kline load used a bare `date_range_start` with
**no pre-window history** (while BTC-vol and MR loads deliberately buffer). A 4h EMA21 needs
~3.5 days of prior candles, so for the first days of *every* window the trend couldn't be
computed and the gate fail-opened — a backtest **under-reported** the filter vs live.
- **Fix (`backtest_service.py`):** new `_signal_quality_lookback(config)` → `168h` (7 days =
  42 native 4h candles, enough for the EMA to fully converge) **only when a gate is on**,
  else `timedelta(0)` so every existing (gate-off) backtest loads a byte-identical window.
  Applied to the load **and** both cache-warm paths (`ensure_coverage`, expansion-warm).
- The sim loop anchors on `signal_time`, not `klines[0]`, so the extra lookback only adds
  history — it never shifts where the simulation starts.

### 4.2 🔴 HIGH — Backtest crashed where live fails-open
Live wraps the gate in `try/except → allow`; the backtest didn't, and `_resample_klines`
used direct `c["high"]` subscripts. A kline with `{h,l,c}` keys or a missing field would
`KeyError` and **abort the whole run** — live would just trade.
- **Fix (`backtest_engine.py`):** wrapped the gate block in `try/except → allow` (mirroring
  live), and switched `_resample_klines` to the tolerant `_h`/`_l`/`_c` accessors.

### 4.3 🔴 HIGH (frontend) — Signal gates "stuck ON" when switching presets
Only `BEST_WINRATE_CONFIG` set the gate fields; Reference/Optimized **omitted** them, and the
mapper copies only *defined* keys. So Apply Best Winrate → Apply Reference left a "Reference"
card **silently running the gates**.
- **Fix (`referencePresets.ts`):** added explicit `require_trend_alignment: false` /
  `block_falling_knife: false` to `DAD_DEMO_REFERENCE_CONFIG` (Optimized inherits via spread;
  Best Winrate still overrides to true). Now applying any preset resets the gates — matching
  every other boolean toggle. Regression test pins the reset.

### 4.4 🟡 MEDIUM — Resample didn't match native exchange candles
Chunks were anchored to the oldest cached bar (not UTC clock boundaries) and dropped the
trailing/most-recent partial bucket (the most decision-relevant candle).
- **Fix (`backtest_engine.py`):** `_resample_klines` now buckets on real clock boundaries
  (`epoch // bucket_seconds`, e.g. 3600 for 1h / 14400 for 4h), includes the latest bucket,
  and handles `open_time` as **datetime or epoch int/float** (the two engine code paths).

### 4.5 🟡 MEDIUM — `getReferencePreset` not exhaustive (future-break)
A new `ReferencePresetId` would silently fall through to the Reference preset.
- **Fix (`applyReferencePreset.ts`):** converted to a `switch` with a `never` exhaustiveness
  guard, so a future preset id fails to **compile** until a case is added.

---

## 5. Tests added/updated

| File | What |
|------|------|
| `tests/backend/test_backtest_engine.py` | `TestSignalQualityGates`: counter-trend filtered, trend-aligned passes, gates off by default, **fail-open on malformed klines**, **resample tolerates short keys + clock-aligns**, **resample handles epoch open_time**. |
| `tests/backend/test_backtest_loaders_parallel.py` | buffer on/off invariants: no buffer when gates off (byte-identical), 168h buffer when trend gate on, buffer when only knife gate on, `_signal_quality_lookback` zero-unless-active. |
| `tests/backend/test_backtest_schemas.py` | the 2 gate fields default off + round-trip when set. |
| `frontend/.../configSchema.test.ts` | `buildBestWinrateDefaults()` values; gates default off in base schema. |
| `frontend/.../applyReferencePreset.test.ts` | best_winrate delta vs optimized; `getReferencePreset` exhaustive; **applying Reference/Optimized after Best Winrate resets the gates**; 67-key count. |
| `frontend/.../AutoTradeSectionPresets.test.tsx` | all three buttons render; Best Winrate confirm dialog labelled + applies tight TP geometry (0.80% chip). |

**Result:** 470 frontend + 205 backtest backend + 199 scanner/auto-trade backend tests pass;
`tsc --noEmit` clean; golden tests confirm the gate-off path is unchanged.

---

## 6. ⚠️ Operational caveat (pre-existing — flagged, not changed here)

The **live** trend gate reads 1h/4h via `kline_cache.get_klines`, which is a **pure cache
read with no fetch-on-miss**. If production hasn't populated 1h/4h candles for a symbol, the
live trend gate fail-opens (safe, but inert) for that symbol. This is shared infrastructure —
MR-mean and BTC-vol have the identical precondition; the live regime classifier fetches 1h/4h
*directly from Bybit* on a separate path (`main.py` `_fetch_candles`, Bybit interval `"240"`).
Re-plumbing live kline-cache population is out of scope for this preset feature, but the
trend gate only bites for symbols whose 1h/4h candles are actually cached. **Follow-up
candidate:** a live 1h/4h warm path (or store-on-fetch in `get_klines`) so the gate is always
armed in production.

---

## 7. Rollout guidance

- The preset and gates are **opt-in** and **default off** — zero behavior change for existing
  accounts/backtests until a user applies "Best Winrate" or toggles a gate.
- Validate per-account in the backtest first (the engine now reflects the gates faithfully),
  then roll the live config to a paper/subset account before broad enablement — consistent
  with the RESEARCH.md guidance.
- Geometry is leverage-coupled: the preset's `5.6` / `12.6` assume **leverage 7**. If a user
  changes leverage, the price-move target shifts; use
  `signal_quality_filter.recommended_exit_pcts(leverage)` to recompute.
