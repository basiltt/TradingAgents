# Scan Forms Tabbed Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the Market Scanner page form, its running/results view, and the Scheduled Scan dialog form into consistent by-purpose tabs, preserving all existing form behavior.

**Architecture:** A shared, data-only `scanTabs.ts` (tab ids/order/labels) plus a `useTabPersistence` hook (mount-read from localStorage, interaction-driven save — generalizing the backtest tab-persistence pattern) drive three independent `<Tabs>` surfaces. Each form keeps its own per-field `useState`; tab panels are `keepMounted` so no input/sub-component unmounts on switch. This is a JSX re-parenting change — no field logic, submit handlers, validation, or `AutoTradeSection` internals change. The only new behavioral logic is the hook and a one-shot Scanner results auto-switch.

**Tech Stack:** React 19 + TypeScript (strict), `@base-ui/react` Tabs (v1.4.1, `keepMounted` supported) via `@/components/ui/tabs`, Tailwind + neumorphism tokens, Vitest + Testing Library, per-field `useState` + localStorage (no react-hook-form/zod in these forms).

**Spec:** `docs/superpowers/specs/2026-06-13-scan-forms-tabbed-redesign-design.md`

---

## Key Constraints (read before any task)

1. **Behavior preservation is the contract.** Every field's exact `value`/`onChange` binding moves unchanged. Submit/start/save handlers, the cool-off launch gate (`cooloffGateValid` / `collectCooloffGateErrors`), and `<AutoTradeSection>` are untouched. Move JSX; do not rewrite fields.
2. **`keepMounted` on EVERY tab panel** (all three tab sets, including the Auto-trade tab). Not for input-value retention (inputs are parent-`useState`-controlled) but to preserve focus/typing, `AutoTradeSection`'s internal `useQuery`/per-card state, and the backend-URL endpoint dropdown.
3. **`showEndpoints` is NOT a collapse flag** — it drives the backend-URL endpoint-picker dropdown. KEEP it (and `endpoints`, the click-outside ref effect, `selectEndpoint`, the dropdown JSX, its `handleOpenChange` reset). Only the three section-collapse flags are removed.
4. **The Scheduled dialog never unmounts** (`<ScheduleFormDialog open={dialogOpen} …>` is rendered unconditionally). Forcing the Schedule tab on open-for-create uses an `open`+`editingId` effect, not a mount read. `editingId == null` ⇒ create.
5. **Run commands from `frontend/`.** Test: `npm run test`. Type-check: `npx tsc --noEmit`. Build: `npm run build`. Lint: `npm run lint`.
6. **Chunk large edits** (~150 lines max per tool call). Moving JSX is large — split each form's move across multiple edits; never reduce existing content while moving it.

---

## File Structure

```
frontend/src/components/scanner/
  form-tabs/
    scanTabs.ts                 # CREATE — tab id unions, ordered arrays, label maps (pure data, no React)
    useTabPersistence.ts        # CREATE — hook: [tab, setTab] = useTabPersistence(key, order, fallback?)
  ScannerPage.tsx               # MODIFY — wrap config sections in 3 tabs; wrap results in 3 tabs;
                                #   add results auto-switch; remove showWorkflow/showLlm collapse flags
  ScheduledScansPage.tsx        # MODIFY — wrap dialog sections in 5 tabs; force Schedule tab on create;
                                #   remove showScanConfig/showWorkflowSettings/showLlmSettings + CollapsibleSection
  __tests__/
    useTabPersistence.test.ts   # CREATE — hook unit tests
    scanTabs.test.ts            # CREATE — tab-data invariants
    ScannerPageTabs.test.tsx    # CREATE — Scanner config + results tab render/switch/persist
    ScheduledFormTabs.test.tsx  # CREATE — dialog tab render/switch + force-Schedule-on-create
```

**Responsibility boundaries:**
- `scanTabs.ts` — the single source of truth for tab ids, order, and labels. No React, no DOM.
- `useTabPersistence.ts` — the only place that touches localStorage for tab state. Consumed by all three surfaces with different keys.
- The two form files — own their `useState` and render `<Tabs>` with existing sections moved into `<TabsContent>` panels. No tab logic duplicated beyond the `useTabPersistence` call + the `<TabsList>` map + (Scanner) the auto-switch effect + (Scheduled) the force-Schedule effect.

---

## Task 1: `scanTabs.ts` — tab id/order/label data

Pure data, the single source of truth for all three tab sets. Built test-first so the order/label invariants are locked.

