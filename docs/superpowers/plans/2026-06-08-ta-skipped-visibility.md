# TA-Skipped Symbol Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface TA-pre-filter-skipped symbols as a distinct, filterable bucket (metric card + collapsible section + filter chip) across all scan views, cleanly separated from genuine LLM "Hold" results.

**Architecture:** Skipped symbols already carry `signal_source = "ta_prefilter"` on each persisted scan result and flow to the detail views in the `results[]` payload — so detail-view cards, sections, and the filter chip are derived 100% client-side via a single shared `signalBucket()` helper. The only backend work is adding a `skipped_count` aggregate to `list_scans` (async + sync persistence + both serializers) for the aggregate history views, which receive grouped counts but no rows. No schema change, no migration, no prefilter-engine or auto-trade changes.

**Tech Stack:** Backend — Python 3.12, asyncpg/psycopg2, pytest + pytest-asyncio. Frontend — React 18 + TypeScript (strict), Vitest + Testing Library, TanStack Query/Router.

**Spec:** `docs/superpowers/specs/2026-06-08-ta-skipped-visibility-design.md`

---

## File Structure

**Backend (3 files modified):**
- `backend/async_persistence.py` — `AsyncAnalysisDB.list_scans()`: add per-scan `skipped_count` aggregate (`signal_source = 'ta_prefilter'`).
- `backend/persistence.py` — sync `AnalysisDB.list_scans()`: mirror the same aggregate.
- `backend/services/scanner_service.py` — `_serialize()` (in-memory scans) and `_serialize_db()` (DB scans): expose `skipped_count` in the serialized scan summary.

**Frontend (5 files modified, 1 test file created):**
- `frontend/src/api/client.ts` — add `signal_source?: string` to `ScanResultItem`; add `skipped_count?: number` to `ScanStatus`.
- `frontend/src/components/scanner/ScanResultFilters.tsx` — export `signalBucket()` helper; add "Skipped" filter chip; route the signal predicate through the helper.
- `frontend/src/components/scanner/ScannerPage.tsx` — derive `skippedResults`, revise `holdResults`, add 4th "TA Skipped" metric card + collapsible section.
- `frontend/src/components/scanner/ScanDetailPage.tsx` — same bucketing + 4th summary box + `CollapsibleSection`.
- `frontend/src/components/scanner/ScanHistoryPage.tsx` — show skipped count on scan cards (subtract from Hold cell).
- `frontend/src/components/scanner/__tests__/signalBucket.test.ts` — **created**: unit tests for the shared helper.

> **NOT modified:** `frontend/src/components/dashboard/HistoryList.tsx` — investigated during review and found to render analysis runs (not scans), so it has no `skipped_count`/`direction_counts` to surface. See Task 9 for the rationale. Do not edit it.

**Test files touched:**
- `tests/backend/test_persistence_scanner.py` — add `skipped_count` tests for sync `list_scans`.
- `tests/backend/test_scanner_service.py` — add `_serialize`/`_serialize_db` `skipped_count` tests.

---

## Task 1: Backend — sync persistence `skipped_count` aggregate

The aggregate history views read scan summaries from `list_scans`, which currently returns a `direction_counts` map but no skipped count. Skipped rows have `direction = "hold"`, so they're invisibly counted as holds. Add a parallel `skipped_count` keyed off `signal_source = 'ta_prefilter'`.

**Files:**
- Modify: `backend/persistence.py` — `AnalysisDB.list_scans()` (~lines 1079–1109)
- Test: `tests/backend/test_persistence_scanner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/backend/test_persistence_scanner.py` (mirror the existing `test_list_scans_hydrates_direction_counts` at line 301). Note `insert_scan_result` already accepts a `signal_source` key:

```python
def test_list_scans_hydrates_skipped_count(db):
    s = _scan()
    db.insert_scan(s)
    db.insert_scan_result(s["scan_id"], {"ticker": "BTC", "score": 5, "status": "completed", "direction": "buy", "signal_source": "structured"})
    db.insert_scan_result(s["scan_id"], {"ticker": "ETH", "score": 0, "status": "completed", "direction": "hold", "signal_source": "ta_prefilter"})
    db.insert_scan_result(s["scan_id"], {"ticker": "SOL", "score": 0, "status": "completed", "direction": "hold", "signal_source": "ta_prefilter"})
    db.insert_scan_result(s["scan_id"], {"ticker": "XRP", "score": 0, "status": "completed", "direction": "hold", "signal_source": "structured"})
    scans = db.list_scans()
    assert len(scans) == 1
    assert scans[0].get("skipped_count") == 2
    # Raw direction_counts is unchanged: all three holds still counted as hold.
    assert scans[0]["direction_counts"].get("hold") == 3


def test_list_scans_skipped_count_zero_when_none(db):
    s = _scan()
    db.insert_scan(s)
    db.insert_scan_result(s["scan_id"], {"ticker": "BTC", "score": 5, "status": "completed", "direction": "buy", "signal_source": "structured"})
    scans = db.list_scans()
    assert scans[0].get("skipped_count") == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/backend/test_persistence_scanner.py::test_list_scans_hydrates_skipped_count tests/backend/test_persistence_scanner.py::test_list_scans_skipped_count_zero_when_none -v`
