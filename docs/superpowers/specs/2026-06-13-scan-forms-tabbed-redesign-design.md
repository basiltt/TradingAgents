# Scan Forms Tabbed Redesign

**Date:** 2026-06-13
**Components:**
- `frontend/src/components/scanner/ScannerPage.tsx` (1651 lines) — Market Scanner / New Scan
- `frontend/src/components/scanner/ScheduledScansPage.tsx` (1514 lines) — Scheduled Scan (list + dialog form)
**Type:** Frontend UI/UX reorganization (tabs) — no form-logic change

---

## Problem

Both scan forms are long single-scroll walls of config. The Market Scanner page
stacks ~10 sections vertically (some behind ad-hoc collapse toggles:
`showWorkflow`, `showLlm`, agent overrides). The Scheduled Scan form is a tall
modal dialog (`max-h-[85vh] overflow-y-auto`) that crams schedule config + the
same scan-config fields + the large shared Auto-trade section into one scroll.

Two specific problems:

1. **Hard to scan / navigate.** Finding a setting means scrolling a long form;
   there's no top-level structure telling the user where things live.
2. **Inconsistent between the two forms.** The Market Scanner and Scheduled Scan
   share most of their scan-config fields (provider, kline interval, output
   language, workflow mode, TA pre-screen, analyst team, research depth, debate /
   risk rounds, recursion, parallelism, backend URL, API key, deep/quick models,
   concurrency, min spacing) but each re-implements them inline with slightly
   different markup, so the two forms look and feel different.

The backtest config form solved the same class of problem with lifecycle tabs +
persistence. This applies that proven pattern to the two scan forms.

## Goal

Reorganize both forms into a **consistent tabbed structure** for scannability,
**preserving all existing form behavior**. This is a presentational JSX
reorganization: every `useState`, submit/start/save handler, validation gate, and
the `AutoTradeSection` component stay exactly as they are. Tabs are a layout
wrapper around the existing field JSX.

## Non-Goals

- No change to form state management (stays per-field `useState`; no react-hook-form / zod introduced).
- No change to submit/start/save handlers, the cool-off launch gate, or any validation.
- No change to `AutoTradeSection`, `CooloffFields`, `RegimeStrategyFields`, or `AICapabilityPanel` internals.
- No extraction of the duplicated scan-config fields into shared field components (explicitly deferred — the user chose "reorganize JSX only"). The two forms keep their own inline field JSX; only the *tab shell* is shared.
- No backend / API changes.

## Approved Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | Both forms, consistent tabs |
| Grouping | By purpose |
| Implementation | Shared tab shell + per-form `useState` (no field extraction) |
| Tab memory | Persist selected tab per form (localStorage), like backtest |
| Auto-trade | Wrapped as-is in its own tab (Scheduled form); stays below tabs on Scanner page |
| Code approach | Reorganize JSX only — preserve all useState logic |
| Scanner results | Gets its own tab set (Results / Progress / Config) once a scan runs |

---

## Architecture

Build a small set of shared tab building blocks, then wrap each form's existing
section JSX in tab panels. The forms keep owning their own state; tabs are a
layout-only wrapper.

### New shared building blocks

Under `frontend/src/components/scanner/form-tabs/`:

```
scanTabs.ts          // Tab id unions + ordered lists + labels for each tab set:
                     //   SCANNER_CONFIG_TABS  = ["scan","analysis","models"]
                     //   SCANNER_RESULT_TABS  = ["results","progress","config"]
                     //   SCHEDULED_TABS       = ["schedule","scan","analysis","models","autotrade"]
                     //   plus *_LABELS maps. One source of truth for order + labels.
useTabPersistence.ts // Hook: const [tab, setTab] = useTabPersistence(storageKey, tabOrder, fallback?)
                     //   - reads the stored id on mount (falls back to fallback ?? tabOrder[0]
                     //     when missing OR not in tabOrder)
                     //   - setTab writes to localStorage on the SAME call (interaction-driven;
                     //     never a mount-time write — mirrors the backtest fix)
```