**Files:**
- Create: `frontend/src/components/scanner/form-tabs/scanTabs.ts`
- Test: `frontend/src/components/scanner/__tests__/scanTabs.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import {
  SCANNER_CONFIG_TABS, SCANNER_RESULT_TABS, SCHEDULED_TABS,
  SCANNER_CONFIG_LABELS, SCANNER_RESULT_LABELS, SCHEDULED_LABELS,
} from "../form-tabs/scanTabs";

describe("scanTabs", () => {
  it("orders the scanner config tabs", () => {
    expect(SCANNER_CONFIG_TABS).toEqual(["scan", "analysis", "models"]);
  });
  it("orders the scanner result tabs", () => {
    expect(SCANNER_RESULT_TABS).toEqual(["results", "progress", "config"]);
  });
  it("orders the scheduled dialog tabs", () => {
    expect(SCHEDULED_TABS).toEqual(["schedule", "scan", "analysis", "models", "autotrade"]);
  });
  it("labels every id in every set (no missing/empty labels)", () => {
    for (const id of SCANNER_CONFIG_TABS) expect(SCANNER_CONFIG_LABELS[id]).toBeTruthy();
    for (const id of SCANNER_RESULT_TABS) expect(SCANNER_RESULT_LABELS[id]).toBeTruthy();
    for (const id of SCHEDULED_TABS) expect(SCHEDULED_LABELS[id]).toBeTruthy();
  });
  it("uses the same 'Models & Connection' label in both config forms", () => {
    expect(SCANNER_CONFIG_LABELS.models).toBe("Models & Connection");
    expect(SCHEDULED_LABELS.models).toBe("Models & Connection");
  });
  it("uses identical Scan/Analysis labels across both forms (family consistency)", () => {
    expect(SCHEDULED_LABELS.scan).toBe(SCANNER_CONFIG_LABELS.scan);
    expect(SCHEDULED_LABELS.analysis).toBe(SCANNER_CONFIG_LABELS.analysis);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- scanTabs`
Expected: FAIL with "Cannot find module '../form-tabs/scanTabs'".

- [ ] **Step 3: Implement `scanTabs.ts`**

```ts
// Tab ids are kebab-case lowercase; labels are human-readable. Single source of
// truth for the order + labels of every tabbed surface in the scanner forms.

export type ScannerConfigTab = "scan" | "analysis" | "models";
export type ScannerResultTab = "results" | "progress" | "config";
export type ScheduledTab = "schedule" | "scan" | "analysis" | "models" | "autotrade";

export const SCANNER_CONFIG_TABS: ScannerConfigTab[] = ["scan", "analysis", "models"];
export const SCANNER_RESULT_TABS: ScannerResultTab[] = ["results", "progress", "config"];
export const SCHEDULED_TABS: ScheduledTab[] = ["schedule", "scan", "analysis", "models", "autotrade"];

export const SCANNER_CONFIG_LABELS: Record<ScannerConfigTab, string> = {
  scan: "Scan",
  analysis: "Analysis",
  models: "Models & Connection",
};

export const SCANNER_RESULT_LABELS: Record<ScannerResultTab, string> = {
  results: "Results",
  progress: "Progress",
  config: "Config",
};

export const SCHEDULED_LABELS: Record<ScheduledTab, string> = {
  schedule: "Schedule",
  scan: "Scan",            // same as SCANNER_CONFIG_LABELS.scan
  analysis: "Analysis",    // same as SCANNER_CONFIG_LABELS.analysis
  models: "Models & Connection",
  autotrade: "Auto-trade",
};
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -- scanTabs`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/form-tabs/scanTabs.ts frontend/src/components/scanner/__tests__/scanTabs.test.ts
git commit -m "feat(scanner): add scanTabs tab id/order/label data"
```

---

## Task 2: `useTabPersistence` hook

A localStorage-backed tab-state hook generalizing the backtest pattern: mount-read with fallback, interaction-driven save on the same call (never a mount write), best-effort.

**Files:**
- Create: `frontend/src/components/scanner/form-tabs/useTabPersistence.ts`
- Test: `frontend/src/components/scanner/__tests__/useTabPersistence.test.ts`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTabPersistence } from "../form-tabs/useTabPersistence";

const KEY = "test_tab_key";
const ORDER = ["a", "b", "c"] as const;

describe("useTabPersistence", () => {
  beforeEach(() => localStorage.clear());

  it("falls back to the first tab when nothing is stored", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a");
  });

  it("uses an explicit fallback when provided and nothing is stored", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER, "b"));
    expect(result.current[0]).toBe("b");
  });

  it("restores a valid stored id on mount", () => {
    localStorage.setItem(KEY, "c");
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("c");
  });

  it("ignores a stored id that is not in the order (falls back)", () => {
    localStorage.setItem(KEY, "zzz");
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a");
  });

  it("saves to localStorage on setTab", () => {
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    act(() => result.current[1]("b"));
    expect(result.current[0]).toBe("b");
    expect(localStorage.getItem(KEY)).toBe("b");
  });

  it("does NOT write to localStorage on mount", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    renderHook(() => useTabPersistence(KEY, ORDER));
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("degrades gracefully when localStorage.getItem throws", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useTabPersistence(KEY, ORDER));
    expect(result.current[0]).toBe("a"); // falls back, no throw
    getItem.mockRestore();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- useTabPersistence`
Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `useTabPersistence.ts`**