Expected: **FAIL** (`AssertionError` — `skipped_count` is `None` because the key is absent) — **but only when a live test database is reachable.** This module calls `pytest.skip(..., allow_module_level=True)` at import time if PostgreSQL is unavailable (`_ensure_test_db()`, test file lines 16–31), so with no DB the entire module **SKIPS** instead of failing. Ensure a test DB is configured (`TEST_DATABASE_URL`, default `postgresql://postgres:...@localhost:5432/tradingagents_test`) before relying on the red-green signal. If you see `SKIPPED`, start/point-to a Postgres instance and re-run.

- [ ] **Step 3: Implement the aggregate in sync `list_scans`**

In `backend/persistence.py`, `list_scans()` currently runs one grouped query and hydrates `direction_counts` (lines ~1093–1105). Add a second query for the skipped count and attach `skipped_count` to each scan. Replace the block from the `cur.execute("SELECT scan_id, direction, COUNT(*) ...` call through the `for scan in scans:` loop with:

```python
                cur.execute(
                    "SELECT scan_id, direction, COUNT(*) as cnt "
                    "FROM scan_results WHERE scan_id = ANY(%s) "
                    "GROUP BY scan_id, direction",
                    (scan_ids,),
                )
                counts = cur.fetchall()
                counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
                for row in counts:
                    counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
                cur.execute(
                    "SELECT scan_id, COUNT(*) as cnt "
                    "FROM scan_results "
                    "WHERE scan_id = ANY(%s) AND signal_source = 'ta_prefilter' "
                    "GROUP BY scan_id",
                    (scan_ids,),
                )
                skipped_rows = cur.fetchall()
                skipped_by_scan: Dict[str, int] = {row["scan_id"]: row["cnt"] for row in skipped_rows}
                for scan in scans:
                    scan["results"] = []
                    scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
                    scan["skipped_count"] = skipped_by_scan.get(scan["scan_id"], 0)
```