**Reused as-is:** `Tabs / TabsList / TabsTrigger / TabsContent` from
`@/components/ui/tabs` (base-ui, the same primitive the backtest form and
BacktestResultsPage use). `TabsContent` supports `keepMounted`, which this design
relies on (see Risks).

### What does NOT change

- Every `useState` in both files, the localStorage settings objects
  (`tradingagents_scanner`, the scheduled form-defaults blob), submit/start/save
  handlers, the cool-off launch gate (`cooloffGateValid` / `collectCooloffGateErrors`),
  and `<AutoTradeSection value=... onChange=...>` — all untouched.
- The forms still own their own state; tabs only re-parent existing JSX.

### Boundaries

- `scanTabs.ts` — pure data (ids, order, labels). No React.
- `useTabPersistence.ts` — the only place that touches localStorage for tab state.
  Both forms and the results view consume it with different keys.
- Each form file (`ScannerPage.tsx`, `ScheduledScansPage.tsx`) — owns its state and
  renders `<Tabs>` with its existing sections moved into `<TabsContent>` panels.
  No tab logic is duplicated beyond the one-line `useTabPersistence` call + the
  `<TabsList>` map.

### Persistence keys

| Key | Used by |
|-----|---------|
| `tradingagents_scanner_config_tab` | Market Scanner config tabs |
| `tradingagents_scanner_results_tab` | Market Scanner results tabs |
| `tradingagents_scheduled_form_tab` | Scheduled Scan dialog tabs |

All are additive, independent, and best-effort (a read/parse failure falls back to
the first tab — losing a remembered tab must never break the form).

---

## Tab Layouts

### Market Scanner — config form (3 tabs)

Shown when no scan is active (`!activeScanId`). The existing "Scan configuration"
panel header stays above the tab bar.

```
[ Scan ]   [ Analysis ]   [ Models & Connection ]
```

| Tab (`id`) | Existing sections moved in (current ScannerPage regions) |
|-----------|-----------|
| **Scan** (`scan`) | Analysis date · Kline interval · LLM provider (top grid, ~L644-677) · Workflow mode segmented control + Smart pre-screen toggle + threshold (~L679-730) · Analyst team chips (~L733-771) |
| **Analysis** (`analysis`) | The "Workflow settings" collapsible body: Research depth slider, Output language, Max debate rounds, Max risk rounds, Max recursion limit, Max parallel analyses (~L798-1050) · `<AgentModelOverrides>` (~L1053-1058) |
| **Models & Connection** (`models`) | The "LLM and proxy settings" collapsible body: Backend URL / proxy endpoint, API key, Deep think model, Quick think model, LLM concurrency limit, Min spacing (~L911-1048) |

> The current ad-hoc collapse toggles (`showWorkflow`, `showLlm`) are replaced by
> the tabs — those two `useState` flags and their toggle buttons are removed
> (their content becomes the Analysis / Models tab panels). This is the only
> state removed, and it is purely UI (not form data). `<AgentModelOverrides>` is
> currently rendered always-visible (not behind a collapse, ~L1053); moving it
> into the Analysis tab changes its default visibility from "always shown" to
> "shown when the Analysis tab is active" — intended.

> Line-number ranges throughout this doc are approximate anchors against the
> current file to help navigation; they will shift as JSX is moved. Identify the
> sections by their labels/headings, not the exact line numbers.


**Below the tabs — always visible (NOT in a tab):**
- `<AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />`
- The **Start full market scan** button + the cool-off launch hint + start error.

Rationale: the launch button and its cool-off gate must be reachable from any tab,
so they live below the tab panels (same "always-visible action" principle as the
backtest sticky footer). Auto-trade stays below for the same reason and because on
the Scanner page it's a distinct, optional concern.

### Scheduled Scan — dialog form (5 tabs)

