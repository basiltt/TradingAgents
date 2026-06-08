# TA-Skipped Symbol Visibility — Design Spec

**Date:** 2026-06-08
**Status:** Approved (pending written-spec review)
**Author:** Brainstorming session
**Feature type:** Presentation / observability (no data-model change)

---

## 1. Problem Statement

When the **TA Pre-Filter** is enabled (`ta_prefilter_enabled = true`, crypto scans only),
every symbol is scored 0–100 by `TAPreFilterEngine` *before* any LLM analysis runs. Symbols
scoring **below the configured threshold** (default 40) are short-circuited — their LLM
analysis is skipped entirely — to save time and cost.

These skipped symbols are persisted as scan results with:

- `direction = "hold"`
- `score = 0`
- `signal_source = "ta_prefilter"`
- `decision_summary` = the engine's human-readable reason, e.g.
  *"TA score 22/40 < threshold 40 — skipping LLM analysis (no clear opportunity)"*

**The gap:** Because skipped symbols carry `direction = "hold"`, they are silently folded
into the **Hold / Neutral** count and table in every scan view. A user running a 580-symbol
scan with the prefilter on cannot tell how many symbols were actually evaluated by the LLM
versus how many were filtered out by TA before reaching it. The "Hold / Neutral" number is
therefore misleading — it conflates *"the LLM looked and said hold"* with
*"the TA filter never let the LLM look."*

This affects both the **live Market Scanner** and the **Scheduled Market Scanner**, since
both produce the same scan records.

## 2. Goal

Make TA-skipped symbols a **distinct, visible bucket** across all scan views, cleanly
separated from genuine LLM "Hold" results, with the ability to filter on it — without
changing the prefilter engine, scoring, the database schema, or auto-trade behavior.

## 3. Non-Goals (YAGNI)

- **No** changes to `TAPreFilterEngine`, its scoring, indicators, or threshold logic.
- **No** new database columns and **no** migration — all required data already exists.
- **No** changes to auto-trade signal filtering or any trade-placement path.
- **No** new score-breakdown drill-down UI. The existing per-symbol detail already exposes
  the `_ta_prefilter` report section; the new section shows the one-line reason only.
- **No** change to the meaning of the API's `direction_counts` map (kept raw to avoid
  rippling to other consumers — see §6.3).

## 4. Chosen Approach — Frontend-derived + minimal backend (Approach A)

The implementation is split by what data each view already has:

| View class | Components | Has row-level `results[]`? | How skipped count is obtained |
|---|---|---|---|
| **Detail views** | `ScannerPage.tsx` (live), `ScanDetailPage.tsx` (scheduled/historical detail) | **Yes** | Derived 100% client-side from `results[]` |
| **Aggregate views** | `ScanHistoryPage.tsx` (cards grid), `HistoryList.tsx` (dashboard) | **No** — only `direction_counts` | New backend `skipped_count` field |

**Why this approach:** Each skipped row is already uniquely tagged
`signal_source === "ta_prefilter"`, and detail views already receive the full `results[]`
array (the field rides along in the JSON payload today — only the TypeScript type omits it).
So cards, the new section, and the filter chip in the detail views need **zero backend
change** beyond declaring the existing field in the type. Only the aggregate views — which
receive a pre-grouped `direction_counts` map and no rows — require a new backend count.

Approaches considered and rejected:

- **Approach B (backend-authoritative everywhere):** backend computes the skipped count for
  every serialization path and the frontend never derives. Rejected: detail views must filter
  `results[]` to build the collapsible *list* and filter chip anyway, so a backend count there
  is redundant; more surface area for no benefit.
- **Approach C (`direction = "skipped"` at the source):** reclassify skipped rows' direction.
  Rejected: a data-model change touching auto-trade signal filtering, existing DB rows, and
  every `direction_counts` consumer — high regression risk for a display feature.

## 5. Shared Definitions

These two definitions are used consistently across **all** views and the filter logic. A
single source of truth in code is preferred (a small helper), so cards, sections, and filter
never drift:

- **Skipped bucket:** a result where `signal_source === "ta_prefilter"`.
- **Hold bucket (revised):** a result where
  `(direction === "hold" || direction === "unknown" || !direction)` **and**
  `signal_source !== "ta_prefilter"`.

Buy and Sell buckets are unchanged (`direction === "buy"` / `"sell"`); a skipped symbol can
never be buy/sell because it is always written with `direction = "hold"`.

## 6. Detailed Changes

### 6.1 Backend — aggregate `skipped_count` (the only backend work)

The aggregate history views call `scanner_service.list_scans()`, which merges **in-memory**
scans (serialized by `_serialize`) with **DB** scans (serialized by `_serialize_db`). Both
the DB query and **both** serializers must expose the count, or the number will be missing
for whichever scan source a given row came from.

**Files:**

1. `backend/async_persistence.py` — `AsyncAnalysisDB.list_scans()` (~line 1934):
   the existing per-scan aggregate is
   `SELECT scan_id, direction, COUNT(*) ... GROUP BY scan_id, direction`.
   Add a second aggregate (or a `FILTER`/conditional `SUM`) counting rows where
   `signal_source = 'ta_prefilter'` per `scan_id`, and attach it to each scan dict as
   `skipped_count` (int, default 0).

2. `backend/persistence.py` — sync `Persistence.list_scans()` (~line 1079):
   mirror the same change (this codebase keeps sync + async persistence in lockstep).

3. `backend/services/scanner_service.py`:
   - `_serialize_db()` (~line 830): pass `skipped_count` through from the DB dict
     (`scan.get("skipped_count", 0)`).
   - `_serialize()` (~line 796): for in-memory scans, compute
     `skipped_count = sum(1 for r in results if r.get("signal_source") == "ta_prefilter")`
     so live/just-finished scans in the cards grid are also correct.

**API shape:** each scan summary object returned by `GET /scanner` gains
`skipped_count: int`. No change to `direction_counts` (stays raw — see §6.3).

**No change** to `get_scan` / `_serialize` `results[]` payload itself: `signal_source` is
already included per row there for the detail views.

### 6.2 Frontend — TypeScript types

`frontend/src/api/client.ts`:

- `ScanResultItem`: add `signal_source?: string;` — the field is already present in the JSON
  response from the backend; this only declares it so the detail views can read it
  type-safely. (Backwards-compatible: optional, so older cached payloads don't break.)
- The scan-summary type used by the aggregate views (`ScanStatus` and/or the list item shape
  consumed by `ScanHistoryPage`/`HistoryList`): add `skipped_count?: number;`.

### 6.3 Why `direction_counts` stays raw

`direction_counts` is `{ buy, sell, hold }` grouped purely by the `direction` column and is
consumed in multiple places (`ScanHistoryPage`, `HistoryList`, possibly others). Redefining
`hold` to exclude skipped at the API layer would silently change every consumer's numbers.

Instead: the API keeps `direction_counts` raw, adds a **separate** `skipped_count`, and the
aggregate views compute the displayed hold as `(direction_counts.hold ?? 0) - skipped_count`
when they want a clean split. This keeps the change additive and low-risk.

### 6.4 Frontend — detail views (`ScannerPage.tsx`, `ScanDetailPage.tsx`)

Both views already compute `buyResults` / `sellResults` / `holdResults` by filtering the
(already filter-bar-filtered) results list. Changes, identical in both files:

**Bucketing** (via the shared `signalBucket` helper from §6.6 — preferred over inline
predicates so all consumers share one definition):

```ts
const skippedResults = filteredResults.filter(r => signalBucket(r) === "skipped");
const holdResults    = filteredResults.filter(r => signalBucket(r) === "hold");
const buyResults     = filteredResults.filter(r => signalBucket(r) === "buy");  // was: r.direction === "buy"
const sellResults    = filteredResults.filter(r => signalBucket(r) === "sell");
```

Buy/Sell results keep their existing sort order. Routing them through `signalBucket` is
optional but keeps all four buckets reading from one definition.

**A. Metric card.** Add a 4th card, "TA Skipped", to the stats row.
- `ScannerPage.tsx` (~lines 1145–1150): the row is a `grid grid-cols-2 sm:grid-cols-3`;
  becomes 4-up (`sm:grid-cols-4`, or `sm:grid-cols-2 lg:grid-cols-4` for small screens) using
  the existing `ScannerMetricCard`. **Render only when `skippedResults.length > 0`.**
- `ScanDetailPage.tsx` (~lines 477–489): the stat grid uses inline cards; add a matching 4th
  cell with the skipped count, same conditional visibility.
- **Tone:** a muted/neutral color (slate/gray), visually distinct from Hold's amber, to read
  as *"not evaluated"* rather than *"evaluated → neutral."* Use existing neutral tokens; do
  not introduce a new design token unless none fits.

**B. Collapsible "TA Skipped" section.** Add below the Hold / Neutral section, reusing the
existing collapsible pattern in each file (`ScannerPage` uses its responsive collapsible;
`ScanDetailPage` uses `CollapsibleSection`). **Render only when `skippedResults.length > 0`.**
- Title: "TA Skipped" with the count, dot/eyebrow in the muted tone.
- Body: the existing `ResultsTable` fed `skippedResults`. Each row already shows the symbol,
  `score` (0), and `decision_summary` (the reason). No new table component needed.
- Because `holdResults` now excludes skipped, the Hold table and the Skipped table never
  double-count the same symbol.

### 6.5 Frontend — filter chip (`ScanResultFilters.tsx`)

The shared filter module backs both detail views. Today the Signal group is Buy / Sell /
Hold and the filter predicate keys purely off `direction`, mapping `hold`/`unknown` → `"hold"`.

**Changes:**

- Add a **"Skipped"** `FilterChip` to the Signal `FilterSection` (~line 232), in the muted
  tone, toggling the signal value `"skipped"`.
- Update the filter predicate in `useScanFilters` (~lines 119–124) so a row's *effective
  signal bucket* is computed via the shared `signalBucket(r)` helper (§6.6) and matched with
  `filters.signal.has(signalBucket(r))`. The helper returns `"skipped"` when
  `signal_source === "ta_prefilter"`, else `"hold"` for `hold`/`unknown`/missing direction,
  else the raw `buy`/`sell` direction. This makes the "Hold" chip exclude skipped and the new
  "Skipped" chip isolate them — consistent with the cards and sections.
- No change needed to `ScanFiltersState` (the `signal` set already holds arbitrary strings),
  persistence, or the `{filteredCount} of {totalCount}` badge (recomputes automatically).

### 6.6 Shared helper (recommended)

To prevent drift between cards, sections, and filter, extract the bucket logic into one place
— e.g. a `signalBucket(r: ScanResultItem): "buy" | "sell" | "hold" | "skipped"` helper
co-located with `ScanResultFilters.tsx` (it already imports `ScanResultItem`). Its three call
sites — the filter predicate (§6.5) and the `skippedResults`/`holdResults` bucketing in each
of the two detail views (§6.4) — all call it, so the definition lives in exactly one place.

Reference implementation:

```ts
export function signalBucket(r: ScanResultItem): "buy" | "sell" | "hold" | "skipped" {
  if (r.signal_source === "ta_prefilter") return "skipped";
  if (r.direction === "buy" || r.direction === "sell") return r.direction;
  return "hold"; // hold, unknown, or missing
}
```

### 6.7 Frontend — aggregate views

- `ScanHistoryPage.tsx` (scan cards grid, ~line 244): alongside the existing buy/sell display,
  show a "skipped" indicator from `scan.skipped_count` when `> 0` (small muted badge, e.g.
  "N skipped"). Optionally display the de-skipped hold using the §6.3 subtraction.
- `HistoryList.tsx` (dashboard, ~line 348): if it surfaces hold/skipped at the aggregate
  level, apply the same treatment. (Primary stat shown there is Buy Signals; adding skipped is
  optional polish — include a muted skipped count if it fits the existing stat row.)
- These are counts only — **no** list or filter at the aggregate level (no row data available,
  and not needed).

## 7. Edge Cases

| Case | Behavior |
|---|---|
| Prefilter **off**, or stock scan | No row has `signal_source === "ta_prefilter"` → `skipped` count is 0 → card hidden, section hidden, filter chip matches nothing. Zero visible change vs. today. |
| Prefilter **error** / insufficient data | `TAPreFilterEngine` fails **open** (`should_proceed = true`, score 100) → symbol proceeds to LLM and is written with a real `signal_source` (`structured`/`regex_fallback`), **not** `ta_prefilter`. Correctly excluded from the skipped bucket. |
| Filter "Skipped" selected | Only `signal_source === "ta_prefilter"` rows shown; all four cards + `{filteredCount} of {totalCount}` recompute off `filteredResults`, staying mutually consistent. |
| Old scans (pre-feature) | `scan_results.signal_source` already exists (DB default `'unknown'`; prefilter rows already written as `'ta_prefilter'`). No migration; historical scans render correctly. |
| Mixed scan (some skipped, some analyzed) | Buckets partition cleanly: buy + sell + hold(revised) + skipped = total completed. |
| In-memory live scan vs. DB scan in cards grid | `skipped_count` computed in both `_serialize` (in-memory) and `_serialize_db` (DB), so the cards grid is correct regardless of source. |

## 8. Testing Strategy

**Backend (`tests/backend/`, pytest + pytest-asyncio):**

- `list_scans` returns correct `skipped_count` for a scan mixing `ta_prefilter` rows with real
  `hold`/`buy`/`sell` rows.
- `skipped_count == 0` when a scan has no `ta_prefilter` rows.
- `_serialize` (in-memory) and `_serialize_db` (DB) both surface `skipped_count` with the same
  value for an equivalent scan.

**Frontend (component/unit tests):**

- `signalBucket()` helper classifies: `ta_prefilter` → `"skipped"`; `hold` + non-prefilter →
  `"hold"`; `buy`/`sell` unchanged.
- Skipped symbols are **excluded** from `holdResults` and **included** in `skippedResults`.
- Card + section render only when `skippedResults.length > 0`; hidden otherwise.
- "Skipped" filter chip isolates only `signal_source === "ta_prefilter"` rows; "Hold" chip
  excludes them.

**Validation before completion (per project rules):**
`python -m pytest tests/backend/ -x -q`, `cd frontend && npx tsc --noEmit`,
`cd frontend && npm run build`.

## 9. Affected Files Summary

**Backend (3 files):**
- `backend/async_persistence.py` — add `skipped_count` aggregate to `list_scans`.
- `backend/persistence.py` — mirror the same in sync `list_scans`.
- `backend/services/scanner_service.py` — surface `skipped_count` in `_serialize` and
  `_serialize_db`.

**Frontend (6 files):**
- `frontend/src/api/client.ts` — `signal_source?` on `ScanResultItem`; `skipped_count?` on
  scan summary type(s).
- `frontend/src/components/scanner/ScanResultFilters.tsx` — Skipped chip + bucket predicate +
  shared `signalBucket` helper.
- `frontend/src/components/scanner/ScannerPage.tsx` — 4th card + skipped section + bucketing.
- `frontend/src/components/scanner/ScanDetailPage.tsx` — 4th card + skipped section + bucketing.
- `frontend/src/components/scanner/ScanHistoryPage.tsx` — skipped badge on scan cards.
- `frontend/src/components/dashboard/HistoryList.tsx` — optional skipped count in stat row.

**No** files in `tradingagents/ta_prefilter/`, no schema/migration files, no auto-trade files.

## 10. Requirements Traceability

| # | Requirement | Satisfied by |
|---|---|---|
| R1 | Show how many symbols were skipped by the TA filter, separate from Hold | §6.4 (card), §6.1 (aggregate count) |
| R2 | Skipped excluded from the Hold count/table | §5, §6.4 |
| R3 | Dedicated skipped section listing each skipped symbol + reason | §6.4-B |
| R4 | Skipped is filterable | §6.5 |
| R5 | Works for both live and scheduled scans, all views | §4 table, §6.1, §6.4, §6.7 |
| R6 | No prefilter-engine / schema / auto-trade changes | §3, §9 |
| R7 | Non-prefilter scans unchanged (clean 3-card layout) | §6.4 (conditional render), §7 |