(The `cur` here is a `RealDictCursor`, so rows are dict-accessible — consistent with the existing code.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/backend/test_persistence_scanner.py -k "skipped_count or direction_counts" -v`
Expected: PASS — new skipped tests pass and the existing `test_list_scans_hydrates_direction_counts` still passes (raw counts unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/persistence.py tests/backend/test_persistence_scanner.py
git commit -m "feat(scanner): add skipped_count to sync list_scans aggregate"
```

---

## Task 2: Backend — async persistence `skipped_count` aggregate

`AsyncAnalysisDB.list_scans()` is the production read path (asyncpg). It must mirror Task 1 so live scans loaded from the DB carry `skipped_count`. asyncpg uses `$1` placeholders and `Record` objects (dict-style access by key).

**Files:**
- Modify: `backend/async_persistence.py` — `AsyncAnalysisDB.list_scans()` (~lines 1934–1956)

- [ ] **Step 1: Implement the aggregate in async `list_scans`**

In `backend/async_persistence.py`, replace the block from the existing
`counts = await self.pool.fetch("SELECT scan_id, direction, COUNT(*) ...` call
through the `for scan in scans:` loop (lines ~1944–1955) with:

```python
        counts = await self.pool.fetch(
            "SELECT scan_id, direction, COUNT(*) as cnt "
            "FROM scan_results WHERE scan_id = ANY($1) "
            "GROUP BY scan_id, direction",
            scan_ids,
        )
        counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
        for row in counts:
            counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
        skipped_rows = await self.pool.fetch(
            "SELECT scan_id, COUNT(*) as cnt "
            "FROM scan_results "
            "WHERE scan_id = ANY($1) AND signal_source = 'ta_prefilter' "
            "GROUP BY scan_id",
            scan_ids,
        )
        skipped_by_scan: Dict[str, int] = {row["scan_id"]: row["cnt"] for row in skipped_rows}
        for scan in scans:
            scan["results"] = []
            scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
            scan["skipped_count"] = skipped_by_scan.get(scan["scan_id"], 0)
        return scans
```

- [ ] **Step 2: Verify the existing async suite still imports/collects cleanly**

Run: `python -m pytest tests/backend/test_analysis_service.py -q --co`
Expected: collection succeeds (no syntax/import error in `async_persistence.py`). If a live PostgreSQL is configured, the module's DB-backed tests run; otherwise they skip. The behavioral assertion for `skipped_count` is covered by the serializer test in Task 3 (the in-memory + DB-passthrough path that actually feeds the frontend).

- [ ] **Step 3: Commit**

```bash
git add backend/async_persistence.py
git commit -m "feat(scanner): add skipped_count to async list_scans aggregate"
```

---

## Task 3: Backend — serializers expose `skipped_count`

`scanner_service.list_scans()` merges in-memory scans (`_serialize`) with DB scans (`_serialize_db`). Both serializers build the dict the router returns to the frontend, so both must surface `skipped_count` — `_serialize` computes it from the in-memory `results`, `_serialize_db` passes through the value the persistence layer attached in Tasks 1–2.

**Files:**
- Modify: `backend/services/scanner_service.py` — `_serialize()` (~lines 796–828), `_serialize_db()` (~lines 830–861)
- Test: `tests/backend/test_scanner_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/backend/test_scanner_service.py` (the helpers `_make_scanner` / `ScannerService` are already imported at the top of the file):

```python
class TestSerializeSkippedCount:
    def test_serialize_counts_ta_prefilter_results(self):
        svc, _ = _make_scanner()
        scan = {
            "scan_id": "s1", "status": "completed", "total": 3, "completed": 3,
            "failed": 0, "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "started_at": "2026-06-08T00:00:00Z", "completed_at": "2026-06-08T00:01:00Z",
            "config": {},
            "results": [
                {"ticker": "BTC", "direction": "buy", "score": 5, "signal_source": "structured"},
                {"ticker": "ETH", "direction": "hold", "score": 0, "signal_source": "ta_prefilter"},
                {"ticker": "SOL", "direction": "hold", "score": 0, "signal_source": "ta_prefilter"},
            ],
        }
        out = svc._serialize(scan)
        assert out["skipped_count"] == 2

    def test_serialize_skipped_count_zero(self):
        svc, _ = _make_scanner()
        scan = {
            "scan_id": "s2", "status": "completed", "total": 1, "completed": 1,
            "failed": 0, "current_batch": 0, "total_batches": 0, "current_tickers": [],
            "started_at": "2026-06-08T00:00:00Z", "completed_at": None, "config": {},
            "results": [{"ticker": "BTC", "direction": "buy", "score": 5, "signal_source": "structured"}],
        }
        assert svc._serialize(scan)["skipped_count"] == 0

    def test_serialize_db_passes_through_skipped_count(self):
        svc, _ = _make_scanner()
        db_scan = {
            "scan_id": "s3", "status": "completed", "total": 2, "completed": 2,
            "failed": 0, "started_at": "2026-06-08T00:00:00Z", "completed_at": None,
            "config": {}, "results": [], "direction_counts": {"hold": 2}, "skipped_count": 2,
        }
        assert svc._serialize_db(db_scan)["skipped_count"] == 2

    def test_serialize_db_defaults_skipped_count_to_zero(self):
        svc, _ = _make_scanner()
        db_scan = {
            "scan_id": "s4", "status": "completed", "total": 0, "completed": 0,
            "failed": 0, "started_at": "2026-06-08T00:00:00Z", "completed_at": None,
            "config": {}, "results": [], "direction_counts": {},
        }
        assert svc._serialize_db(db_scan)["skipped_count"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/backend/test_scanner_service.py::TestSerializeSkippedCount -v`
Expected: FAIL with `KeyError: 'skipped_count'` (the serialized dict has no such key yet).

- [ ] **Step 3: Add `skipped_count` to `_serialize`**

In `backend/services/scanner_service.py`, `_serialize()` already iterates `results` to build `counts`. Add a skipped tally in that same loop and include it in the returned dict. Change the counts loop (lines ~799–802) to also count skipped:

```python
        counts: Dict[str, int] = {}
        skipped_count = 0
        for r in results:
            d = r.get("direction", "unknown")
            counts[d] = counts.get(d, 0) + 1
            if r.get("signal_source") == "ta_prefilter":
                skipped_count += 1
```

Then add one line to the returned dict (next to `"direction_counts": counts,` at line ~814):

```python
            "direction_counts": counts,
            "skipped_count": skipped_count,
```

- [ ] **Step 4: Add `skipped_count` to `_serialize_db`**

In the same file, `_serialize_db()` returns a dict built from the DB scan. Add one line next to its `"direction_counts": scan.get("direction_counts", {}),` (line ~847):

```python
            "direction_counts": scan.get("direction_counts", {}),
            "skipped_count": scan.get("skipped_count", 0),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/backend/test_scanner_service.py::TestSerializeSkippedCount -v`
Expected: PASS (all four).

- [ ] **Step 6: Commit**

```bash
git add backend/services/scanner_service.py tests/backend/test_scanner_service.py
git commit -m "feat(scanner): surface skipped_count in scan serializers"
```

---

## Task 4: Frontend — types + shared `signalBucket` helper

The detail views, the filter, and (later) the aggregate views all need consistent bucketing. Introduce one helper as the single source of truth, plus declare the two API fields that already arrive in the JSON but aren't typed yet.

**Files:**
- Modify: `frontend/src/api/client.ts` — `ScanResultItem` (~lines 355–363), `ScanStatus` (~lines 384–408)
- Modify: `frontend/src/components/scanner/ScanResultFilters.tsx` (imports `ScanResultItem` at line 7)
- Test (create): `frontend/src/components/scanner/__tests__/signalBucket.test.ts`

- [ ] **Step 1: Add the optional API fields**

In `frontend/src/api/client.ts`, add `signal_source` to `ScanResultItem`:

```ts
export interface ScanResultItem {
  ticker: string;
  run_id: string | null;
  status: string;
  direction: string;
  confidence: string;
  score: number;
  decision_summary: string;
  signal_source?: string;
}
```

And add `skipped_count` to `ScanStatus` (next to `direction_counts?` at line ~394):

```ts
  direction_counts?: Record<string, number>;
  skipped_count?: number;
```

- [ ] **Step 2: Write the failing test for `signalBucket`**

Create `frontend/src/components/scanner/__tests__/signalBucket.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { signalBucket } from "../ScanResultFilters";
import type { ScanResultItem } from "@/api/client";

function row(partial: Partial<ScanResultItem>): ScanResultItem {
  return {
    ticker: "X", run_id: null, status: "completed",
    direction: "hold", confidence: "none", score: 0, decision_summary: "",
    ...partial,
  };
}

describe("signalBucket", () => {
  it("classifies ta_prefilter rows as skipped even when direction is hold", () => {
    expect(signalBucket(row({ direction: "hold", signal_source: "ta_prefilter" }))).toBe("skipped");
  });

  it("classifies a real hold (non-prefilter) as hold", () => {
    expect(signalBucket(row({ direction: "hold", signal_source: "structured" }))).toBe("hold");
  });

  it("treats unknown/missing direction as hold", () => {
    expect(signalBucket(row({ direction: "unknown", signal_source: "regex_fallback" }))).toBe("hold");
    expect(signalBucket(row({ direction: "", signal_source: undefined }))).toBe("hold");
  });

  it("passes buy and sell through unchanged", () => {
    expect(signalBucket(row({ direction: "buy", signal_source: "structured" }))).toBe("buy");
    expect(signalBucket(row({ direction: "sell", signal_source: "structured" }))).toBe("sell");
  });

  it("never returns buy/sell for a ta_prefilter row", () => {
    expect(signalBucket(row({ direction: "buy", signal_source: "ta_prefilter" }))).toBe("skipped");
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/signalBucket.test.ts`
Expected: FAIL — `signalBucket` is not exported from `ScanResultFilters` (`undefined is not a function` / import error).

- [ ] **Step 4: Implement and export `signalBucket`**

In `frontend/src/components/scanner/ScanResultFilters.tsx`, add the helper near the top (after the `import` of `ScanResultItem`, before `useScanFilters`):

```ts
export type SignalBucket = "buy" | "sell" | "hold" | "skipped";

export function signalBucket(r: ScanResultItem): SignalBucket {
  if (r.signal_source === "ta_prefilter") return "skipped";
  if (r.direction === "buy" || r.direction === "sell") return r.direction;
  return "hold"; // hold, unknown, or missing
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/signalBucket.test.ts`
Expected: PASS (all five).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/scanner/ScanResultFilters.tsx frontend/src/components/scanner/__tests__/signalBucket.test.ts
git commit -m "feat(scanner): add signalBucket helper and skipped API types"
```

---

## Task 5: Frontend — "Skipped" filter chip + bucket-aware predicate

The shared filter currently maps a row to a signal value purely from `direction` (`hold`/`unknown` → `"hold"`). Route it through `signalBucket` so "Hold" excludes skipped and a new "Skipped" chip isolates them. This task has no separate unit test (covered by `signalBucket` tests in Task 4 + the manual verification step); it's a mechanical wiring change verified by typecheck + existing filter behavior.

**Files:**
- Modify: `frontend/src/components/scanner/ScanResultFilters.tsx` — predicate (~lines 119–124), Signal `FilterSection` (~lines 232–236)

- [ ] **Step 1: Route the filter predicate through `signalBucket`**

In `useScanFilters`, the current signal filter block is:

```ts
    if (filters.signal.size > 0) {
      items = items.filter((r) => {
        const dir = r.direction === "hold" || r.direction === "unknown" ? "hold" : r.direction;
        return filters.signal.has(dir);
      });
    }
```

Replace it with:

```ts
    if (filters.signal.size > 0) {
      items = items.filter((r) => filters.signal.has(signalBucket(r)));
    }
```

(`signalBucket` is defined in the same file from Task 4 — no import needed.)

- [ ] **Step 2: Add a `neutral` color to `FILTER_NEU_CLASSES`**

The Skipped chip should render in a muted/slate tone (spec §6.5), distinct from Hold's amber. `FilterChip`'s `color` prop defaults to `"accent"` (line 25), and `FILTER_NEU_CLASSES` (lines ~15–20) only defines `accent`/`success`/`danger`/`warning` — so a chip with no `color` renders **accent-colored when active**, not muted. Add a `neutral` key. The current map is:

```ts
const FILTER_NEU_CLASSES = {
  accent: "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))]",
  success: "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]",
  danger: "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]",
  warning: "bg-[color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-base))] text-[var(--neu-warning)] border-[color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))]",
} as const;
```

Add the `neutral` line:

```ts
  warning: "bg-[color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-base))] text-[var(--neu-warning)] border-[color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))]",
  neutral: "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)]",
} as const;
```

(`color?: keyof typeof FILTER_NEU_CLASSES` on `FilterChip` automatically accepts the new key — no prop-type edit needed.)

- [ ] **Step 3: Add the "Skipped" chip to the Signal filter group**

The current Signal `FilterSection` (~line 232) has Buy/Sell/Hold chips. Add a Skipped chip after Hold, with the new `neutral` color:

```tsx
            <FilterSection label="Signal">
              <FilterChip label="Buy" active={filters.signal.has("buy")} color="success" onClick={() => update("signal", toggleSet(filters.signal, "buy"))} />
              <FilterChip label="Sell" active={filters.signal.has("sell")} color="danger" onClick={() => update("signal", toggleSet(filters.signal, "sell"))} />
              <FilterChip label="Hold" active={filters.signal.has("hold")} color="warning" onClick={() => update("signal", toggleSet(filters.signal, "hold"))} />
              <FilterChip label="Skipped" active={filters.signal.has("skipped")} color="neutral" onClick={() => update("signal", toggleSet(filters.signal, "skipped"))} />
            </FilterSection>
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Run the scanner filter-related tests**