Inside the existing `ScheduleFormDialog` `<DialogContent>`. The dialog title and
the Save/Create + Cancel footer stay outside the tabs (always visible).

```
[ Schedule ]   [ Scan ]   [ Analysis ]   [ Models ]   [ Auto-trade ]
```

| Tab (`id`) | Content (current ScheduledScansPage dialog regions) |
|-----------|-----------|
| **Schedule** (`schedule`) | Schedule Name · Schedule Type (Once / Interval / Weekly / Cron segmented) · type-specific params (Date&Time / Interval minutes / Time + Days / Day of Week / Cron expression) · Timezone (~L1114-1213) |
| **Scan** (`scan`) | LLM Provider · Kline Interval · Output Language · Workflow Mode · TA pre-screen + threshold · Analyst Team (~L1218-1314) |
| **Analysis** (`analysis`) | Research Depth · Max Debate Rounds · Max Risk Rounds · Max Recursion Limit · Max Parallel Analyses (~L1316-1370) |
| **Models** (`models`) | Backend URL / Proxy · API Key · Deep Think Model · Quick Think Model · LLM Concurrency Limit · Min Spacing (~L1373-1470) |
| **Auto-trade** (`autotrade`) | `<AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />` (~L1475), wrapped in this tab, unchanged |

**Consistency:** the **Scan / Analysis / Models** tabs are conceptually identical
across both forms (same field groupings, same labels), so the two forms feel like
one family. The Scheduled form just adds **Schedule** (first) and **Auto-trade**
(last).

---

## Scanner Results Tabs

When a scan is active (`activeScanId` set), the config form is replaced by the
running/results view today. That view gets its **own, separate** tab set:

```
[ Results ]   [ Progress ]   [ Config ]
```

| Tab (`id`) | Existing content moved in (current ScannerPage "Progress"/results regions) |
|-----------|-----------|
| **Results** (`results`) | The result-cards grid + `ScanResultFiltersBar` (buy/sell/hold filters) + the auto-trade execution result cards (~L1179-1206 plus the cards section below the progress block) |
| **Progress** (`progress`) | Progress header (status icon + `ScanDurationBadge`), progress bar, stats row (buy/sell/hold/skipped counts ~L1169-1177), account-status summaries (~L1208-1223), AI-Manager reduced-protection notices (~L1225-1239) |
| **Config** (`config`) | The `ScanConfigBanner` read-only summary (~L1150-1153) |

- **Cancel** (while running) and **New Scan** stay in the page header/action area —
  not inside a tab.
- This is a **separate** tab set from the config tabs. Config tabs show before a
  scan; results tabs show during/after. They are never on screen at the same time,
  so there is no ambiguity about which tab bar is active.
- **Default tab:** **Progress** while the scan is running; auto-switch to
  **Results** once `scan.status === "completed"`. (A failed/cancelled scan stays on
  Progress.) After the first auto-switch, the user's manual tab choice is respected
  and persisted.

## Tab Persistence Behavior

`useTabPersistence(storageKey, tabOrder, fallback?)` returns `[activeTab, setActiveTab]`:

- **On mount:** read `localStorage[storageKey]`; if it's a valid id in `tabOrder`,
  use it; otherwise use `fallback ?? tabOrder[0]`.
- **On change:** `setActiveTab(next)` updates state AND writes
  `localStorage[storageKey] = next` in the same call — interaction-driven only,
  never on mount (this is the exact lesson from the backtest redesign, where a
  mount-time write clobbered other state).
- **Best-effort:** any localStorage read/parse/write failure degrades to the
  fallback / no-op; it never throws.

**Per-surface behavior:**
- **Scanner config tabs** (`tradingagents_scanner_config_tab`): persist across page
  reloads.
- **Scanner results tabs** (`tradingagents_scanner_results_tab`): persist across
  reloads; the running→completed auto-switch to Results overrides the stored value
  once, then user choice wins.