```tsx
import * as React from "react";

/**
 * localStorage-backed tab state. Mirrors the backtest tab-persistence behavior:
 * read the stored id once on mount (fall back to `fallback ?? order[0]` when it is
 * missing OR not in `order`); `setTab(next)` updates state AND writes localStorage
 * in the SAME call — interaction-driven, never a mount-time write. Best-effort: any
 * storage read/write failure degrades to the fallback / a no-op and never throws.
 *
 * The setter may also be called imperatively to FORCE a tab (e.g. the dialog forcing
 * "schedule" on open-for-create, or the results view auto-switching on completion);
 * those calls persist too, which is intended.
 */
export function useTabPersistence<T extends string>(
  storageKey: string,
  order: readonly T[],
  fallback?: T,
): [T, (next: T) => void] {
  const initial = React.useMemo<T>(() => {
    const fb = fallback ?? order[0];
    try {
      const stored = localStorage.getItem(storageKey);
      return stored && (order as readonly string[]).includes(stored) ? (stored as T) : fb;
    } catch {
      return fb;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time read only
  }, []);

  const [tab, setTab] = React.useState<T>(initial);

  const setAndPersist = React.useCallback(
    (next: T) => {
      setTab(next);
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        /* storage unavailable — best-effort, ignore */
      }
    },
    [storageKey],
  );

  return [tab, setAndPersist];
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -- useTabPersistence`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/form-tabs/useTabPersistence.ts frontend/src/components/scanner/__tests__/useTabPersistence.test.ts
git commit -m "feat(scanner): add useTabPersistence hook"
```

---

## Task 3: Market Scanner — config form into 3 tabs

Wrap the existing config sections (shown when `!activeScanId`) in a `<Tabs>` with Scan / Analysis / Models & Connection panels. Pure JSX re-parenting + removing the two collapse toggles. No field bindings change.

**Files:**
- Modify: `frontend/src/components/scanner/ScannerPage.tsx`

> **Section inventory (identify by label, not line number — they will shift):**
> - **Scan panel** = the top grid section (Analysis date / Kline interval / LLM provider) + the Workflow-mode segmented control + Smart pre-screen toggle/threshold + the Analyst-team chips section. These are the always-visible sections at the top of the config today.
> - **Analysis panel** = the body currently inside the `showWorkflow` collapsible ("Workflow settings"): Research depth, Output language, Max debate rounds, Max risk rounds, Max recursion limit, Max parallel analyses, the **Checkpointing toggle** (`checkpointEnabled`), the **Prompt-cache toggle** (`promptCacheEnabled`) — PLUS the `<AgentModelOverrides>` block currently rendered after the LLM collapsible (move it into this panel).
> - **Models panel** = the body currently inside the `showLlm` collapsible ("LLM and proxy settings"): Backend URL/proxy (incl. the endpoint dropdown), API key, Deep think model, Quick think model, LLM concurrency limit, Min spacing.

- [ ] **Step 1: Add imports + the persisted config-tab state**

At the top of `ScannerPage.tsx`, add:

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { SCANNER_CONFIG_TABS, SCANNER_CONFIG_LABELS } from "@/components/scanner/form-tabs/scanTabs";
import { useTabPersistence } from "@/components/scanner/form-tabs/useTabPersistence";
```

Inside the `ScannerPage` component body (near the other `useState`s, ~L337+), add:

```tsx
const [configTab, setConfigTab] = useTabPersistence(
  "tradingagents_scanner_config_tab", SCANNER_CONFIG_TABS,
);
```

- [ ] **Step 2: Remove the two collapse toggles' machinery**

Delete the `showWorkflow`/`showLlm` `useState` declarations (~L351-352) and the two `<button onClick={() => setShowWorkflow(...)}>` / `setShowLlm` collapse-header buttons that wrap the Workflow-settings and LLM-settings panels. Keep the panel BODIES (their inner `<div>` content) — those become the Analysis and Models tab panels. Do NOT remove `showEndpoints`, `endpoints`, the endpoint click-outside ref effect, `selectEndpoint`, or the endpoint dropdown JSX — those live inside the Models panel and stay.

- [ ] **Step 3: Wrap the config sections in `<Tabs>`**

