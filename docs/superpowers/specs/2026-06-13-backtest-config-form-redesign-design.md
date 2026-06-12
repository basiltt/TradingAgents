# Backtest Config Form — UI/UX Redesign

**Date:** 2026-06-13
**Component:** `frontend/src/components/backtest/BacktestConfigForm.tsx`
**Type:** Frontend UI/UX redesign + structural refactor (no form-semantics change)

---

## Problem

`BacktestConfigForm.tsx` is a single 1102-line file rendering ~10 collapsible
sections stacked vertically, each laying fields out in a rigid 3-column grid
(`GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"`). The form works
but is hard to use and hard to maintain. The user flagged four specific pains:

1. **Broken grouping/pairing.** Checkbox-enables-input pairs are scattered by the
   rigid grid. In the "Advanced (engine-level)" section, "Cool off after a win"
   lands on one grid row while its "Win cool off (min)" input lands in the next
   row's first column — they don't read as a pair. The win/loss/2-win/2-loss
   cool-off controls are visually interleaved.
2. **Dead inputs always visible.** The cool-off and adaptive-blacklist minutes
   inputs render even when their enabling toggle is off, producing blank/disabled-
   looking fields (e.g. "Loss cool off (min)" shows an empty box because the loss
   toggle is unchecked). This is visual noise and implies the field is active when
   it isn't.
3. **Too long / hard to scan.** ~10 sections in one scroll column make it hard to
   find a setting or judge what matters.
4. **Visual inconsistency.** The Close Rules section already uses a clean
   `ToggleNumberField` (input revealed only when the toggle is on), but the
   Advanced section's cool-off and adaptive-blacklist groups don't — so two
   different interaction patterns coexist for the same kind of control.

## Goal

Redesign the whole form for clarity and consistency while making **zero changes to
form semantics**: same zod schema, same submitted payload (`toCreateRequest`
output), same draft persistence, same reference-config buttons. This is a
presentational + structural refactor.

## Non-Goals

- No changes to `configSchema.ts` (the zod schema / field set / defaults).
- No changes to the backtest backend, engine, or API contract.
- No new fields, no removed fields, no renamed form fields.
- No changes to `backtestDraft.ts` persistence format beyond optionally storing the
  active tab id (additive, backward-compatible).

---

## Approved Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | Whole form, deep redesign |
| Navigation | Tabbed groups (4 tabs) |
| Tab grouping | By lifecycle: Setup / Strategy / Risk & Exits / Filters & Advanced |
| Toggle+input behavior | Reveal input inline only when toggle is on |
| Errors across tabs | Auto-switch to first errored tab + per-tab count badges + keep summary banner |
| Field provenance tags | Keep (Scanner / Backtest-only / Engine-level / not-simulated) |
| Intro explainer | Keep, rendered once above the tab bar |
| Within-tab sections | Flat, always-open cards (no nested collapsing) |
| Action buttons | Sticky footer, always visible; keep all 5 buttons |
| Code restructuring | Modular tab components + shared fields module + thin shell |

---

## Architecture

Decompose the 1102-line monolith into a thin shell plus focused tab components.
All form-state logic (react-hook-form ownership, zod resolver, draft persistence,
reference-config callbacks, invalid-submit focus handling) stays in the shell —
the tabs are presentational and receive what they need via props.

### File structure

```
frontend/src/components/backtest/
  BacktestConfigForm.tsx          // thin shell (~250 lines): RHF state, intro,
                                  //   tab bar + badges, error routing, sticky footer
  config-form/
    fields.tsx                    // moved helpers: NumberField, SelectField,
                                  //   CheckField, ToggleNumberField, HoursListField,
                                  //   SymbolListField, Hint, Section, GRID
    ToggleNumberPairField.tsx     // NEW: checkbox(_enabled bool) + revealed (_minutes)
                                  //   input, for the cool-off pairs
    tabMeta.ts                    // tab ids, labels, ordered list, and the field-path
                                  //   groups per tab (single source of truth for
                                  //   error routing + badges)
    SetupTab.tsx                  // Backtest Setup + Signal Source + Execution Model
    StrategyTab.tsx               // Trade Decisions + Market Regime & Strategy
    RiskExitsTab.tsx              // Close Rules + Risk Limits + Target Goal
    FiltersAdvancedTab.tsx        // Symbol Filters + Advanced (engine-level)
```

### Module boundaries

- **Shell (`BacktestConfigForm.tsx`)** — owns `useForm`, the draft `watch`
  subscription, all reference/reset callbacks, `submit`, `fieldError`/`anyError`,
  `validationMessages`, the active-tab state, and the error-routing logic. Renders:
  intro banner → summary banner → `<Tabs>` with badged triggers → the active tab
  component → sticky footer. Knows nothing about individual field layout.