Run: `cd frontend && npx vitest run src/components/scanner`
Expected: PASS (existing scanner tests unaffected; `signalBucket` test passes).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/scanner/ScanResultFilters.tsx
git commit -m "feat(scanner): add Skipped filter chip backed by signalBucket"
```

---

## Task 6: Frontend — live Market Scanner card + section (`ScannerPage.tsx`)

This is the page in the screenshot. Add the 4th "TA Skipped" metric card and a collapsible Skipped results section, and exclude skipped rows from the Hold bucket. `ScannerMetricCard` already supports a `neutral` tone.

**Files:**
- Modify: `frontend/src/components/scanner/ScannerPage.tsx` — bucketing (~lines 527–529), stats row (~lines 1146–1150), hold section (~lines 1292–1319)

- [ ] **Step 1: Import `signalBucket` and revise bucketing**

At the existing import of the filters module (line 14: `import { useScanFilters, ScanResultFiltersBar } from "@/components/scanner/ScanResultFilters";`), add `signalBucket`:

```ts
import { useScanFilters, ScanResultFiltersBar, signalBucket } from "@/components/scanner/ScanResultFilters";
```

Replace the three bucket lines (~527–529):

```ts
  const buyResults = filteredResults.filter((r) => r.direction === "buy").sort((a, b) => b.score - a.score);
  const sellResults = filteredResults.filter((r) => r.direction === "sell").sort((a, b) => a.score - b.score);
  const holdResults = filteredResults.filter((r) => r.direction === "hold" || r.direction === "unknown");