Replace the config sections' container (the `<div className="grid gap-4 xl:grid-cols-...">` wrapper that holds the Scan sections, plus the two collapsible panels, plus `<AgentModelOverrides>`) with this structure. Keep `<AutoTradeSection>` and the Start button OUTSIDE/BELOW the Tabs (they are already after these sections — leave them where they are).

```tsx
<Tabs value={configTab} onValueChange={(v) => setConfigTab(v as typeof configTab)}>
  <TabsList>
    {SCANNER_CONFIG_TABS.map((id) => (
      <TabsTrigger key={id} value={id}>{SCANNER_CONFIG_LABELS[id]}</TabsTrigger>
    ))}
  </TabsList>

  <TabsContent value="scan" keepMounted>
    {/* MOVE here: the top grid (Analysis date / Kline interval / LLM provider),
        the Workflow-mode segmented control + Smart pre-screen toggle/threshold,
        and the Analyst-team chips section — exactly as they render today. */}
  </TabsContent>

  <TabsContent value="analysis" keepMounted>
    {/* MOVE here: the body of the former "Workflow settings" panel (Research depth,
        Output language, Max debate/risk rounds, Max recursion, Max parallel,
        Checkpointing toggle, Prompt-cache toggle) THEN <AgentModelOverrides ... />. */}
  </TabsContent>

  <TabsContent value="models" keepMounted>
    {/* MOVE here: the body of the former "LLM and proxy settings" panel (Backend URL
        + endpoint dropdown, API key, Deep/Quick think models, LLM concurrency,
        Min spacing) — exactly as it renders today, incl. showEndpoints dropdown. */}
  </TabsContent>
</Tabs>
```

> The existing two-column grid layout inside the Scan sections can be preserved
> inside the `scan` panel. The Analysis/Models panels were single-column collapsible
> bodies; render them directly. Keep every `value={...}`/`onChange={...}` binding and
> every `className` exactly as-is — this is a move, not a restyle.

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS. Fix any unused-import errors from the removed collapse buttons (e.g. an now-unused chevron `svg` helper).

- [ ] **Step 5: Lint (catch unused `showWorkflow`/`showLlm` leftovers)**

Run: `npx eslint src/components/scanner/ScannerPage.tsx`
Expected: clean. If `showWorkflow`/`showLlm`/their setters are flagged unused, remove the stragglers.

- [ ] **Step 6: Manual sanity (defer full assertions to Task 6 tests)**

Run: `npm run test -- scanner` — existing scanner tests must stay green (no behavior change yet asserted here).
Expected: PASS (existing suite unchanged).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/scanner/ScannerPage.tsx
git commit -m "feat(scanner): organize Market Scanner config into Scan/Analysis/Models tabs"
```

---

## Task 4: Market Scanner — running/results view into 3 tabs + auto-switch

When a scan is active, wrap the results view in its own `<Tabs>` (Results / Progress / Config) and add the one-shot running→completed auto-switch.

**Files:**
- Modify: `frontend/src/components/scanner/ScannerPage.tsx`

> **Section inventory (the block rendered when `scan && scan.status !== "cancelled"`):**
> - **Progress panel** = status header (icon + `ScanDurationBadge`), progress bar, the stats row (`ScannerMetricCard` buy/sell/hold/skipped), the auto-trade-results block, account-status summaries, AI-Manager notices (the `MobileCollapse` blocks — keep them as-is inside this panel).
> - **Results panel** = the result-cards grid + `ScanResultFiltersBar`.
> - **Config panel** = the `ScanConfigBanner` read-only summary.

- [ ] **Step 1: Add the results-tab state + auto-switch**

Add the imports (if not already from Task 3): `SCANNER_RESULT_TABS, SCANNER_RESULT_LABELS` from `scanTabs`. In the component body add:

```tsx
const [resultsTab, setResultsTab] = useTabPersistence(
  "tradingagents_scanner_results_tab", SCANNER_RESULT_TABS, "progress",
);
const didAutoSwitch = useRef(false);
const prevScanStatus = useRef<string | undefined>(undefined);
// One-shot: switch to Results on the running→completed rising edge, then user wins.
useEffect(() => {
  if (prevScanStatus.current === "running" && scan?.status === "completed" && !didAutoSwitch.current) {
    setResultsTab("results");
    didAutoSwitch.current = true;
  }
  prevScanStatus.current = scan?.status;
}, [scan?.status, setResultsTab]);
// Re-arm the one-shot when a new scan begins.
useEffect(() => { didAutoSwitch.current = false; }, [activeScanId]);
```

> `ScannerPage.tsx` imports named hooks at the top
> (`import { useState, useEffect, useRef, type ReactNode } from "react"`). Use those
> directly (`useRef`, `useEffect`) as shown — do NOT introduce a `React.` namespace
> import.


- [ ] **Step 2: Wrap the results view in `<Tabs>`**

Inside the `{scan && scan.status !== "cancelled" && ( ... )}` block, wrap the content in:

```tsx
<Tabs value={resultsTab} onValueChange={(v) => setResultsTab(v as typeof resultsTab)}>
  <TabsList>
    {SCANNER_RESULT_TABS.map((id) => (
      <TabsTrigger key={id} value={id}>{SCANNER_RESULT_LABELS[id]}</TabsTrigger>
    ))}
  </TabsList>

  <TabsContent value="results" keepMounted>
    {/* MOVE here: the result-cards grid + <ScanResultFiltersBar ... />. */}
  </TabsContent>
  <TabsContent value="progress" keepMounted>
    {/* MOVE here: the status header + progress bar + stats row + auto-trade results
        + account-status summaries + AI-Manager notices (keep the MobileCollapse
        wrappers as-is). */}
  </TabsContent>
  <TabsContent value="config" keepMounted>
    {/* MOVE here: the {(scan.provider || ...) && <ScanConfigBanner scan={scan} />}. */}
  </TabsContent>
