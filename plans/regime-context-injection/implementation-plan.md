# Implementation Plan — Regime-Context Injection (Lite, TDD)

**Spec:** `specs/regime-context-injection-spec.md`
**Mode:** Lite. 3 phases, strict TDD (RED→GREEN→REFACTOR) per task. Default-OFF flag.
**Test runner:** `python -m pytest tests/ -x -q` (subset per phase).

---

## Phase 0 — Worktree + baseline

- **T0.1** Create worktree `regime-context-injection`.
- **T0.2** Baseline: `python -m pytest tests/backend/ -q` (record pass count). Must be green before any change.

---

## Phase 1 — Pure regime-context builder

**File (NEW):** `tradingagents/agents/utils/regime_context.py`
**Test (NEW):** `tests/test_regime_context_builder.py`

### Module API (exact)
```python
# regime_context.py — imports: only stdlib (logging, typing). NO backend.*, NO market_data.
from typing import Optional, Sequence

REGIME_TREND_THRESH_PCT = 1.0   # matches market_data regime_trend_ema_dist_pct default
REGIME_SKEW_MIN_SAMPLE = 20

def _ema(values: Sequence[float], period: int) -> Optional[float]:
    # copied semantics from market_data.py:63-74 (no import)
    ...

def _ema_distance_pct(closes: Sequence[float], period: int) -> Optional[float]:
    # (close[-1] - ema) / ema * 100 ; copied from market_data.py:80-86
    ...

def btc_scalars_from_closes(closes: Sequence[float], period: int = 14) -> tuple[Optional[float], Optional[float]]:
    # returns (trend_pct, move_pct); move_pct = (closes[-1]-closes[0])/closes[0]*100, guard closes[0]==0 -> None
    ...

def build_regime_context_block(
    btc_trend_pct: Optional[float],
    btc_move_pct: Optional[float],
    signal_skew: Optional[dict],          # {short_pct, long_pct, sample_n, window}
    *, trend_thresh: float = REGIME_TREND_THRESH_PCT,
    min_sample: int = REGIME_SKEW_MIN_SAMPLE,
) -> str:
    # returns "" if btc_trend_pct is None AND skew insufficient; else labeled block ending "\n\n"
    ...
```

### Tasks (each: write failing test first)
- **T1.1** `_ema` / `_ema_distance_pct` parity: test asserts equality with `market_data.compute_ema_distance_pct` on a shared close fixture (import the original INSIDE the test only). (AC-2 base, FR-1.2a)
- **T1.2** `btc_scalars_from_closes`: rising/falling/flat fixtures → correct sign; `closes[0]==0` → move `None`; short series (< period) → trend `None`. (FR-1.2, FR-1.3)
- **T1.3** Direction mapping: trend `+1.5` → "rising / favors LONGS"; `-1.5` → "falling / favors SHORTS"; `0.3` → "flat". (FR-1.2)
- **T1.4** Skew line: `{short_pct:89,long_pct:8,sample_n:200}` → contains "89% SHORT"; `sample_n:19` → no skew line; `sample_n:0` → no skew line. (FR-1.4)
- **T1.5** Conflict warning: rising BTC + short_pct≥70 → squeeze-warning present; flat BTC + short skew → **no** warning; falling BTC + short skew → no squeeze warning. (FR-1.5)
- **T1.6** Empty/insufficient: `(None, None, None)` → `""`; block (when non-empty) ends with `"\n\n"`. (FR-1.6)
- **T1.7** Import-guard (AST): parse module source, assert no import references `backend`/`scan_context`/`market_data`/gate modules. (AC-6)

### Validate Phase 1
`python -m pytest tests/test_regime_context_builder.py -q` → all green.

---

## Phase 2 — Wiring: persistence skew query + scanner compute + analysis thread + allowlist

### T2.1 — Persistence read method (FR-2.6)
**File:** `backend/async_persistence.py`
**Test:** `tests/backend/test_signal_skew_query.py`
```python
async def get_recent_signal_skew(self, *, exclude_scan_id: str | None = None,
                                 window: int = 200, min_abs_score: int = 6) -> dict:
    # SELECT direction-sign counts over recent scan_results, ABS(score) >= min_abs_score,
    # scan_id != exclude_scan_id, ORDER BY <chronological pk/completed_at> DESC LIMIT window.
    # returns {"short_pct": float, "long_pct": float, "sample_n": int, "window": window}
```
- **T2.1a** (RED) test against a seeded in-memory/test DB fixture: insert mixed score rows, assert short_pct/long_pct/sample_n. Verify `exclude_scan_id` filters current scan. (FR-2.3)
- Score sign: `score < 0` → short, `score > 0` → long, `score == 0`/below min → excluded.
- **DISCOVERY TASK first:** read how other `async_persistence.py` read methods acquire a connection + how tests seed scan_results (mirror an existing read-method test exactly). If no DB test harness exists, make the query a thin method and unit-test the SQL builder + parse logic with a fake `fetch`.