```

with:

```ts
  const buyResults = filteredResults.filter((r) => signalBucket(r) === "buy").sort((a, b) => b.score - a.score);
  const sellResults = filteredResults.filter((r) => signalBucket(r) === "sell").sort((a, b) => a.score - b.score);
  const holdResults = filteredResults.filter((r) => signalBucket(r) === "hold");
  const skippedResults = filteredResults.filter((r) => signalBucket(r) === "skipped");
```

- [ ] **Step 2: Add the 4th metric card**

The stats row (~lines 1146–1149) is `<div className="grid grid-cols-2 gap-3 sm:grid-cols-3">` with three `ScannerMetricCard`s. Widen the grid and add the conditional Skipped card:

```tsx
            {/* Stats row */}
            <div className={cn("grid grid-cols-2 gap-3", skippedResults.length > 0 ? "sm:grid-cols-4" : "sm:grid-cols-3")}>
              <ScannerMetricCard tone="success" value={buyResults.length} label="Buy signals" />
              <ScannerMetricCard tone="danger" value={sellResults.length} label="Sell signals" />
              <ScannerMetricCard tone="warning" value={holdResults.length} label="Hold / neutral" />
              {skippedResults.length > 0 && (
                <ScannerMetricCard tone="neutral" value={skippedResults.length} label="TA skipped" />
              )}
            </div>