</Tabs>
```

Keep the **Cancel** button (in the status header area while running) and the page-header **New Scan** action where they are — NOT inside the tabs. (The status header with Cancel can live in the Progress panel, OR stay above the Tabs; keep it above the Tabs so Cancel is reachable regardless of tab — match the existing position, which is the top of the results block.)

- [ ] **Step 3: Type-check + lint**

Run: `npx tsc --noEmit` → PASS
Run: `npx eslint src/components/scanner/ScannerPage.tsx` → clean

- [ ] **Step 4: Existing tests stay green**

Run: `npm run test -- scanner`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/ScannerPage.tsx
git commit -m "feat(scanner): organize scan results into Results/Progress/Config tabs with auto-switch"
```

---

## Task 5: Scheduled Scan dialog into 5 tabs + force Schedule tab on create

Wrap the dialog's form sections in a `<Tabs>` (Schedule / Scan / Analysis / Models & Connection / Auto-trade), remove the three `CollapsibleSection` collapse flags (KEEP `showEndpoints`), and force the Schedule tab when opening for a new schedule.

**Files:**
- Modify: `frontend/src/components/scanner/ScheduledScansPage.tsx`

> **Section inventory inside `ScheduleFormDialog`'s `<DialogContent>`:**
> - **Schedule panel** = Schedule Name, Schedule Type segmented (Once/Interval/Weekly/Cron), the type-specific params, Timezone (the fields ABOVE the first `CollapsibleSection`).
> - **Scan panel** = the body of the "Scan Configuration" `CollapsibleSection` MINUS Output Language: LLM Provider, Kline Interval, Workflow Mode, TA pre-screen + threshold, Analyst Team.
> - **Analysis panel** = the body of the "Workflow Settings" `CollapsibleSection` (Research Depth, Max Debate/Risk Rounds, Max Recursion, Max Parallel, Checkpointing toggle, Prompt-cache toggle) PLUS **Output Language** (moved out of Scan Config) PLUS `<AgentModelOverrides ... />` (currently rendered after the LLM section — move it here).
> - **Models & Connection panel** = the body of the "LLM & Proxy Settings" `CollapsibleSection`: Backend URL + endpoint dropdown (`showEndpoints`), API Key, Deep/Quick Think Models, LLM Concurrency, Min Spacing.
> - **Auto-trade panel** = `<AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />`.

- [ ] **Step 1: Add imports + persisted dialog-tab state + force-Schedule effect**