### T2.2 — Scanner flag helper + per-scan compute (FR-2.1/2.2/2.4/2.5, FR-5)
**File:** `backend/services/scanner_service.py`
**Test:** `tests/backend/test_scanner_regime_context.py`
```python
REGIME_BTC_INTERVAL = "1h"
REGIME_BTC_LOOKBACK = 14
REGIME_ACTIONABLE_MIN_SCORE = 6

def _regime_context_enabled() -> bool:
    return (os.environ.get("TRADINGAGENTS_REGIME_CONTEXT","") or "").strip().lower() in ("1","true","yes","on")

async def _build_scan_regime_context(self, scan_id: str) -> str:
    # fail-open: try/except -> "" + logger.warning. If not _regime_context_enabled(): return "".
    # 1) klines = await self._kline_cache.get_klines("BTCUSDT", REGIME_BTC_INTERVAL, start, end)
    # 2) closes -> btc_scalars_from_closes(closes, REGIME_BTC_LOOKBACK)
    # 3) skew = await self._db.get_recent_signal_skew(exclude_scan_id=scan_id) if self._db else None
    # 4) return build_regime_context_block(trend_pct, move_pct, skew)
```
- Call site: in the scan-execution method, after symbols resolved + before the `_process_ticker` fan-out (near line 1100–1145). Store `scan["regime_context"] = await self._build_scan_regime_context(scan_id)`.
- **T2.2a** (RED) flag OFF → `_build_scan_regime_context` returns `""` (no kline/db calls). (AC-8/FR-2.4)
- **T2.2b** flag ON + stub kline cache (rising closes) + stub db skew → returns a non-empty block containing "rising". (FR-2.1)
- **T2.2c** flag ON + kline cache raises → returns `""`, WARNING logged, no exception. (AC-5 fail-open)
- **T2.2d** interval constant is "1h" (guards the "D" fail-open trap). (FR-2.2)

### T2.3 — Inject into per-coin request (FR-2.5)
**File:** `backend/services/scanner_service.py` `_run_single`
- Add to the `request` dict: `"regime_context": scan.get("regime_context", "")` (read from the `_scans[scan_id]` entry under lock, like `config`).
- **T2.3a** (RED) test: with `scan["regime_context"]="X"`, the request dict built in `_run_single` carries `regime_context="X"`. (May require extracting request-building or asserting via a spy on `self._analysis.start_analysis`.)

### T2.4 — Thread through analysis_service (FR-3)
**File:** `backend/services/analysis_service.py` (`_prepare_graph_run`, ~line 704)
- Change `create_initial_state(...)` call to add `regime_context=request.get("regime_context", "") or ""`.
- **T2.4a** (RED) test: `_prepare_graph_run` with `request["regime_context"]="X"` → `init_state["regime_context"]=="X"`; absent → `""`. (FR-3.1/3.2)

### T2.5 — State-filter allowlist (FR-6)
**File:** `tradingagents/agents/constants.py`
- Add `"regime_context"` to `READABLE_KEYS["portfolio_manager"]` and `READABLE_KEYS["technical_analyst"]`.
- **T2.5a** (RED) test with `use_information_barriers=ON`: `filter_state_for_read({"regime_context":"X",...}, "portfolio_manager")` keeps it; same for `technical_analyst`; `news_analyst` strips it. (AC-4, FR-6.3)

### Validate Phase 2
`python -m pytest tests/backend/test_signal_skew_query.py tests/backend/test_scanner_regime_context.py -q` + the analysis/constants tests → green.

---

## Phase 3 — PM prompt injection + byte-identical regression

**File:** `tradingagents/agents/crypto_analysts.py` (`create_crypto_portfolio_manager._prepare`)
**Test:** `tests/test_pm_regime_injection.py`

### T3.1 — Read + inject with empty-guard (FR-4.1/4.2)
- In `_prepare`: `regime_ctx = filtered.get("regime_context", "") or ""` then `regime_block = f"{regime_ctx.strip()}\n\n" if regime_ctx.strip() else ""`.
- Interpolate `{regime_block}` into the prompt f-string **between** the `CURRENT PRICE DATA...{price_context}\n\n` line and the `Max allowed leverage:` line.
- **T3.1a** (RED) non-empty `regime_context` in state (barriers ON) → rendered prompt contains the block, positioned before "Max allowed leverage" and after the price block. (AC-3)

### T3.2 — Byte-identical OFF golden (FR-4.3, AC-1) — THE safety test
- Capture golden: render `_prepare` prompt with `regime_context` absent (today's behavior) → store expected string in the test.
- **T3.2a** parametrized `{absent, ""}` → rendered PM prompt `==` golden (byte-identical).
- **T3.2b** Same golden assertion for the **technical analyst** `system_message` with `regime_context=""`/absent (it references the field; ensure empty-guard there too — if the existing code already guards via `... or ""`, just assert). (AC-1)

### T3.3 — End-to-end flag-OFF contract (AC-8)
- **T3.3a** Integration-ish: barriers ON + flag unset → drive the scanner→`_run_single`→`_prepare_graph_run` path with stubs → `init_state["regime_context"]==""` → PM prompt == golden.

### Validate Phase 3
`python -m pytest tests/test_pm_regime_injection.py -q` → green.

---

## Phase 4 — Full validation + sim reconfirm
- **T4.1** `python -m pytest tests/ -q` (full suite) — no regressions.
- **T4.2** Re-run `_debug_analysis/sim_regime_ab.py` (manual, AC-7) — confirm A:APPROVE vs B/C/D:REJECT still holds with the production-shaped prompt now produced by real `_prepare` (feed a non-empty regime_context through state).
- **T4.3** Lint/typecheck if configured (`ruff`/`mypy` if present; else skip with note).

## Decided Log (contradiction guard)
- D1: Builder takes **scalars**, not klines/market_data import (resolves Critical isolation). 
- D2: BTC interval **forced to "1h"**, never scan config interval (resolves fail-open).
- D3: Skew is a **global rolling window** over scan_results excluding current scan (account-agnostic by construction).
- D4: Reversibility guaranteed by **producer-side** gating + empty-guard concat; allowlist edit is additive.
- D5: Only `portfolio_manager` + `technical_analyst` get allowlist access; other analysts keep dead `""` read.

## Out of scope (deferred P1)
Directional-accuracy feedback loop (new table + background horizon job). Documented in FINDINGS.md.