```

(`cn` is already imported in this file.)

- [ ] **Step 3: Add the collapsible Skipped section**

After the Hold / Unknown block (which ends at ~line 1319 with `)}` before the closing `</>`), add a matching block using the same `MobileCollapse` + `CollapsibleResultCard` pattern with a slate color:

```tsx
          {/* TA Skipped */}
          {skippedResults.length > 0 && (
            <>
              <MobileCollapse
                storageKey="scanner:collapse:skipped"
                defaultOpen={false}
                className="md:hidden"
                title={
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <span className="size-2 rounded-full bg-slate-400 shrink-0" />
                    <span className="text-slate-500 dark:text-slate-300">TA Skipped</span>
                    <span className="text-xs font-normal text-muted-foreground">({skippedResults.length})</span>
                  </span>
                }
              >
                <ResultsTable results={skippedResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </MobileCollapse>
              <CollapsibleResultCard
                className="hidden md:block"
                storageKey="scanner:collapse:skipped:desktop"
                defaultOpen={false}
                color="slate"
                title={`TA Skipped (${skippedResults.length})`}
              >
                <ResultsTable results={skippedResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
              </CollapsibleResultCard>
            </>
          )}
```

- [ ] **Step 4: Add a `slate` entry to `COLOR_MAP`**

`CollapsibleResultCard`'s `color` prop is typed `string` (no union to extend), and `COLOR_MAP` (line ~1336) already falls back to a neutral tone for unknown keys (`COLOR_MAP[color] ?? { dot: "bg-muted-foreground/50", tone: "neutral" }`). Add an explicit `slate` entry so the dot color is intentional. `COLOR_MAP` currently is:

```ts
const COLOR_MAP: Record<string, { dot: string; tone: keyof typeof TONE_PILL_STYLES }> = {
  emerald: { dot: "bg-[var(--neu-success)]", tone: "success" },
  red: { dot: "bg-[var(--neu-danger)]", tone: "danger" },
  amber: { dot: "bg-[var(--neu-warning)]", tone: "warning" },
};
```

Add the `slate` line:

```ts
const COLOR_MAP: Record<string, { dot: string; tone: keyof typeof TONE_PILL_STYLES }> = {
  emerald: { dot: "bg-[var(--neu-success)]", tone: "success" },
  red: { dot: "bg-[var(--neu-danger)]", tone: "danger" },
  amber: { dot: "bg-[var(--neu-warning)]", tone: "warning" },
  slate: { dot: "bg-slate-400", tone: "neutral" },
};
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/scanner/ScannerPage.tsx
git commit -m "feat(scanner): add TA Skipped card and section to live scanner"
```

---

## Task 7: Frontend — scan detail card + section (`ScanDetailPage.tsx`)

The scheduled/historical scan detail view. It receives the full `results[]`, so the same client-side bucketing applies. Its summary boxes and sections use simpler inline markup + a `CollapsibleSection` that takes a `dotColor: string`.

**Files:**
- Modify: `frontend/src/components/scanner/ScanDetailPage.tsx` — imports (line 9), bucketing (~lines 332–334), summary boxes (~lines 477–490), results sections (~lines 506–520)

- [ ] **Step 1: Import `signalBucket` and revise bucketing**

Update the import on line 9:

```ts
import { useScanFilters, ScanResultFiltersBar, signalBucket } from "@/components/scanner/ScanResultFilters";
```

Replace the bucket lines (~332–334):

```ts
  const buyResults = filteredResults.filter((r) => r.direction === "buy");
  const sellResults = filteredResults.filter((r) => r.direction === "sell");
  const holdResults = filteredResults.filter((r) => r.direction === "hold" || r.direction === "unknown" || !r.direction);
```

with:

```ts
  const buyResults = filteredResults.filter((r) => signalBucket(r) === "buy");
  const sellResults = filteredResults.filter((r) => signalBucket(r) === "sell");
  const holdResults = filteredResults.filter((r) => signalBucket(r) === "hold");
  const skippedResults = filteredResults.filter((r) => signalBucket(r) === "skipped");
```

- [ ] **Step 2: Widen the grid, fix the Hold box col-span, and add the 4th box**

The summary grid (~lines 477–490) is `<div className="grid grid-cols-2 sm:grid-cols-3 gap-3">`, and the Hold box (~line 486) carries `col-span-2 sm:col-span-1` to fill the orphaned 3rd slot of a 3-up grid on mobile. When a 4th (Skipped) box is added, that `col-span-2` would force Hold to span the full mobile row, pushing Skipped into an unbalanced orphaned cell. So the Hold col-span must become conditional.

First, replace the grid wrapper opening tag (line 477):

```tsx
        <div className={cn("grid grid-cols-2 gap-3", skippedResults.length > 0 ? "sm:grid-cols-4" : "sm:grid-cols-3")}>
```

Then replace the entire Hold / Neutral box (lines ~486–489) so its mobile col-span only applies in the 3-box case:

```tsx
          <div className={cn("rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 text-center border-none", skippedResults.length > 0 ? "" : "col-span-2 sm:col-span-1")}>
            <div className="text-2xl font-bold text-[var(--neu-warning)] leading-none">{holdResults.length}</div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] mt-2">Hold / Neutral</div>
          </div>
```

Then, immediately after that Hold box (before the grid's closing `</div>`), add the 4th box:

```tsx
          {skippedResults.length > 0 && (
            <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 text-center border-none">
              <div className="text-2xl font-bold text-[var(--neu-text-muted)] leading-none">{skippedResults.length}</div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)] mt-2">TA Skipped</div>
            </div>
          )}