Add imports:

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { SCHEDULED_TABS, SCHEDULED_LABELS } from "@/components/scanner/form-tabs/scanTabs";
import { useTabPersistence } from "@/components/scanner/form-tabs/useTabPersistence";
```

Inside `ScheduleFormDialog` (which receives `open` and `editingId` props), add:

```tsx
const [dialogTab, setDialogTab] = useTabPersistence(
  "tradingagents_scheduled_form_tab", SCHEDULED_TABS,
);
// The dialog is always mounted, so localStorage is read only once per page load.
// Force the Schedule tab whenever the dialog opens to CREATE (editingId == null);
// opening to edit leaves the remembered tab. setDialogTab persists, which is fine.
useEffect(() => {
  if (open && editingId == null) setDialogTab("schedule");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: fire on open/editingId edges only
}, [open, editingId]);
```

- [ ] **Step 2: Remove the three collapse flags (KEEP showEndpoints)**

Delete the `showScanConfig`, `showWorkflowSettings`, `showLlmSettings` `useState` declarations. In `handleOpenChange`, EDIT the reset line
`setShowScanConfig(false); setShowWorkflowSettings(false); setShowLlmSettings(false); setShowEndpoints(false);`
to keep ONLY `setShowEndpoints(false);` (remove the three collapse resets, keep the endpoint reset). Do NOT touch `showEndpoints`, `endpoints`, the endpoint click-outside ref effect, `selectEndpoint`, or the endpoint dropdown JSX.

- [ ] **Step 3: Replace the `CollapsibleSection` wrappers with `<Tabs>`**

Replace the three `<CollapsibleSection ...>...</CollapsibleSection>` blocks + the schedule fields above them + the `<AgentModelOverrides>` + `<AutoTradeSection>` with one `<Tabs>`. The `<DialogFooter>` (Save/Update button) stays OUTSIDE the Tabs.

```tsx
<Tabs value={dialogTab} onValueChange={(v) => setDialogTab(v as typeof dialogTab)}>
  <TabsList>
    {SCHEDULED_TABS.map((id) => (
      <TabsTrigger key={id} value={id}>{SCHEDULED_LABELS[id]}</TabsTrigger>
    ))}
  </TabsList>

  <TabsContent value="schedule" keepMounted>
    {/* MOVE here: Schedule Name, Schedule Type segmented, type-specific params, Timezone. */}
  </TabsContent>
  <TabsContent value="scan" keepMounted>
    {/* MOVE here: the Scan Configuration body MINUS Output Language (LLM Provider,
        Kline Interval, Workflow Mode, TA pre-screen + threshold, Analyst Team). */}
  </TabsContent>
  <TabsContent value="analysis" keepMounted>
    {/* MOVE here: the Workflow Settings body (Research Depth, Max Debate/Risk Rounds,
        Max Recursion, Max Parallel, Checkpointing toggle, Prompt-cache toggle),
        THEN Output Language, THEN <AgentModelOverrides ... />. */}
  </TabsContent>
  <TabsContent value="models" keepMounted>
    {/* MOVE here: the LLM & Proxy Settings body (Backend URL + endpoint dropdown,
        API Key, Deep/Quick Think Models, LLM Concurrency, Min Spacing). */}
  </TabsContent>
  <TabsContent value="autotrade" keepMounted>
    <AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />
  </TabsContent>
</Tabs>
```

- [ ] **Step 4: Delete the now-unused `CollapsibleSection` component**

After the move, the local `function CollapsibleSection(...)` (~L1498) has no remaining
references. Run `grep -n "CollapsibleSection" src/components/scanner/ScheduledScansPage.tsx`
— if the only hit is the definition, delete it.

- [ ] **Step 5: Type-check + lint**

Run: `npx tsc --noEmit` → PASS
Run: `npx eslint src/components/scanner/ScheduledScansPage.tsx` → clean (remove any straggler unused imports/state).

- [ ] **Step 6: Existing tests stay green**

Run: `npm run test -- scanner`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/scanner/ScheduledScansPage.tsx
git commit -m "feat(scanner): organize Scheduled Scan dialog into 5 tabs; force Schedule tab on create"
```

---

## Task 6: Render tests for both forms' tabs

Focused render tests asserting tab structure + a representative field per tab + tab switching + the create-forces-Schedule behavior. The heavy data hooks are mocked to no-ops so the forms mount in isolation (these forms had no component tests before — these are the first).

**Files:**
- Create: `frontend/src/components/scanner/__tests__/ScannerPageTabs.test.tsx`
- Create: `frontend/src/components/scanner/__tests__/ScheduledFormTabs.test.tsx`

> **Mocking note:** both pages use `@tanstack/react-query` (`useQuery`/`useMutation`),
> `@/hooks/useModels`, `@/hooks/useConnectivityCheck`, `@tanstack/react-router`
> (`Link`), and (Scanner) a `WebSocket`. Mock these so the component renders the
> CONFIG form (no active scan). Follow the existing mocking style in
> `__tests__/ScanHistoryPage.test.tsx` (it already mocks `@/api/client` and the
> router). Wrap renders in a `QueryClientProvider` with a fresh `QueryClient`.

- [ ] **Step 1: Write the Scanner config-tabs test**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...p }: { children: React.ReactNode }) => <a {...p}>{children}</a>,
}));
vi.mock("@/hooks/useModels", () => ({ useModels: () => ({ data: undefined }) }));
vi.mock("@/hooks/useConnectivityCheck", () => ({
  useConnectivityCheck: () => ({ status: "idle", latency: null, errorMsg: null }),
}));
// Minimal WebSocket stub so the page mounts.
class WS { close() {} send() {} addEventListener() {} removeEventListener() {} }
vi.stubGlobal("WebSocket", WS as unknown as typeof WebSocket);

