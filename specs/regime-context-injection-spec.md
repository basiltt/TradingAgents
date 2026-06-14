# Spec — Market-Regime + Portfolio-Skew Context Injection (LLM Scanner)

**Feature:** `regime-context-injection`
**Mode:** Lite pipeline (focused wiring fix)
**Date:** 2026-06-13
**Root-cause evidence:** `_debug_analysis/FINDINGS.md`

---

## 1. Problem & Goal

### Problem (proven)
The LLM market scanner analyzes every coin **blind to market regime** and **blind to its own signal book**. The `regime_context` field is threaded through the graph but is **always `""`** in production, and the Portfolio Manager (PM) — the agent that emits the final Buy/Sell/Hold rating — does not even read it. Consequence: a structurally ~89%-short book that bleeds when the market rises (win rate 64% → 27% from Jun 6).

### Goal
Compute, once per scan, an **account-agnostic** regime-context string (BTC trend **direction** + recent signal long/short skew) and inject it into the analyst **and** PM prompts — behind a **default-OFF** environment flag, fully reversible, with zero impact on the execution money-path.

### Proven effect (simulation)
Adding this context flips a real losing counter-trend short from APPROVE → REJECT, while a bearish-regime control keeps trend-aligned shorts (Sell). It discriminates by direction; it does not blanket-suppress.

### Non-Goals (explicit)
- **No** account-agnostic directional-accuracy *feedback loop* (deferred P1 — needs a background horizon-tracking job + table).
- **No** changes to execution-side regime gates (F1/F2/F3), `classify_regime`, `BtcRegime`, or `ScanContext`.
- **No** changes to TP/SL/leverage/per-account configs.
- **No** change to the score formula `score = sign × confidence`.
- **No** raising of `min_score` (score is uncalibrated; not the lever).

---

## 2. Key Constraints

| ID | Constraint |
|---|---|
| C-1 | **Account-agnostic.** Context is identical for all N per-account configs consuming the signal. NO per-account `net_pnl`, balances, TP/SL, or leverage may appear in it. |
| C-2 | **Default-OFF.** Gated by `TRADINGAGENTS_REGIME_CONTEXT=1` (off → byte-identical current behavior). |
| C-3 | **Zero money-path blast radius.** Must not import from / modify the F1/F2/F3 execution gates, `ScanContext`, or `classify_regime`. Reuse only pure primitives (`compute_ema_distance_pct`). |
| C-4 | **Fail-open.** Any error computing regime context → log + pass `""` (current behavior). A scan must never fail because regime context could not be built. |
| C-5 | **Cheap.** One BTC kline fetch + one DB skew query per scan (not per coin). No added per-coin network I/O. |
| C-6 | **Directional.** The context MUST state BTC trend up/down/flat — direction is the crux (existing `BtcRegime` is non-directional and is NOT reused for the label). |

---

## 3. Functional Requirements

### FR-1 — Regime-context builder (new pure module)
New module `tradingagents/agents/utils/regime_context.py` — **genuinely pure: imports ONLY stdlib.** It must NOT import `backend.services.market_data` (that module top-level-imports `backend.services.scan_context`, which would drag `ScanContext` into the import graph, violate C-3/NFR-3, fail AC-6, and invert layering). The ~6 lines of EMA math are **copied** into this module as a private helper.

- **FR-1.1** `build_regime_context_block(btc_trend_pct, btc_move_pct, signal_skew) -> str` — pure function of **scalars + a dict** (NOT raw klines): `btc_trend_pct` = signed EMA-distance % (computed by the caller), `btc_move_pct` = signed first→last % move over the window, `signal_skew` = `{short_pct, long_pct, sample_n, window}`. Returns a formatted block or `""` if inputs insufficient. (Caller in `scanner_service` does the kline→scalar reduction — backend→backend is allowed.)
- **FR-1.2** BTC direction from `btc_trend_pct` (signed). Map: `>= +trend_thresh` → "rising / favors LONGS"; `<= -trend_thresh` → "falling / favors SHORTS"; else "flat / no directional edge". Default `trend_thresh = 1.0` (% — matches existing `regime_trend_ema_dist_pct` default).
- **FR-1.2a** A private `_ema(values, period)` + `_ema_distance_pct(closes, period)` helper is copied verbatim (semantically) from `market_data.py:63-86` into this module so there is **no cross-module import**. A unit test asserts it produces the same number as the original on a shared fixture (parity test, import done inside the test only).
- **FR-1.3** Include BTC `btc_move_pct` (signed first→last close % over the window) and the trend label. Caller guards first-close `== 0` (returns `None` → builder treats as "move unavailable").
- **FR-1.4** Portfolio-skew line from `signal_skew`: e.g. "Recent signal book: 89% SHORT / 8% LONG (last 200 actionable signals). The book is one-sided — demand a higher bar for another SHORT." Only emitted when `sample_n >= min_sample` (default 20). `sample_n == 0` and `0 < sample_n < 20` are distinct (both → no skew line, but logged differently).
- **FR-1.5** Cross-signal warning when BTC direction and book skew conflict (e.g. BTC rising + book ≥70% short → "Counter-trend shorts into a rising tape carry elevated squeeze risk."). BTC flat ⇒ **no** conflict warning.
- **FR-1.6** Output is a labeled block ending in `\n\n`, safe to concatenate into a prompt. Empty/insufficient inputs → `""` (never partial/garbled).