```

Result: with no skipped, the grid is the original 3-up (Hold keeps `col-span-2 sm:col-span-1`). With skipped, the grid is `sm:grid-cols-4`, Hold drops `col-span-2`, and all four boxes wrap 2×2 on mobile and 4-up on `sm+`. (`cn` is already imported in this file — confirmed at line 8.)

- [ ] **Step 3: Add the Skipped `CollapsibleSection`**

After the Hold / Neutral section (~lines 516–520), add:

```tsx
      {skippedResults.length > 0 && (
        <CollapsibleSection title="TA Skipped" count={skippedResults.length} dotColor="bg-slate-400">
          <ResultsTable results={skippedResults} isCrypto={isCrypto} onTrade={handleTrade} tradedSymbols={tradedSymbols} />
        </CollapsibleSection>
      )}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/ScanDetailPage.tsx
git commit -m "feat(scanner): add TA Skipped card and section to scan detail"
```

---

## Task 8: Frontend — aggregate scan cards (`ScanHistoryPage.tsx`)

The history cards grid receives scan summaries with `direction_counts` + the new `skipped_count` (no rows). Currently the "Hold" cell shows `total - buy - sell`, which silently includes skipped. Surface skipped distinctly and de-skip the Hold cell.

**Files:**
- Modify: `frontend/src/components/scanner/ScanHistoryPage.tsx` — per-card derive (~line 244), signal metrics grid (~lines 361–375)

- [ ] **Step 1: Derive `skipped` per card**

In the `scans.map((scan) => { ... })` body (~lines 244–249), the current derives are:

```ts
            const dc = scan.direction_counts ?? {};
            const buy = dc.buy ?? 0;
            const sell = dc.sell ?? 0;
            const total = Object.values(dc).reduce((a, b) => a + b, 0);
```

Add a skipped derive and a de-skipped hold:

```ts
            const dc = scan.direction_counts ?? {};
            const buy = dc.buy ?? 0;
            const sell = dc.sell ?? 0;
            const total = Object.values(dc).reduce((a, b) => a + b, 0);
            const skipped = scan.skipped_count ?? 0;
            const hold = Math.max(0, total - buy - sell - skipped);
```

- [ ] **Step 2: Show skipped in the signal metrics grid**

The signal metrics grid (~lines 361–375) is a `grid grid-cols-3` with Buy / Sell / Hold cells, where Hold shows `{total - buy - sell}`. Update the Hold cell to use the de-skipped `hold`, and widen the grid to 4 columns with a Skipped cell when `skipped > 0`:

```tsx
                {/* Signal metrics */}
                <div className={cn("relative grid gap-2 px-4 pb-3.5", skipped > 0 ? "grid-cols-4" : "grid-cols-3")}>
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className={`text-base font-extrabold tabular-nums ${buy > 0 ? "text-[var(--neu-success)]" : "text-[var(--neu-text-muted)]/30"}`}>{buy}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Buy</div>
                  </div>
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className={`text-base font-extrabold tabular-nums ${sell > 0 ? "text-[var(--neu-danger)]" : "text-[var(--neu-text-muted)]/30"}`}>{sell}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Sell</div>
                  </div>
                  <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                    <div className="text-base font-extrabold tabular-nums text-[var(--neu-text-muted)]/60">{hold}</div>
                    <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Hold</div>
                  </div>
                  {skipped > 0 && (
                    <div className="rounded-xl bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border-none px-3 py-2.5 text-center">
                      <div className="text-base font-extrabold tabular-nums text-[var(--neu-text-muted)]/60">{skipped}</div>
                      <div className="text-[9px] text-[var(--neu-text-muted)] uppercase tracking-wider font-semibold mt-0.5">Skipped</div>
                    </div>
                  )}
                </div>
