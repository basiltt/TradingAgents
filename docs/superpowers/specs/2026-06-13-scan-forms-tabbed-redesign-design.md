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
| AgentModelOverrides visibility | Currently always-visible; moves into the Analysis tab (shown only when that tab is active) — accepted UX change |
| Results auto-switch | Running→completed auto-switch to Results is NEW behavioral logic (a `useRef` rising-edge + `useEffect`), not pure JSX-moving — small, explicitly in scope |

> **Two things this redesign adds beyond moving JSX (called out so they aren't
> under-estimated or left untested):** (1) the `useTabPersistence` hook, and (2) the
> Scanner results running→completed auto-switch. Everything else is re-parenting
> existing JSX into tab panels.


---

## Architecture

Build a small set of shared tab building blocks, then wrap each form's existing
section JSX in tab panels. The forms keep owning their own state; tabs are a
layout-only wrapper.

### New shared building blocks

Under `frontend/src/components/scanner/form-tabs/`:

```
scanTabs.ts          // Tab id unions + ordered lists + labels for each tab set.
                     // Tab ids are kebab-case lowercase; labels are human-readable:
                     //   SCANNER_CONFIG_TABS  = ["scan","analysis","models"]
                     //   SCANNER_RESULT_TABS  = ["results","progress","config"]
                     //   SCHEDULED_TABS       = ["schedule","scan","analysis","models","autotrade"]
                     //   *_LABELS maps each id → title, e.g.
                     //     scan→"Scan", analysis→"Analysis",
                     //     models→"Models & Connection"  (SAME label in both forms),
                     //     schedule→"Schedule", autotrade→"Auto-trade",
                     //     results→"Results", progress→"Progress", config→"Config"
                     // One source of truth for order + labels. No React.
useTabPersistence.ts // Hook: const [tab, setTab] = useTabPersistence(storageKey, tabOrder, fallback?)
                     //   - reads the stored id ONCE on mount (falls back to fallback ?? tabOrder[0]
                     //     when missing OR not in tabOrder)
                     //   - setTab(next) updates state AND writes localStorage in the SAME call
                     //     (interaction-driven; never a mount-time write — the backtest lesson)
                     //   - returns [tab, setTab]; the SETTER is also used imperatively by callers
                     //     that need to force a tab (e.g. the dialog forcing "schedule" on open-for-new,
                     //     or the results view auto-switching to "results" on completion). Those
                     //     imperative setTab calls persist too, which is correct.
```

> **Models label:** both forms use the label **"Models & Connection"** for the
> `models` tab (the earlier draft inconsistently shortened the Scheduled one to
> "Models"). Identical labels reinforce the "same family" goal.


**Reused as-is:** `Tabs / TabsList / TabsTrigger / TabsContent` from
`@/components/ui/tabs` (base-ui 1.4.1, the same primitive the backtest form and
BacktestResultsPage use). `TabsContent` exposes `keepMounted` (verified) and our
wrapper forwards it. **Every tab panel in every tab set uses `keepMounted`** — see
the keepMounted rationale in Risks (it is NOT about losing input values, since all
inputs are parent-`useState`-controlled; it is about preserving focus/typing
continuity, internal sub-component state, and open dropdowns/popovers across tab
switches).

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
| **Analysis** (`analysis`) | The "Workflow settings" collapsible body (~L798-885): Research depth slider, Output language, Max debate rounds, Max risk rounds, Max recursion limit, Max parallel analyses, **Checkpointing toggle (`checkpointEnabled`, ~L864), Prompt-cache toggle (`promptCacheEnabled`, ~L871)** · `<AgentModelOverrides>` (~L1053) |
| **Models & Connection** (`models`) | The "LLM and proxy settings" collapsible body (~L907-1048): Backend URL / proxy endpoint, API key, Deep think model, Quick think model, LLM concurrency limit, Min spacing |