- **Tab components** — pure presentational. Each receives `control`,
  `fieldError`, and the specific `watch`/`setValue` values it needs (e.g.
  `StrategyTab` needs `mrLongEnabled`; `RiskExitsTab` needs the duration-limits
  derived state). They render `Section` cards + fields. No RHF instantiation.
- **`fields.tsx`** — the existing field helpers moved verbatim (same props, same
  behavior). Existing tests re-point their imports here.
- **`tabMeta.ts`** — exports `TAB_ORDER`, tab labels, and
  `FIELD_PATHS_BY_TAB: Record<TabId, string[]>`. Both the badge counts and the
  auto-switch target derive from this one map, so they cannot drift apart.

### What gets simplified

The `Section` component's collapse machinery (`open`/`defaultOpen`/`forceOpen`,
the render-time `forceOpen` rising-edge logic) is **removed**. Tabs now handle
length, and sections are always-open flat cards. `Section` keeps only: a header,
an optional grey subtitle, and children inside the `neu-surface-raised` card.
This deletes the most subtle stateful code in the file.

---

## Tab Layout & Content

Rendered with the existing `Tabs` primitive (`frontend/src/components/ui/tabs.tsx`,
`default` variant) — matching the precedent already set by `BacktestResultsPage`.

```
[ Setup ]   [ Strategy ]   [ Risk & Exits ]   [ Filters & Advanced ]
```

### Tab → section → field mapping

**Tab 1 — Setup**
- *Backtest Setup* — `starting_capital`, `date_range_start`, `date_range_end`
- *Signal Source* — `scan_source.*` (mode, schedule_id, scan_ids, replay_account_id)
- *Execution Model* — `simulation_interval`, `fee_rate_pct`, `slippage_bps`,
  `funding_rate_model`, `funding_rate_fixed_pct`

**Tab 2 — Strategy**
- *Trade Decisions* — `direction`, `leverage`, `capital_pct`, `take_profit_pct`,
  `stop_loss_pct`, `min_score`, `confidence_filter`, `signal_sides`, `max_trades`,
  `execution_mode`, `fill_to_max_trades`, `skip_if_positions_open`
- *Market Regime & Strategy (F1/F2/F3)* — regime filter, session hours, BTC vol
  band, strategy cohort, mean-reversion fields (`mr_*`)

**Tab 3 — Risk & Exits**
- *Close Rules* — `max_drawdown_pct`, `smart_drawdown_close`, `close_on_profit_pct`,
  duration limits (`breakeven_timeout_hours` + `max_trade_duration_hours`),
  `trailing_profit_pct`
- *Risk Limits* — `max_same_direction`, `max_signal_age_minutes`
- *Target Goal* — `target_goal_type`, `target_goal_value`

**Tab 4 — Filters & Advanced**
- *Symbol Filters* — `symbol_whitelist`, `symbol_blacklist`
- *Advanced (engine-level)* — `max_price_drift_pct`, `max_same_sector`,
  adaptive blacklist group, cool-off group (see Toggle Pattern below)

> The exact field-to-tab assignment is the basis for `FIELD_PATHS_BY_TAB` in
> `tabMeta.ts`. Every form field must appear in exactly one tab — a unit test
> asserts the union of all tab field-path lists equals the full schema key set, so
> no field can be silently orphaned by future edits.

### Within a tab

- Sections render as **flat, always-open cards** (`neu-surface-raised`,
  `var(--neu-radius-lg)`, `p-4`) with a bold header and the existing grey subtitle.
- Plain inputs keep the responsive `GRID` (1 / 2 / 3 columns).
- The intro explainer paragraph renders **once, above the tab bar**, so the
  Scanner / Backtest-only / Engine-level / not-simulated legend applies across tabs.
- Per-field provenance hints are unchanged.

### Default & persistence

- Default active tab: `setup`.
- Active tab id is persisted into the existing draft (additive field
  `active_tab?: TabId`) so returning to the form restores the user's place. A draft
  predating this field simply falls back to `setup`. This is the only change to the
  draft shape and is backward-compatible.

---

## Toggle + Input Pattern (core fix)

Every "checkbox enables a number input" control adopts the **reveal-when-on**
pattern already used by `ToggleNumberField` in Close Rules: when the toggle is off,
no input renders; when on, the input appears inline next to the toggle.

### Two underlying field shapes

There are two distinct schema shapes, so two components:

1. **Single nullable field** (existing `ToggleNumberField`) — one field that is
   `null` when off and a number when on (e.g. `close_on_profit_pct`,
   `trailing_profit_pct`). Used as-is. No change.

2. **Separate boolean + value fields** (the cool-off controls) — e.g.
   `cooloff_on_success_enabled` (bool) **and** `cooloff_on_success_minutes`
   (number|null) are independent schema fields. A new
   **`ToggleNumberPairField`** wires the checkbox to the `_enabled` boolean and
   reveals the `_minutes` input only when the boolean is true. The `_enabled`
   boolean stays authoritative (it is what the backend reads). On toggling on, the
   minutes field is seeded with a sensible default (e.g. 60) if currently null; on
   toggling off, the boolean goes false (the minutes value may be left as-is or
   nulled — see Open Decisions). The schema is unchanged.

### Cool Off Time — layout

A 2-column stack of self-contained control cards, replacing the scattered grid:

```
COOL OFF TIME

┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ ☑ Cool off after a win  [ 60 ]m │  │ ☐ Cool off after a loss         │
│   pause new entries after a win │  │   pause after a losing cycle    │
└─────────────────────────────────┘  └─────────────────────────────────┘
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ ☐ Cool off after 2 wins         │  │ ☑ Cool off after 2 losses [480]m│
│   2 consecutive wins            │  │   2 consecutive losses          │
└─────────────────────────────────┘  └─────────────────────────────────┘
```

- Pairs: `cooloff_on_success_{enabled,minutes}`,
  `cooloff_on_failure_{enabled,minutes}`,
  `cooloff_on_double_success_{enabled,minutes}`,
  `cooloff_on_double_failure_{enabled,minutes}`.
- Off → no minutes input shown (fixes "dead inputs always visible").
- On → minutes input revealed inline, `1–43200 min` shown as the hint, with the
  field's validation error rendered under it if present.
- Each card visually binds the toggle to its value (fixes "broken pairing").

### Adaptive Blacklist — layout

The `adaptive_blacklist_enabled` checkbox becomes the header of a bordered group.
Its three dependent fields — `adaptive_blacklist_min_trades`,
`adaptive_blacklist_max_win_rate`, `adaptive_blacklist_lookback_hours` — render
**only when enabled**. When disabled, they are hidden (not shown as always-on
inputs). This mirrors the Close Rules duration-limits card (one toggle revealing a
sub-grid of inputs).

> Note: hiding dependent inputs when their toggle is off is purely presentational.
> The underlying field values persist in RHF state while hidden (consistent with
> how `ToggleNumberField` and the draft `getValues()` snapshot already behave), so
> toggling off then on does not silently discard a typed value within a session.

---

## Error Routing Across Tabs

The current code computes per-section error booleans via
`anyError(...fieldPaths)`. These field-path lists are regrouped **by tab** in
`tabMeta.ts` so each tab has an error count derived from the same map used to
render it.

- **Tab badges** — each `TabsTrigger` shows a small red count badge when its tab
  has ≥1 field error (e.g. `Risk & Exits ②`). No badge when clean. Badge has an
  accessible label (e.g. `aria-label="2 errors"`).
- **Auto-switch on failed submit** — the existing invalid-submit handler already
  runs `requestAnimationFrame(() => focus first [aria-invalid="true"])`. It is
  extended to first set the active tab to the **earliest tab in `TAB_ORDER` that
  has an error**, then focus the first invalid control within it. Nothing stays
  hidden on an inactive tab.
- **Summary banner** — the existing red "Fix the highlighted backtest settings"
  banner (with `role="alert"`, listing all errors via `validationMessages`) stays
  above the tab bar, unchanged.
- The removed `Section.forceOpen` behavior is fully replaced by tab-switching:
  previously a collapsed section auto-opened on error; now the errored tab is
  auto-selected and badged.

## Sticky Footer

The action row moves into a footer pinned to the bottom of the form, visible from
any tab:

```
─────────────────────────────────────────────────────────────
   [Reset] [Store Reference] [Reference Config] [Optimized Reference] [ Run Backtest ]
─────────────────────────────────────────────────────────────
```

- `sticky bottom-0` bar using the neu surface background + top border / subtle
  shadow so scrolled content passes cleanly beneath it.
- All five buttons retained (Reset, Store Reference, Reference Config, Optimized
  Reference, Run Backtest) — no overflow menu.
- Keeps the existing `flex-wrap` so it degrades gracefully on narrow widths.
- `Run Backtest` keeps its `isSubmitting` → "Running…" disabled state.

---

## Testing Strategy