import { ScannerPage } from "../ScannerPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ScannerPage /></QueryClientProvider>);
}

describe("ScannerPage config tabs", () => {
  beforeEach(() => localStorage.clear());

  it("renders the three config tabs", () => {
    renderPage();
    expect(screen.getByRole("tab", { name: "Scan" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Analysis" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Models & Connection" })).toBeInTheDocument();
  });

  it("keeps a representative field from each tab reachable (keepMounted)", () => {
    renderPage();
    // keepMounted ⇒ all panels are in the DOM regardless of active tab.
    expect(screen.getByText("Analysis date")).toBeInTheDocument();        // Scan
    expect(screen.getByText("Research depth")).toBeInTheDocument();       // Analysis
    expect(screen.getByText(/Backend URL/i)).toBeInTheDocument();         // Models
    // Easy-to-miss Analysis fields the redesign must not drop:
    expect(screen.getByText(/Checkpoint/i)).toBeInTheDocument();
    expect(screen.getByText(/Prompt cache/i)).toBeInTheDocument();
  });

  it("persists the active config tab", () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Models & Connection" }));
    expect(localStorage.getItem("tradingagents_scanner_config_tab")).toBe("models");
  });

  it("keeps the Auto-trade section and Start button below the tabs", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /Start full market scan/i })).toBeInTheDocument();
  });
});
```

> Adjust the exact `getByText` label strings to match the rendered labels (e.g. the
> checkpoint/prompt-cache toggle titles — check the `ScannerToggle title=...` props).
> The intent: assert one field per tab + the two easy-to-miss toggles + the Start button.

- [ ] **Step 2: Run to verify (it should already pass if Task 3 wired tabs correctly)**

Run: `npm run test -- ScannerPageTabs`
Expected: PASS. If a label assertion fails, fix the assertion to the real label (do NOT change the form); if a tab is missing, Task 3's wiring is incomplete — fix there.

- [ ] **Step 3: Write the Scheduled dialog-tabs test**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...p }: { children: React.ReactNode }) => <a {...p}>{children}</a>,
}));
vi.mock("@/hooks/useModels", () => ({ useModels: () => ({ data: undefined }) }));
vi.mock("@/hooks/useConnectivityCheck", () => ({
  useConnectivityCheck: () => ({ status: "idle", latency: null, errorMsg: null }),
}));

import { ScheduledScansPage } from "../ScheduledScansPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ScheduledScansPage /></QueryClientProvider>);
}

describe("ScheduledScansPage dialog tabs", () => {
  beforeEach(() => localStorage.clear());

  it("opens the New-schedule dialog on the Schedule tab and shows all 5 tabs", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
    for (const label of ["Schedule", "Scan", "Analysis", "Models & Connection", "Auto-trade"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps a representative field per tab reachable (keepMounted), incl. moved/easy-to-miss fields", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    await screen.findByRole("tab", { name: "Schedule" });
    expect(screen.getByText(/Schedule Name/i)).toBeInTheDocument();       // Schedule
    expect(screen.getByText(/Analyst Team/i)).toBeInTheDocument();        // Scan
    expect(screen.getByText(/Output Language/i)).toBeInTheDocument();     // Analysis (moved)
    expect(screen.getByText(/Research Depth/i)).toBeInTheDocument();      // Analysis
    expect(screen.getByText(/API Key/i)).toBeInTheDocument();             // Models
  });

  it("forces the Schedule tab on open-for-new even if another tab was remembered", async () => {
    localStorage.setItem("tradingagents_scheduled_form_tab", "models");
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New schedule/i }));
    // editingId == null ⇒ force Schedule despite the stored "models".
    expect(await screen.findByRole("tab", { name: "Schedule" })).toHaveAttribute("data-active");
  });
});
```

> If `findByRole("tab", { name: "Schedule" })` can't resolve because the dialog
> portals outside the container, use `screen` (Testing Library queries the whole
> document by default) — already used above. Adjust label regexes to the real
> rendered text.

- [ ] **Step 4: Run to verify**