### FR-2 — Per-scan computation (scanner)
In `backend/services/scanner_service.py`:
- **FR-2.1** When flag ON, compute the regime-context string **once per scan** (not per coin), after symbols are resolved and before the per-ticker fan-out. The scanner reduces BTC klines → two scalars (`btc_trend_pct` via the builder's `_ema_distance_pct`, `btc_move_pct` via first→last close) and queries skew, then calls `build_regime_context_block(...)`.
- **FR-2.2** BTC klines sourced via the existing kline cache (`self._kline_cache.get_klines("BTCUSDT", interval, …)`), reusing the same fetch shape as `_set_executor_scan_context._fetch`. **Interval MUST be a regime-supported value — force `"1h"`** (a new constant `REGIME_BTC_INTERVAL="1h"`). DO NOT use the scan config `interval` (it defaults to `"D"`/`"15"`, which the `_fetch` minute-map lacks → empty klines → feature silently never fires). Lookback default 14 candles. If klines come back empty/short → log WARNING + `regime_context=""` (fail-open).
- **FR-2.3** Signal skew via one NEW read method on the DB layer over recent `scan_results`: `ORDER BY <chronological> DESC LIMIT 200`, filtered to actionable rows (`ABS(score) >= 6`, named constant `REGIME_ACTIONABLE_MIN_SCORE=6`), **excluding the current `scan_id`** (its rows don't exist yet at FR-2.1 time, but exclude defensively against overlapping schedules). Returns `{short_pct, long_pct, sample_n, window}`. Account-agnostic by construction (`scan_results` has no `account_id` column — confirmed). Documented as a **global book** across schedules (acceptable: the short bias is structural).
- **FR-2.4** Cache the computed string on the scan dict (`scan["regime_context"]`). Flag OFF or any error → `""`.
- **FR-2.5** Pass `scan["regime_context"]` into each per-coin `request` dict built in `_run_single` (new key `regime_context`).
- **FR-2.6** New DB read method lives in `backend/async_persistence.py` (alongside `insert_scan_result`): `async def get_recent_signal_skew(self, *, exclude_scan_id, window=200, min_abs_score=6) -> dict`. Pure read; no writes.

### FR-3 — Thread through analysis service
In `backend/services/analysis_service.py`:
- **FR-3.1** In `_prepare_graph_run` (the `create_initial_state` call ~line 704), pass `regime_context=request.get("regime_context", "")`.
- **FR-3.2** No behavior change when the key is absent/empty (default `""`).

### FR-4 — Inject into the Portfolio Manager prompt
In `tradingagents/agents/crypto_analysts.py` `create_crypto_portfolio_manager._prepare`:
- **FR-4.1** Read `regime_context` from filtered state: `regime_ctx = filtered.get("regime_context", "") or ""`.
- **FR-4.2** Insert it into the PM prompt **between the CURRENT PRICE DATA block and "Max allowed leverage"** (the exact slot validated in simulation arms B/C/D), using a **conditional-concat empty-guard** mirroring the technical analyst's pattern: build a local `regime_block = f"{regime_ctx}\n\n" if regime_ctx.strip() else ""` and interpolate `{regime_block}` into the f-string. An empty value contributes the empty string — **no stray newlines**.
- **FR-4.3** When `regime_context` is `""` (or absent), the rendered PM prompt is **byte-identical** to today's (pinned by a frozen-golden equality test over both `absent` and `""` cases).
- **FR-4.4** The technical analyst already references `regime_context` (line 77) but it was being stripped by the state filter (see FR-6); once FR-6.2 lands it receives the real value. The derivatives/news/fundamentals analysts also reference it but are **intentionally NOT** added to the allowlist (FR-6.3) — they continue to receive `""` (documented dead read, asserted by test).

### FR-5 — Flag
- **FR-5.1** `TRADINGAGENTS_REGIME_CONTEXT` read with the existing truthy convention (`in ("1","true","yes","on")`). Default OFF.
- **FR-5.2** A single helper `_regime_context_enabled()` in scanner_service mirrors `_async_graph_enabled()`.

### FR-6 — State-filter allowlist (CRITICAL, discovered during design)
The per-role `READABLE_KEYS` allowlist in `tradingagents/agents/constants.py` strips any state key not explicitly listed. **Neither `portfolio_manager` nor `technical_analyst` currently lists `regime_context`** — so even today's `filtered.get("regime_context")` in the technical analyst is silently stripped. Without this fix the injected context never reaches any agent.
- **FR-6.1** Add `"regime_context"` to `READABLE_KEYS["portfolio_manager"]`.
- **FR-6.2** Add `"regime_context"` to `READABLE_KEYS["technical_analyst"]`.
- **FR-6.3** No other role gains read access (keep blast radius minimal).
- **FR-6.4** This is additive (a new readable key). **Reversibility contract:** the byte-identical-OFF property (NFR-1) is guaranteed by the *producer* side — when the flag is OFF the scanner never populates `regime_context` (stays `""`), and the FR-4.2 empty-guard makes `""` contribute nothing. The allowlist edit only changes behavior if some *other* entrypoint puts a non-empty `regime_context` in state; today only the scanner does, and it is flag-gated. A test pins this: barriers ON + flag-OFF scanner path ⇒ `regime_context == ""` reaches the PM. (If a future non-scanner entrypoint sets it, that is its responsibility to gate.)

---

## 4. Non-Functional Requirements

| ID | NFR |
|---|---|
| NFR-1 | **Reversibility:** flag OFF ⇒ behavior byte-identical to pre-change (verified by a prompt-equality test with `regime_context=""`). |
| NFR-2 | **Performance:** ≤ 1 extra BTC kline read (cached) + 1 DB query per scan; 0 extra per-coin I/O. |
| NFR-3 | **Isolation:** new module imports only stdlib + `compute_ema_distance_pct`; no money-path / ScanContext imports (enforced by an import-guard test). |
| NFR-4 | **Observability:** log once per scan at INFO when context is built (regime label + skew %), and at WARNING (not ERROR) on fail-open. |
| NFR-5 | **Determinism:** builder is a pure function of its inputs (unit-testable with no I/O). |

---

## 5. Acceptance Criteria

- **AC-1** (reversibility — the key safety property) Frozen-golden equality: with `regime_context` both **absent** and **`""`**, the rendered PM `_prepare` prompt AND the technical-analyst `system_message` are byte-identical to a captured golden of current output. Parametrized over `{absent, ""}`.
- **AC-2** With a rising BTC (`btc_trend_pct >= +1.0`) + 89%-short skew (`sample_n >= 20`), `build_regime_context_block` returns a string containing structural tokens: BTC direction ("rising"), skew (short_pct rendered), and the squeeze warning. Also assert falling, flat-no-warning, and below-sample arms.
- **AC-3** With a non-empty `regime_context` in state + barriers ON, the PM `_prepare` prompt contains the regime block in the slot between the price-data block and "Max allowed leverage".
- **AC-4** With `use_information_barriers=ON`, `filter_state_for_read` **keeps** `regime_context` for `portfolio_manager` and `technical_analyst`, and **strips** it for a control role (e.g. `news_analyst`) — proving FR-6.1/6.2 landed and FR-6.3 holds.
- **AC-5** (fail-open) Monkeypatch the builder to `raise`; run the scanner path; assert the scan completes and `scan["regime_context"] == ""` and a WARNING (not ERROR) was logged. Separately, empty/short klines → builder returns `""` (defined path).
- **AC-6** Import-guard via **AST parse** of `regime_context.py` source: assert it contains no `import`/`from` referencing `backend`, `scan_context`, `market_data`, or the F1/F2/F3 gate modules. Back with a fresh-subprocess import smoke check (avoids `sys.modules` cross-test leakage).
- **AC-7** (manual validation, not CI) Re-running the simulation arms (A vs B/C/D) against the real model reproduces APPROVE→REJECT. Demoted to a documented manual check — depends on a live non-deterministic LLM; the deterministic guarantee is AC-3.
- **AC-8** Flag-OFF producer contract: with `TRADINGAGENTS_REGIME_CONTEXT` unset and barriers ON, the scanner→analysis path yields `regime_context == ""` at the PM (pins FR-6.4).

---

## 6. Files Touched

| File | Change |
|---|---|
| `tradingagents/agents/utils/regime_context.py` | **NEW** — pure builder (FR-1) |
| `tradingagents/agents/constants.py` | Add `regime_context` to 2 READABLE_KEYS lists (FR-6) |
| `tradingagents/agents/crypto_analysts.py` | PM `_prepare` reads + injects `regime_context` (FR-4) |
| `backend/services/scanner_service.py` | Flag helper + per-scan compute + pass into request (FR-2, FR-5) |
| `backend/services/analysis_service.py` | Pass `regime_context` into `create_initial_state` (FR-3) |
| `backend/async_persistence.py` | **NEW** read method `get_recent_signal_skew(...)` (FR-2.6) |
| `tests/...` | New unit + integration + regression tests (Phase tests) |

## 7. Rollout
- Ship default-OFF. Validate on the dev MCP/scanner. Enable via `TRADINGAGENTS_REGIME_CONTEXT=1` on prod once a scan's logs show sane regime/skew lines. Roll back = unset the env var (no redeploy of logic).

## 8. Deferred (documented follow-up)
Account-agnostic **directional-accuracy feedback loop**: background job stamps each signal's price N hours later, computes directional hit-rate by regime/confidence tier, injects "your recent SHORT hit-rate in rising regimes is 22%" into the prompt. Requires a new table + scheduler task. Tracked as P1 in `_debug_analysis/FINDINGS.md`.