**Invariant under test:** identical inputs must yield an identical
`toCreateRequest` payload before and after the redesign. This is the guardrail for
"no semantic change."

Baseline: run the existing `BacktestConfigForm.test.tsx` to confirm green before
refactoring, and keep it passing throughout (TDD — write/adjust tests first each
phase, then refactor to green).

New / updated tests:

1. **Tab navigation** — all 4 tabs render; clicking a trigger switches the visible
   panel; default active tab is `setup`; selecting a tab persists `active_tab` into
   the draft and a re-mount restores it.
2. **Field coverage** — the union of `FIELD_PATHS_BY_TAB` equals the full set of
   schema field paths (no orphaned or duplicated field).
3. **Toggle reveal (single-field)** — `ToggleNumberField` inputs stay hidden when
   off, appear when on (regression guard for the unchanged Close Rules controls).
4. **Toggle reveal (pair-field)** — cool-off minutes input is hidden when its
   `_enabled` is false, appears when true, seeds the default on enable, and the
   `_enabled` boolean and `_minutes` value stay consistent.
5. **Adaptive blacklist group** — the 3 dependent fields are hidden when
   `adaptive_blacklist_enabled` is false and shown when true.
6. **Error routing** — a forced invalid submit targeting a field on a non-active
   tab auto-switches to that tab, renders the tab's count badge, focuses the
   invalid control, and the summary banner still lists the error.
7. **Payload invariance** — a fixed known config (and a couple of toggle
   permutations) produce the same `toCreateRequest` output as a captured snapshot.
8. **Field-helper tests** — keep coverage for the helpers after the move to
   `fields.tsx` (re-point imports; behavior assertions unchanged).

Validation gates before completion (run and read full output):
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npm run test` (at least the backtest form suite)
- `cd frontend && npm run build`

## Implementation Phases

Each phase keeps the form working and tests green (incremental, low-risk):

1. **Extract field helpers** → `config-form/fields.tsx`; re-point imports + tests.
   No UI change.
2. **Tab shell + `tabMeta.ts`** — introduce `<Tabs>` wrapping the *existing*
   sections grouped into 4 tabs; add badges + auto-switch error routing; intro
   moved above tabs. Sections still collapsible at this point (smallest diff to
   prove tabs + routing work).
3. **Move sections into tab components** (`SetupTab`, `StrategyTab`,
   `RiskExitsTab`, `FiltersAdvancedTab`); shell passes props. `Section` simplified
   to flat always-open card; collapse logic removed.
4. **Toggle pattern** — add `ToggleNumberPairField`; convert cool-off to the
   2-column card matrix; convert adaptive-blacklist to a reveal group.
5. **Sticky footer** — move the action row into the pinned footer.
6. **Final review + full validation gates.**

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hidden-when-off inputs drop values from the submitted payload | RHF retains unmounted field values; payload-invariance test (test 7) + the existing `getValues()` draft snapshot guard this. |
| An error on an inactive tab goes unnoticed | Auto-switch to earliest errored tab + per-tab badges + summary banner (three redundant signals). |
| Field accidentally orphaned from all tabs during future edits | Coverage test (test 2) fails if the tab map ≠ schema keys. |
| Cool-off boolean/value desync (toggle on but minutes null, or vice-versa) | `ToggleNumberPairField` owns both; test 4 asserts consistency; `_enabled` stays authoritative for the backend. |
| Draft from before redesign lacks `active_tab` | Falls back to `setup`; additive field only. |
| Large refactor regresses untested behavior | Phase 1 establishes green baseline; every phase re-runs tests; payload invariance pins semantics. |

## Open Decisions (defer to plan, sensible defaults chosen)

- **Cool-off toggle-off value handling:** when a cool-off toggle is switched off,
  leave the `_minutes` value in place (hidden) vs. null it. Default: **leave in
  place** so re-enabling restores the prior value within a session; the `_enabled`
  boolean is what the backend honors, so a stale minutes value is harmless.
- **Badge styling:** exact badge size/color — defer to implementation, using the
  existing `--neu-danger` token and the `badge.tsx` primitive if it fits.

## Success Criteria

- Form renders as 4 lifecycle tabs with a persistent sticky action footer.
- Cool-off and adaptive-blacklist controls use the reveal-when-on pattern; no
  blank dead inputs; each toggle is visually bound to its value.
- Invalid submit routes the user to the errored tab with a visible badge.
- `tsc --noEmit`, the test suite, and `npm run build` all pass.
- `toCreateRequest` output is unchanged for identical inputs (payload invariance
  test passes).
- `BacktestConfigForm.tsx` is a thin shell; tab content lives in focused,
  independently-readable components.