- **Scheduled dialog tabs** (`tradingagents_scheduled_form_tab`): restored when the
  dialog reopens. **Exception:** opening the dialog to **create a new** schedule
  starts on the **Schedule** tab (ignoring the stored value); opening to **edit** an
  existing schedule restores the last-used tab. (Rationale: a new schedule needs its
  name/type set first; editing is usually to tweak a specific known area.)

---

## Testing Strategy

These forms use per-field `useState` (no react-hook-form / zod) and currently have
**no component tests for ScannerPage / ScheduledScansPage themselves** (only
sub-components like CooloffFields, RegimeStrategyFields, aiManagerCapabilities are
tested). Because this is a JSX reorganization with zero form-logic change, testing
focuses on the shared tab pieces + render-level preservation:

1. **`useTabPersistence` unit tests:** saves the id on `setActiveTab`; restores a
   valid stored id on mount; falls back to the first tab when the stored id is
   missing OR not in `tabOrder`; never writes on mount; degrades gracefully when
   localStorage throws.
2. **`scanTabs` unit test:** every tab set has a label for every id, and the order
   arrays contain only known ids (no orphans/dupes).
3. **Market Scanner render tests:** the 3 config tabs render; clicking each switches
   the visible panel; a representative field from EACH tab is reachable (e.g.
   "Analysis date" on Scan, "Research depth" on Analysis, "Backend URL" on Models);
   the Auto-trade section and Start button remain present below the tabs; the active
   config tab persists across remount.
4. **Scheduled dialog render tests:** the 5 tabs render; opening for "new" starts on
   Schedule; a representative field per tab is reachable; the AutoTradeSection
   renders under the Auto-trade tab; the Save footer is always present.
5. **Behavior-preservation:** the existing sub-component tests (CooloffFields,
   RegimeStrategyFields, aiManagerCapabilities, CooloffBadge) must stay green —
   they exercise logic this change does not touch.

**Validation gates before completion (run and read full output):**
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npm run test`
- `cd frontend && npm run build`
- Live visual check of both forms in the browser (tabs switch, fields present,
  scan can start, dialog saves) — mirrors the backtest verification.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Moving JSX drops a field or breaks a `value`/`onChange` binding | Each field keeps its exact existing binding (move, don't rewrite); render tests assert a representative field per tab is present and editable |
| A `useState`-bound input unmounts when its tab is inactive, losing focus / interrupting typing | All config panels render with the Tabs primitive's `keepMounted` so hidden panels stay in the DOM (no Controller/input unmount) — the exact lesson from the backtest redesign |
| Scheduled dialog tab state leaks between create and edit | `useTabPersistence` keyed per-form; the dialog forces the Schedule tab when opening for create |
| Removing `showWorkflow`/`showLlm` collapse toggles breaks something referencing them | These are UI-only booleans; grep confirms they gate only the collapsible bodies now becoming tabs — remove the state + toggle buttons together with their panels' re-parenting |
| Results auto-switch (running→Results) fights the persisted value | Auto-switch fires once on the running→completed transition; afterward the persisted user choice wins (tracked via a "did auto-switch" ref, like backtest's rising-edge pattern) |
| The two large files get even larger | Acceptable per scope (user chose "reorganize JSX only", not extract components); the net line delta is small since JSX is moved, not added |

## Success Criteria

- Market Scanner config renders as 3 tabs (Scan / Analysis / Models & Connection);
  Auto-trade + Start button stay below, always visible.
- Scheduled Scan dialog renders as 5 tabs (Schedule / Scan / Analysis / Models /
  Auto-trade); Save footer always visible.
- Scanner running/results view renders as 3 tabs (Results / Progress / Config).
- Each form remembers its selected tab across reload / dialog reopen (with the
  new-schedule → Schedule-tab exception).
- Every field present before is present after, with identical behavior; the scan
  start gate (cool-off) and dialog save behave exactly as before.
- `tsc --noEmit`, the test suite, and `npm run build` all pass; existing
  sub-component tests stay green.
- No changes to `AutoTradeSection` or any backend/API.