```

- [ ] **Step 3: Ensure `cn` is imported**

Run: `grep -n "import { cn }" frontend/src/components/scanner/ScanHistoryPage.tsx`
Expected: a match. If absent, add `import { cn } from "@/lib/utils";` to the imports. (The grid `className` now uses `cn`.)

- [ ] **Step 4: Typecheck + run the page's existing test**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/components/scanner/__tests__/ScanHistoryPage.test.tsx`
Expected: no type errors; the existing ScanHistoryPage test still passes (it mocks an empty scan list, so the new branch isn't exercised but must not break rendering).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/ScanHistoryPage.tsx
git commit -m "feat(scanner): show TA skipped count on history scan cards"
```

---

## Task 9: Dashboard `HistoryList.tsx` — DO NOT IMPLEMENT (out of scope)

**Decision: skip this component. No code change.** During plan review this was found to be a misdirection — the spec's §6.7 "optional polish" framing is misleading.

`frontend/src/components/dashboard/HistoryList.tsx` lists **analysis runs, not scans**. Evidence:
- It queries the analyses endpoint and uses the `["analyses"]` query key, with `allItems = data?.items` (~line 124) where each item is an analysis run keyed by `run_id` (~line 127).
- `buyCount`/`sellCount` are derived from per-run trade-score snapshots via `parseTradeCard(snap.reports)` (~lines 140–146, 315–333) — they are NOT scan `direction_counts`.
- These items have no `direction_counts`, no `signal_source`, and no `skipped_count`. `skipped_count` is a `ScanStatus` concept (scan summaries), which this component never handles.

Adding `const skippedCount = allItems.reduce((sum, i) => sum + ((i as { skipped_count?: number }).skipped_count ?? 0), 0)` would type-compile only because of the cast, and would **always sum to 0** — a permanently-zero stat that misleads users. That is worse than omitting it.

The TA-skipped feature is about *scan* results. The scan-facing surfaces (live scanner, scan detail, scan history cards) are fully covered by Tasks 6–8. Requirements R1–R7 are satisfied without touching `HistoryList`.

- [ ] **Step 1: Confirm and move on**

No file change. Verify the premise still holds (in case the component was refactored):

Run: `grep -n "listAnalyses\|listScans\|data?.items\|run_id\|skipped_count\|direction_counts" frontend/src/components/dashboard/HistoryList.tsx`
Expected: matches for analyses/`run_id`-style access and NO `skipped_count`/`direction_counts`/`listScans`. If that holds, leave the file untouched and proceed to Task 10. (If the component has since been changed to render scan summaries typed as `ScanStatus`, only then revisit — but that is not the case today.)

---

## Task 10: Full validation + manual verification

Run the complete validation gates (per project rules: tests, typecheck, build must all pass before claiming completion) and verify the feature end-to-end against a real scan.

**Files:** none (verification only)

- [ ] **Step 1: Backend test suite**

Run: `python -m pytest tests/backend/test_persistence_scanner.py tests/backend/test_scanner_service.py -v`
Expected: PASS, including the new `skipped_count` tests and all pre-existing scanner tests (no regressions). Note: `test_persistence_scanner.py` requires a live PostgreSQL (`TEST_DATABASE_URL`) and SKIPs at module level without one — a SKIP is not a pass, so ensure a DB is configured to actually exercise the persistence tests. `test_scanner_service.py` (the `_serialize`/`_serialize_db` tests) needs no DB and must pass unconditionally.

- [ ] **Step 2: Frontend tests**

Run: `cd frontend && npx vitest run src/components/scanner`
Expected: PASS — `signalBucket.test.ts` and existing scanner tests green.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Production build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual verification against a real crypto scan with the prefilter on**

1. Start the backend (`python -m uvicorn backend.main:app --reload`) and frontend (`cd frontend && npm run dev`).
2. On the Market Scanner page, enable the TA Pre-Filter with a threshold high enough to skip some symbols (e.g. 50), and run a crypto scan.
3. Verify, as results stream in:
   - A **TA Skipped** card appears (4th card) once at least one symbol is skipped, and shows a non-zero count.
   - The **Hold / neutral** card no longer includes skipped symbols (cross-check: buy + sell + hold + skipped == completed).
   - A **TA Skipped** collapsible section lists the skipped symbols, each with its reason text (e.g. "TA score 22/50 < threshold 50 …").
   - In the filter bar, opening Filters shows a **Skipped** chip; selecting it shows only skipped rows and the `N of M` badge updates; selecting **Hold** excludes skipped rows.
4. Open the same scan from **Scan History**: the detail page shows the same 4th box, section, and filter behavior.
5. On the **Scan History** cards grid, the scan's card shows a **Skipped** metric and the Hold cell excludes skipped.
6. Run a scan with the prefilter **off** (or a stock scan): confirm no Skipped card/section/chip-effect appears and the layout is the original 3-up.

- [ ] **Step 6: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(scanner): verify TA skipped visibility end-to-end"
```

(Skip if no changes were required during verification.)

---

## Notes for the Implementer

- **No DB migration:** `scan_results.signal_source` already exists (default `'unknown'`; skipped rows already written as `'ta_prefilter'`). Do not add a migration.
- **`direction_counts` stays raw:** never subtract skipped at the API layer — the subtraction happens only in the aggregate-view display code (Task 8). Other consumers rely on the raw grouping.
- **Single source of truth:** all bucketing routes through `signalBucket()` (Task 4). If you find yourself re-deriving "is this skipped?" inline, use the helper instead.
- **`signalBucket` precedence is intentional:** it checks `signal_source === "ta_prefilter"` *before* direction, so a row's skipped status wins over buy/sell. Today every skipped row is persisted with `direction = "hold"` (see spec §5), so this never reclassifies a real buy/sell. But if a future change ever writes a `ta_prefilter` row with `direction = "buy"/"sell"`, `signalBucket` will classify it as `"skipped"` and it will NOT appear in the Buy/Sell buckets — by design (skipped means "never analyzed", so it has no real signal). The `signalBucket` test explicitly locks this precedence in.
- **Fail-open safety:** prefilter errors/insufficient-data proceed to LLM with a non-`ta_prefilter` `signal_source`, so they correctly never land in the skipped bucket — no special handling needed.
- **`HistoryList.tsx` is deliberately untouched** (Task 9): it renders analysis runs, not scans, and has no skipped concept. Do not add a permanently-zero stat there.
- **Line-number anchors will drift:** every step also quotes the exact code block to find/replace, so locate by the quoted text, not the `~line` hint.