> **Field-inventory note:** the Analysis tab MUST include the `checkpointEnabled`
> and `promptCacheEnabled` toggles — they are real submitted fields
> (`checkpoint_enabled` / `prompt_cache_enabled` in the start payload) and were
> easy to miss because they sit deep in the Workflow-settings collapsible. Output
> language stays in **Analysis** (see cross-form consistency note below).


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
[ Schedule ]   [ Scan ]   [ Analysis ]   [ Models & Connection ]   [ Auto-trade ]
```

| Tab (`id`) | Content (current ScheduledScansPage dialog regions) |
|-----------|-----------|
| **Schedule** (`schedule`) | Schedule Name · Schedule Type (Once / Interval / Weekly / Cron segmented) · type-specific params (Date&Time / Interval minutes / Time + Days / Day of Week / Cron expression) · Timezone (~L1114-1213) |
| **Scan** (`scan`) | LLM Provider · Kline Interval · Workflow Mode · TA pre-screen + threshold · Analyst Team (from the "Scan Configuration" `CollapsibleSection`, ~L1215-1311) |
| **Analysis** (`analysis`) | Research Depth · **Output Language** (moved here for cross-form consistency) · Max Debate Rounds · Max Risk Rounds · Max Recursion Limit · Max Parallel Analyses · **Checkpointing toggle, Prompt-cache toggle** · `<AgentModelOverrides>` (~L1472) (from the "Workflow Settings" `CollapsibleSection`, ~L1314-1367) |
| **Models & Connection** (`models`) | Backend URL / Proxy · API Key · Deep Think Model · Quick Think Model · LLM Concurrency Limit · Min Spacing (from the "LLM & Proxy Settings" `CollapsibleSection`, ~L1370-1469) |
| **Auto-trade** (`autotrade`) | `<AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />` (~L1475), wrapped in this tab, unchanged. The tab panel uses `keepMounted` (see Risks). |

> **Field-inventory note (Scheduled):** the dialog ALSO has `checkpointEnabled`,
> `promptCacheEnabled` (state ~L827-828, submitted as `checkpoint_enabled` /
> `prompt_cache_enabled`) and `<AgentModelOverrides>` (~L1472, currently rendered
> directly after the LLM section, NOT inside a CollapsibleSection). All three go in
> the **Analysis** tab, matching the Scanner form. Output Language moves from the
> dialog's Scan Configuration section into **Analysis** so the Scan/Analysis split is
> identical across both forms.

> **Existing collapsibles to remove (Scheduled):** the dialog currently wraps its
> Scan / Workflow / LLM groups in a local `CollapsibleSection` component
> (`ScheduledScansPage.tsx:1498`) driven by `showScanConfig`, `showWorkflowSettings`,
> `showLlmSettings`. The tabs replace these: remove those **three** `useState`
> flags, their reset lines in `handleOpenChange`, and the `CollapsibleSection`
> wrappers, moving each section's children directly into its tab panel. Delete the
> now-unused `CollapsibleSection` component if nothing else references it.
>
> **DO NOT remove `showEndpoints`.** It is NOT a section-collapse flag — it drives
> the backend-URL endpoint-picker dropdown (state L838-839, click-outside ref
> L869-875, `selectEndpoint` L877, dropdown trigger/list L1380-1420). It moves into
> the **Models & Connection** tab intact (with `endpoints`, the ref effect,
> `selectEndpoint`, the dropdown JSX, and its `handleOpenChange` reset line),
> mirroring the identical dropdown the Scanner page keeps. Removing it would delete
> a working feature and create the exact cross-form inconsistency this redesign
> exists to eliminate.



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

> **Nested collapsibles (Progress tab):** the account-status, auto-trade-results,
> and AI-Manager notice blocks the Progress tab absorbs are currently wrapped in
> `MobileCollapse` (`ScannerPage.tsx:1278-1379`, 4 instances). Inside a tab panel a
> `MobileCollapse` is a redundant second layer of collapsing. Default: **keep the
> `MobileCollapse` wrappers as-is** (they only collapse on mobile via their own
> breakpoint logic and are harmless on desktop) to keep this a pure JSX move; an
> implementer MAY flatten them if it reads better, but that is optional and not
> required for correctness.

- **Cancel** (while running) and **New Scan** stay in the page header/action area —
  not inside a tab.
- **Cancelled-scan visibility:** the results view renders for a cancelled scan *only
  if it produced partial results* (`scan && !(status === "cancelled" && results.length === 0)`).
  A cancelled scan that completed some symbols keeps its tabs so those results stay
  reachable (pre-redesign they showed via a separate always-visible results block); a
  cancelled+empty scan is hidden and the cleanup effect clears `activeScanId` back to
  the config form. The two gates key on the identical predicate, so they always agree.
- This is a **separate** tab set from the config tabs. Config tabs show before a
  scan; results tabs show during/after. They are never on screen at the same time,
  so there is no ambiguity about which tab bar is active.
- **Default tab:** **Progress** while the scan is running; auto-switch to
  **Results** once `scan.status === "completed"`. (A failed/cancelled scan stays on
  Progress.) After the first auto-switch, the user's manual tab choice is respected
  and persisted.

### Results auto-switch algorithm (new behavioral logic)

A one-shot, rising-edge switch from Progress → Results on completion, then the user
is in control. Concretely:

```tsx
const [resultsTab, setResultsTab] = useTabPersistence(
  "tradingagents_scanner_results_tab", SCANNER_RESULT_TABS, "progress",
);
const didAutoSwitch = React.useRef(false);
const prevStatus = React.useRef<string | undefined>(undefined);
React.useEffect(() => {
  // Rising edge: running → completed, fire at most once per scan.
  if (prevStatus.current === "running" && scan?.status === "completed" && !didAutoSwitch.current) {
    setResultsTab("results");
    didAutoSwitch.current = true;
  }
  prevStatus.current = scan?.status;
}, [scan?.status, setResultsTab]);
// Reset when a NEW scan begins (activeScanId changes): re-arm the one-shot guard
// AND snap back to Progress, so the previous scan's persisted "results" can't strand
// the user on an empty Results panel while the new scan runs. Guarded on a real
// activeScanId so it never fires a mount-time write (no scan ⇒ no-op).
React.useEffect(() => {
  didAutoSwitch.current = false;
  if (activeScanId) setResultsTab("progress");
}, [activeScanId, setResultsTab]);
```

- It fires **once** (guarded by `didAutoSwitch`), only on the running→completed
  transition; subsequent re-renders do not re-switch.
- The `activeScanId`-keyed effect resets the guard **and** snaps the view back to
  Progress so each new scan re-arms cleanly and starts on the live Progress view
  (the documented "while running" default), regardless of where the previous scan
  left the persisted tab.
- The auto-switch persists (`setResultsTab` writes localStorage), which is the
  intended "remember Results after completion" behavior; the user can still click
  back to Progress afterward and that choice persists.


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
- **Scanner results tabs** (`tradingagents_scanner_results_tab`): the key is written
  on interaction (and by the auto-switch), but in practice the tab is only visible
  while a scan is active, and the new-scan reset effect snaps it back to `progress`
  whenever `activeScanId` is (re)established — including a reload that re-attaches to
  a live scan. So the *observable* default is always Progress while running, with the
  running→completed auto-switch promoting Results once and the user's manual choice
  winning until the next scan begins (see algorithm above). The persisted value is a
  best-effort detail, not a guaranteed cross-reload "remembered Results."
- **Scheduled dialog tabs** (`tradingagents_scheduled_form_tab`): the active tab is
  remembered while the page is open and across reloads.

> **CRITICAL — dialog lifecycle (verified):** `ScheduleFormDialog` is rendered
> **unconditionally** by its parent (`ScheduledScansPage.tsx:711`, `open={dialogOpen}`)
> — it **never unmounts**. So `useTabPersistence`'s mount-time read fires only once
> per page load, NOT per dialog open. This means:
> - "Restored when the dialog reopens" is satisfied by the always-mounted React
>   state itself (the tab simply stays where it was); localStorage only matters
>   across full page reloads.
> - The "new schedule → start on Schedule tab" rule therefore CANNOT rely on a
>   mount read. Implement it as an effect keyed on the dialog's `open` prop that
>   forces the tab when opening for create:
>   ```tsx
>   // editingId == null  ⇒  creating a new schedule (verified signal, L341/L794)
>   React.useEffect(() => {
>     if (open && editingId == null) setActiveTab("schedule");
>   }, [open, editingId]);  // setActiveTab persists, which is fine
>   ```
>   Opening to **edit** (`editingId != null`) leaves the remembered tab as-is. Note
>   the dialog shows a loading spinner while edit data fetches (`editingId && editLoading`,
>   ~L1102); the force-effect targets the create path only, so the spinner delay is
>   irrelevant to it.


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
   "Analysis date" on Scan, "Research depth" on Analysis, "Backend URL" on Models) —
   **including the easy-to-miss Analysis fields: the Checkpointing toggle, the
   Prompt-cache toggle, and `AgentModelOverrides`**; the Auto-trade section and Start
   button remain present below the tabs; the active config tab persists across remount.
4. **Scheduled dialog render tests:** the 5 tabs render; **opening for "new"
   (`editingId == null`) forces the Schedule tab even if a different tab was
   remembered** (the C1 behavior); a representative field per tab is reachable
   (incl. the moved Output Language, checkpoint/prompt-cache toggles, and
   AgentModelOverrides on Analysis); the AutoTradeSection renders under the
   Auto-trade tab; the Save footer is always present.
5. **Results auto-switch test:** simulate a scan going running→completed and assert
   the results view switches to the Results tab exactly once; assert a manual switch
   back to Progress afterward is NOT overridden on the next render; assert a new
   `activeScanId` re-arms the one-shot.
6. **Behavior-preservation:** the existing sub-component tests (CooloffFields,
   RegimeStrategyFields, aiManagerCapabilities, CooloffBadge) must stay green —
   they exercise logic this change does not touch. The cool-off launch gate on the
   Scanner page must still disable Start under the same conditions.


**Validation gates before completion (run and read full output):**
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npm run test`
- `cd frontend && npm run build`
- Live visual check of both forms in the browser (tabs switch, fields present,
  scan can start, dialog saves) — mirrors the backtest verification.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Moving JSX drops a field or breaks a `value`/`onChange` binding | Each field keeps its exact existing binding (move, don't rewrite); render tests assert a representative field per tab is present and editable; the field-inventory notes call out the easy-to-miss fields (`checkpointEnabled`, `promptCacheEnabled`, `AgentModelOverrides`) |
| Switching tabs interrupts typing, drops focus, resets a sub-component's internal state, or closes an open dropdown | Apply `keepMounted` to **every** tab panel in **every** tab set (config, results, AND the Auto-trade tab). NOTE: this is NOT about losing input values — all inputs are parent-`useState`-controlled, so an unmounted panel's values survive in the parent regardless. It is about (a) focus/typing continuity, (b) `AutoTradeSection`'s internal `useQuery(accounts)` + per-card `useState`/`AICapabilityPanel` state resetting on each switch, and (c) the backend-URL endpoint dropdown's click-outside ref (`ScannerPage.tsx:916`). `keepMounted` keeps all panels in the DOM so none of these reset. |
| Scheduled dialog never unmounts → tab persistence / new-vs-edit reset behaves unexpectedly | Verified: dialog is always-mounted (`open={dialogOpen}`). Use an `open`+`editingId`-keyed effect to force the Schedule tab on open-for-create; "restore on reopen" is satisfied by the always-mounted React state. (See Tab Persistence Behavior.) |
| Removing collapse state breaks something referencing it | Scanner: `showWorkflow`/`showLlm` are UI-only and NOT in the `tradingagents_scanner` settings blob (verified) — safe to delete with their toggle buttons. Scheduled: remove ONLY `showScanConfig`/`showWorkflowSettings`/`showLlmSettings` + the local `CollapsibleSection` component, together with their reset lines in `handleOpenChange`; grep for remaining references before deleting `CollapsibleSection`. **Keep `showEndpoints`** — it drives the backend-URL endpoint dropdown (not a collapse); move it into the Models tab intact, mirroring Scanner. |
| Results auto-switch (running→Results) fights the persisted value | Auto-switch fires once on the running→completed transition (rising-edge `useRef` guard), re-armed per new `activeScanId`; afterward the persisted user choice wins. Full algorithm specified in Scanner Results Tabs. |
| Nested `MobileCollapse` inside the Progress tab reads oddly | The 4 `MobileCollapse` blocks (`ScannerPage.tsx:1278-1379`) only collapse at a mobile breakpoint; harmless inside a desktop tab. Keep as-is (pure move); flattening is optional. |
| `keepMounted` puts all panels in the DOM at once → duplicate `id`/`htmlFor` collisions | Audit for `id`/`htmlFor` collisions when all panels co-exist (e.g. `schedule-name`, `scanner_ta_threshold`); the existing ids are already unique per form, but verify after the move. |
| The two large files get even larger | Acceptable per scope (user chose "reorganize JSX only", not extract components); the net line delta is small since JSX is moved, not added. The realistic effort is non-trivial (~30 fields across two ~1500-line files) — budget accordingly; it is not a 10-minute "wrap in TabsContent". |

## Success Criteria

- Market Scanner config renders as 3 tabs (Scan / Analysis / Models & Connection);
  Auto-trade + Start button stay below, always visible.
- Scheduled Scan dialog renders as 5 tabs (Schedule / Scan / Analysis / Models &
  Connection / Auto-trade); Save footer always visible; opening for a NEW schedule
  starts on the Schedule tab.
- Scanner running/results view renders as 3 tabs (Results / Progress / Config);
  Progress is active while running and auto-switches to Results on completion.
- Each form remembers its selected tab across reload / dialog session (with the
  new-schedule → Schedule-tab exception).
- Every field present before is present after, with identical behavior — including
  `checkpointEnabled`, `promptCacheEnabled`, and `AgentModelOverrides`; the scan
  start gate (cool-off) and dialog save behave exactly as before.
- `tsc --noEmit`, the test suite, and `npm run build` all pass; existing
  sub-component tests stay green.
- No changes to `AutoTradeSection` or any backend/API.