Run: `npm run test -- ScheduledFormTabs`
Expected: PASS. Same rule: fix assertions to real labels; fix wiring in Task 5 if a tab/field is genuinely missing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/scanner/__tests__/ScannerPageTabs.test.tsx frontend/src/components/scanner/__tests__/ScheduledFormTabs.test.tsx
git commit -m "test(scanner): cover scan-form tab structure, field presence, and create-forces-Schedule"
```

---

## Task 7: Full validation gates + manual verification

Run every gate, then verify in the browser that the redesign works and nothing regressed.

**Files:** none (verification only)

- [ ] **Step 1: Whole frontend test suite**

Run: `npm run test`
Expected: PASS, 0 failures. The pre-existing scanner sub-component tests (CooloffFields, RegimeStrategyFields, aiManagerCapabilities, CooloffBadge, ScanHistoryPage) must stay green, plus the 4 new test files.

- [ ] **Step 2: Type-check the project**

Run: `npx tsc --noEmit`
Expected: PASS, zero errors.

- [ ] **Step 3: Lint**

Run: `npm run lint`
Expected: no NEW errors in the changed files (`ScannerPage.tsx`, `ScheduledScansPage.tsx`, `form-tabs/*`). Resolve any unused-var/import errors from removed collapse machinery. (Pre-existing lint issues in untouched files are out of scope.)

- [ ] **Step 4: Production build**

Run: `npm run build`
Expected: SUCCESS (`tsc -b && vite build` completes; chunk-size warnings are pre-existing advisories, not errors).

- [ ] **Step 5: Manual browser verification**

Run `npm run dev`, then:
- `/scanner` (config): three tabs (Scan / Analysis / Models & Connection) render; switching tabs works; the Checkpointing + Prompt-cache toggles and Agent overrides are on Analysis; Backend URL endpoint dropdown still opens on Models; Auto-trade + Start stay below the tabs; reload keeps the selected tab.
- `/scanner` (results): start a scan (or open a completed one) — Results / Progress / Config tabs render; Progress is active while running; on completion it switches to Results once; Cancel/New Scan reachable.
- `/scanner/schedules`: click "New schedule" → opens on the Schedule tab; all 5 tabs render; switch to a different tab, close, reopen "New" → back on Schedule; Edit an existing schedule → remembered tab; the endpoint dropdown works on Models; Save/Update creates/updates correctly.

- [ ] **Step 6: Final commit (if any verification-driven fix was needed)**

```bash
git add -A
git commit -m "fix(scanner): address scan-form tab verification findings"
```
(Skip if Steps 1-5 needed no changes.)

---

## Spec Coverage Map

| Spec requirement | Task(s) |
|------------------|---------|
| Shared `scanTabs.ts` (ids/order/labels, single source) | 1 |
| `useTabPersistence` (mount-read, interaction-save, fallback, best-effort) | 2 |
| Market Scanner config → 3 tabs (Scan/Analysis/Models & Connection) | 3 |
| Auto-trade + Start stay below the config tabs | 3 |
| Remove `showWorkflow`/`showLlm` collapse flags (keep `showEndpoints`) | 3 |
| Orphaned fields placed (checkpoint, prompt-cache, AgentModelOverrides — Scanner) | 3 |
| Scanner results → 3 tabs (Results/Progress/Config) | 4 |
| Results running→completed auto-switch (one-shot, re-armed per scan) | 4 |
| `MobileCollapse` blocks kept as-is in Progress tab | 4 |
| Scheduled dialog → 5 tabs (Schedule/Scan/Analysis/Models & Connection/Auto-trade) | 5 |
| Force Schedule tab on open-for-create (`editingId == null`, `open`-keyed effect) | 5 |
| Remove the 3 `CollapsibleSection` flags + the component (keep `showEndpoints`) | 5 |
| Output Language → Analysis (both forms, consistency) | 3 (Scanner: already there), 5 (Scheduled: moved) |
| Orphaned fields placed (checkpoint, prompt-cache, AgentModelOverrides — Scheduled) | 5 |
| `keepMounted` on EVERY panel incl. Auto-trade | 3, 4, 5 |
| Wrap `AutoTradeSection` as-is | 5 |
| Per-form tab persistence (3 independent keys) | 2, 3, 4, 5 |
| Tests: hook, data, render/switch/persist, create-forces-Schedule, auto-switch | 1, 2, 6 |
| Validation gates (tsc/test/lint/build) + manual check | 7 |
| Behavior preservation (no field-logic/handler/AutoTradeSection change) | 3, 4, 5 (move, don't rewrite) + 6 (assert) |

## Notes for the Implementer

- **Move, don't rewrite.** Every field's `value`/`onChange`/`className` is copied verbatim into its tab panel. If you find yourself retyping a field's logic, stop — cut/paste the existing JSX.
- **`keepMounted` is load-bearing.** Without it, switching tabs unmounts `AutoTradeSection` (losing its `useQuery`/per-card state) and interrupts typing. Put it on every `<TabsContent>`.
- **`showEndpoints` ≠ a collapse flag.** It's the backend-URL dropdown. Keep it (both forms).
- **Dialog never unmounts.** The force-Schedule-on-create is an `open`+`editingId` effect, not a mount read.
- **Label strings in tests** are copied from the live markup; if a label differs, fix the test assertion to the real label — never weaken the form to satisfy a test.
- **Big files shift.** Line numbers in this plan are navigation aids; locate sections by their labels/headings.







