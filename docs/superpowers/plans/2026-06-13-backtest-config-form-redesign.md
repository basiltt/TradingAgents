# Backtest Config Form UI/UX Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `BacktestConfigForm` into 4 lifecycle tabs with a reveal-when-on toggle pattern, cross-tab error routing, and a sticky action footer — with zero change to submitted form semantics.

**Architecture:** A thin shell component (`BacktestConfigForm.tsx`) owns all react-hook-form state, draft persistence, reference-config callbacks, error routing, and renders a base-ui `<Tabs>` whose four `<TabsContent>` panels are **all `keepMounted`** (so no `Controller` ever unmounts → payload + draft snapshots are structurally unchanged). Each panel renders a focused presentational tab component (`SetupTab`, `StrategyTab`, `RiskExitsTab`, `FiltersAdvancedTab`) that receives `control`/`fieldError`/watched values via props. Shared field helpers move to `config-form/fields.tsx`; a new `ToggleNumberPairField` unifies the cool-off boolean+value pairs onto the reveal-when-on pattern.

**Tech Stack:** React 18 + TypeScript (strict), react-hook-form, zod (v4), `@base-ui/react` Tabs (v1.4.1, `keepMounted` supported), Tailwind + neumorphism design tokens, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-13-backtest-config-form-redesign-design.md`

---

## Key Constraints (read before any task)

1. **Payload invariance is sacred.** `toCreateRequest(parse(values))` must produce identical output for identical inputs, before and after. Guaranteed structurally by `keepMounted` on every panel (no field unmounts) + asserted by a payload test (Task 10).
2. **Schema is frozen.** No edits to `configSchema.ts`. The cool-off cross-field refinements (`*_enabled === true` ⇒ `*_minutes != null`, message "Set a cool-off duration (1–43200 min)") mean `ToggleNumberPairField` MUST seed a non-null minutes value when toggled on, or submit is blocked.
3. **Draft format change is additive only.** Add optional `active_tab?: TabId` to the draft; a draft without it falls back to `"setup"`.
4. **Existing tests are the safety net.** `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx` must stay green except where a task explicitly updates an assertion (Tasks 3, 5, and 8 call these out by name).
5. **Run commands from `frontend/`.** Test: `npm run test`. Type-check: `npx tsc --noEmit`. Build: `npm run build`. Lint: `npm run lint`.
6. **Chunk large edits.** ~150 lines max per Edit/Write tool call; never reduce existing content when moving it.

---

## File Structure

```
frontend/src/components/backtest/
  BacktestConfigForm.tsx          # MODIFY → thin shell: RHF state, intro, summary banner,
                                  #   <Tabs> + badged triggers + keepMounted panels, error
                                  #   routing (active-tab state + auto-switch), sticky footer
  backtestDraft.ts                # MODIFY → BacktestDraft gains optional active_tab
  config-form/
    fields.tsx                    # CREATE → moved verbatim: Hint, NumberField, SelectField,
                                  #   CheckField, ToggleNumberField, HoursListField,
                                  #   SymbolListField, Section (simplified), GRID
    ToggleNumberPairField.tsx     # CREATE → checkbox(_enabled) + revealed (_minutes) input
    tabMeta.ts                    # CREATE → TabId, TAB_ORDER, TAB_LABELS, FIELD_PATHS_BY_TAB
    SetupTab.tsx                  # CREATE → Backtest Setup + Signal Source + Execution Model
    StrategyTab.tsx               # CREATE → Trade Decisions + Market Regime & Strategy
    RiskExitsTab.tsx              # CREATE → Close Rules + Risk Limits + Target Goal
    FiltersAdvancedTab.tsx        # CREATE → Symbol Filters + Advanced (engine-level)
  __tests__/
    BacktestConfigForm.test.tsx   # MODIFY → drop obsolete expand-clicks, add tab nav,
                                  #   error-routing, reveal, and payload-invariance tests
    tabMeta.test.ts               # CREATE → field-coverage + ordering tests
    ToggleNumberPairField.test.tsx# CREATE → reveal/seed/sync behavior
```

**Responsibility boundaries:**
- `fields.tsx` — dumb, reusable field primitives. No tab/form knowledge.
- `tabMeta.ts` — the single source of truth mapping fields→tabs. Both badges and auto-switch derive from it, so they cannot drift.
- Tab components — presentational; given `control`, `fieldError`, and the specific watched values they need. No `useForm`.
- Shell — the only owner of `useForm`, draft, submit, error routing, footer.

---

## Task 1: Extract field helpers into `config-form/fields.tsx`

Pure move + import re-point. No behavior or UI change. Establishes the green baseline and the shared module the tab components will import.

**Files:**
- Create: `frontend/src/components/backtest/config-form/fields.tsx`
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx` (remove the moved helpers, import them instead)

- [ ] **Step 1: Capture the green baseline**

Run: `npm run test -- BacktestConfigForm`
Expected: PASS (all existing tests green). Record the count — it must not drop.

- [ ] **Step 2: Create `fields.tsx` and move the helpers verbatim**

Move these symbols from `BacktestConfigForm.tsx` (lines ~28–412) into the new file **unchanged**, keeping their exact implementations: `Hint`, `NumberField` (+`NumFieldProps`), `SelectField` (+`SelectFieldProps`), `CheckField` (+`CheckFieldProps`), `ToggleNumberField`, `HoursListField`, `SymbolListField`, `Section`, and the `GRID` constant. Preserve the leading import block they depend on. Header of the new file:

```tsx
import * as React from "react";
import { Controller, type Control, type FieldPath } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import type { BacktestConfigFormValues } from "../configSchema";

// (moved verbatim from BacktestConfigForm.tsx — Hint, NumberField, SelectField,
//  CheckField, ToggleNumberField, HoursListField, SymbolListField, Section, GRID)
```

Export every moved symbol: `export function NumberField(...)`, `export function SelectField(...)`, `export function CheckField(...)`, `export function ToggleNumberField(...)`, `export function HoursListField(...)`, `export function SymbolListField(...)`, `export function Section(...)`, `export function Hint(...)`, and `export const GRID = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3";`

- [ ] **Step 3: Re-point `BacktestConfigForm.tsx` to import from `fields.tsx`**

Delete the moved definitions from `BacktestConfigForm.tsx` and add:

```tsx
import {
  Hint,
  NumberField,
  SelectField,
  CheckField,
  ToggleNumberField,
  HoursListField,
  SymbolListField,
  Section,
  GRID,
} from "./config-form/fields";
```

Remove now-unused imports from `BacktestConfigForm.tsx` (e.g. `Label`, `Checkbox` if no longer referenced directly — verify with the type-check in Step 4; `Label`/`Controller` are still used by the inline date and scan_source fields, so keep those).

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS, no errors.

- [ ] **Step 5: Run tests to confirm no regression**

Run: `npm run test -- BacktestConfigForm`
Expected: PASS, same count as Step 1.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/backtest/config-form/fields.tsx frontend/src/components/backtest/BacktestConfigForm.tsx
git commit -m "refactor(backtest): extract config form field helpers into fields.tsx"
```

---

## Task 2: Create `tabMeta.ts` — the field→tab single source of truth

Defines tab ids, order, labels, and which field paths belong to each tab. Built test-first so the coverage invariant (every schema field in exactly one tab) is locked from the start.

**Files:**
- Create: `frontend/src/components/backtest/config-form/tabMeta.ts`
- Test: `frontend/src/components/backtest/__tests__/tabMeta.test.ts`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from "vitest";
import { TAB_ORDER, TAB_LABELS, FIELD_PATHS_BY_TAB } from "../config-form/tabMeta";
import { buildDefaults } from "../configSchema";

describe("tabMeta", () => {
  it("orders the four lifecycle tabs", () => {
    expect(TAB_ORDER).toEqual(["setup", "strategy", "risk", "filters"]);
  });

  it("labels every tab", () => {
    for (const id of TAB_ORDER) expect(TAB_LABELS[id]).toBeTruthy();
  });

  it("assigns every top-level schema field to exactly one tab", () => {
    // scan_source.* is represented by the single top-level key "scan_source".
    const schemaKeys = Object.keys(buildDefaults()).sort();
    const mapped = TAB_ORDER.flatMap((id) => FIELD_PATHS_BY_TAB[id]);
    // No duplicates across tabs.
    expect(new Set(mapped).size).toBe(mapped.length);
    // Union equals the full schema key set (no orphans, no extras).
    expect([...new Set(mapped)].sort()).toEqual(schemaKeys);
  });
});
```

> **Important — carried-but-not-rendered fields.** `buildDefaults()` contains 5
> keys with NO visible input in the current form: `mr_regime`,
> `mr_extreme_min_abs_score`, `regime_staleness_minutes`, `regime_volatile_atr`,
> `regime_trend_ema_dist_pct`. They are part of the submitted payload and ride
> along at their defaults (kept intact by `keepMounted` + the `getValues()` draft
> snapshot). They MUST still be listed in `FIELD_PATHS_BY_TAB` (under `strategy`,
> their domain) or the coverage test fails. They are mapped for accounting/error
> routing only; no task adds UI for them (out of scope — see spec Non-Goals).

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tabMeta`
Expected: FAIL with "Cannot find module '../config-form/tabMeta'".

- [ ] **Step 3: Implement `tabMeta.ts`**

The field list below is the complete top-level key set of `buildDefaults()` (verified against `configSchema.ts:353-429`). `scan_source` is one top-level key. Every key appears exactly once.

```tsx
export type TabId = "setup" | "strategy" | "risk" | "filters";

export const TAB_ORDER: TabId[] = ["setup", "strategy", "risk", "filters"];

export const TAB_LABELS: Record<TabId, string> = {
  setup: "Setup",
  strategy: "Strategy",
  risk: "Risk & Exits",
  filters: "Filters & Advanced",
};

/** Top-level form field paths per tab. The union MUST equal the schema key set
 *  (enforced by tabMeta.test.ts). Used for per-tab error counts + auto-switch. */
export const FIELD_PATHS_BY_TAB: Record<TabId, string[]> = {
  setup: [
    "starting_capital", "date_range_start", "date_range_end",
    "scan_source",
    "simulation_interval", "fee_rate_pct", "slippage_bps",
    "funding_rate_model", "funding_rate_fixed_pct",
  ],
  strategy: [
    "direction", "leverage", "capital_pct", "take_profit_pct", "stop_loss_pct",
    "min_score", "confidence_filter", "signal_sides", "max_trades",
    "execution_mode", "fill_to_max_trades", "skip_if_positions_open",
    // Market Regime & Strategy (F1/F2/F3)
    "regime_filter_enabled", "session_filter_enabled",
    "session_blocked_hours_utc", "session_allowed_hours_utc",
    "btc_vol_filter_enabled", "btc_vol_min_threshold", "btc_vol_max_threshold",
    "btc_vol_interval", "btc_vol_lookback_candles",
    "strategy_cohort", "mean_reversion_enabled",
    "mr_short_enabled", "mr_long_enabled", "mr_leverage", "mr_capital_pct",
    "mr_max_trades", "mr_mean_period", "mr_mean_interval",
    "mr_target_capture_pct", "mr_tight_stop_pct", "mr_time_stop_minutes",
    "mr_min_edge_pct",
    // Carried-but-not-rendered (payload defaults, no UI — see note above).
    "mr_regime", "mr_extreme_min_abs_score", "regime_staleness_minutes",
    "regime_volatile_atr", "regime_trend_ema_dist_pct",
  ],
  risk: [
    "max_drawdown_pct", "smart_drawdown_close", "close_on_profit_pct",
    "breakeven_timeout_hours", "max_trade_duration_hours", "trailing_profit_pct",
    "max_same_direction", "max_signal_age_minutes",
    "target_goal_type", "target_goal_value",
  ],
  filters: [
    "symbol_whitelist", "symbol_blacklist",
    "max_price_drift_pct", "max_same_sector",
    "adaptive_blacklist_enabled", "adaptive_blacklist_min_trades",
    "adaptive_blacklist_max_win_rate", "adaptive_blacklist_lookback_hours",
    "cooloff_on_success_enabled", "cooloff_on_success_minutes",
    "cooloff_on_failure_enabled", "cooloff_on_failure_minutes",
    "cooloff_on_double_success_enabled", "cooloff_on_double_success_minutes",
    "cooloff_on_double_failure_enabled", "cooloff_on_double_failure_minutes",
  ],
};
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- tabMeta`
Expected: PASS. If the coverage assertion fails, the printed diff shows the missing/extra key — add it to (or remove it from) the right tab. Do NOT edit the schema.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/backtest/config-form/tabMeta.ts frontend/src/components/backtest/__tests__/tabMeta.test.ts
git commit -m "feat(backtest): add tabMeta field-to-tab map with coverage test"
```

---

## Task 3: Simplify `Section` to a flat, always-open card

Tabs now handle length, so `Section`'s collapse machinery (`open`/`defaultOpen`/`forceOpen` + the render-time rising-edge logic) is removed. This also removes the `forceOpen`-on-error behavior, which Task 6 replaces with tab auto-switch.

**Files:**
- Modify: `frontend/src/components/backtest/config-form/fields.tsx` (the `Section` moved in Task 1)
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx` (drop now-unused `defaultOpen`/`forceOpen` props at call sites)

- [ ] **Step 1: Replace the `Section` implementation**

Replace the entire `Section` function in `fields.tsx` with this flat version (no state, no collapse):

```tsx
export function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  /** Optional one-line description shown under the section title. */
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4">
      <h3 className="text-sm font-bold text-[var(--neu-text-strong)]">{title}</h3>
      {subtitle ? (
        <p className="mt-1 text-[0.72rem] leading-snug text-[var(--neu-text-muted)]">{subtitle}</p>
      ) : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}
```

This drops the `defaultOpen`, `forceOpen`, and `open`-toggle button. (`React` is still imported in `fields.tsx` for the other helpers, so the import stays.)

- [ ] **Step 2: Remove obsolete `Section` props at every call site**

In `BacktestConfigForm.tsx`, delete `defaultOpen={...}` and `forceOpen={...}` from all `<Section>` usages (Close Rules, Risk Limits, Symbol Filters, Target Goal, Advanced, Market Regime). The `*HasError` consts (`closeRulesHasError`, `riskLimitsHasError`, `targetGoalHasError`, `advancedHasError`, `regimeHasError`) are now unused by `Section` — KEEP them; Task 6 reuses the same `anyError(...)` pattern for tab badges. (If lint flags them as unused at this step, that is expected and resolved in Task 6; do not delete them.)

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Update the section-expand tests (they no longer need clicks)**

Several existing tests click a section header to expand it; with always-open sections the click is unnecessary but harmless (the header is now an `<h3>`, not a button). The clicks WILL break because `getByText("Close Rules")` resolves to a non-clickable heading and the subsequent `getByText("Trailing profit stop")` is already present. Update these tests in `__tests__/BacktestConfigForm.test.tsx` by REMOVING the now-obsolete expand clicks:
- In "toggling a close-rule switch off submits null...": remove `fireEvent.click(screen.getByText("Close Rules"));`
- In "exposes the advanced engine-level and target-goal config sections": remove `fireEvent.click(screen.getByText("Advanced (engine-level)"));`
- In "exposes the regime section...": remove `fireEvent.click(screen.getByText("Market Regime & Strategy (F1/F2/F3)"));`

> NOTE: These same tests are revisited in Task 5 (tab wrapping) and Task 7 (toggle reveal). At THIS task they pass because all sections render in one flow still (tabs not added yet). Leave the field-presence assertions intact.

- [ ] **Step 5: Run tests**

Run: `npm run test -- BacktestConfigForm`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/backtest/config-form/fields.tsx frontend/src/components/backtest/BacktestConfigForm.tsx frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx
git commit -m "refactor(backtest): flatten Section to always-open card"
```

---

## Task 4: Extract the four tab components

Move each section's JSX out of `BacktestConfigForm.tsx` into a focused presentational component. The shell will render them inside tab panels in Task 5; at this task they are extracted and rendered in the same linear order so tests still pass (no tabs yet).

**Files:**
- Create: `frontend/src/components/backtest/config-form/SetupTab.tsx`
- Create: `frontend/src/components/backtest/config-form/StrategyTab.tsx`
- Create: `frontend/src/components/backtest/config-form/RiskExitsTab.tsx`
- Create: `frontend/src/components/backtest/config-form/FiltersAdvancedTab.tsx`
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx`

- [ ] **Step 1: Define the shared tab-props contract**

Each tab is presentational and receives what it renders. Create `config-form/tabProps.ts` with the shared base type and import it in all four tab files:

```tsx
// config-form/tabProps.ts
import type { Control } from "react-hook-form";
import type { BacktestConfigFormValues } from "../configSchema";

export interface TabProps {
  control: Control<BacktestConfigFormValues>;
  fieldError: (path: string) => string | undefined;
}
```

> **Type sources (verified):** `ScheduleOption` is currently declared INSIDE
> `BacktestConfigForm.tsx` (`export interface ScheduleOption { value: string; label: string }`).
> Move this declaration into `config-form/tabProps.ts` and export it from there;
> re-import it in `BacktestConfigForm.tsx` so the prop type is unchanged. The
> accounts prop is typed `DashboardCard[]` from `@/api/client` (NOT a custom
> "AccountOption"). Use `DashboardCard` directly.

`SetupTab`, `StrategyTab`, and `RiskExitsTab` need a few extra props for their conditional UI; declare those as explicit extensions (shown per-tab below).

- [ ] **Step 2: Create `SetupTab.tsx`**

`SetupTab` owns Backtest Setup + Signal Source + Execution Model. Signal Source has conditional sub-fields keyed off `scanMode`, and needs the `schedules`/`accounts` props plus `replayAccountId`. Props:

```tsx
import * as React from "react";
import { Controller } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { DashboardCard } from "@/api/client";
import { NumberField, SelectField, Section, Hint, GRID } from "./fields";
import type { TabProps, ScheduleOption } from "./tabProps";

interface SetupTabProps extends TabProps {
  schedules: ScheduleOption[];
  accounts: DashboardCard[];
  scanMode: string | undefined;
  replayAccountId: string | undefined | null;
}

export function SetupTab({ control, fieldError, schedules, accounts, scanMode, replayAccountId }: SetupTabProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* MOVE the three <Section> blocks verbatim from BacktestConfigForm.tsx:
          - "Backtest Setup (backtest-only)"   (lines ~720-761)
          - "Signal Source (backtest-only)"    (lines ~763-856)
          - "Execution Model (backtest-only)"  (lines ~858-877)
          Keep ALL inner JSX, hints, error spans, and conditional blocks exactly. */}
    </div>
  );
}
```

- [ ] **Step 3: Create `StrategyTab.tsx`**

`StrategyTab` owns Trade Decisions + Market Regime & Strategy. It needs `mrLongEnabled` (to show the danger note). Props:

```tsx
import { CheckField, NumberField, SelectField, HoursListField, Section, GRID } from "./fields";
import type { TabProps } from "./tabProps";

interface StrategyTabProps extends TabProps {
  mrLongEnabled: boolean | undefined;
}

export function StrategyTab({ control, fieldError, mrLongEnabled }: StrategyTabProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* MOVE verbatim:
          - "Trade Decisions" <Section> (lines ~879-914)
          - "Market Regime & Strategy (F1/F2/F3)" <Section> (lines ~1019-1080),
            INCLUDING the mrLongEnabled danger <p data-testid="mr-long-danger">. */}
    </div>
  );
}
```

- [ ] **Step 4: Create `RiskExitsTab.tsx`**

`RiskExitsTab` owns Close Rules + Risk Limits + Target Goal. Close Rules has the duration-limits card driven by `durationLimitsOn` + `setValue`. Props:

```tsx
import { Checkbox } from "@/components/ui/checkbox";
import { CheckField, NumberField, SelectField, ToggleNumberField, Section, Hint, GRID } from "./fields";
import type { UseFormSetValue } from "react-hook-form";
import type { BacktestConfigFormValues } from "../configSchema";
import type { TabProps } from "./tabProps";

interface RiskExitsTabProps extends TabProps {
  durationLimitsOn: boolean;
  setValue: UseFormSetValue<BacktestConfigFormValues>;
}

export function RiskExitsTab({ control, fieldError, durationLimitsOn, setValue }: RiskExitsTabProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* MOVE verbatim:
          - "Close Rules" <Section> (lines ~916-952) INCLUDING the duration-limits
            bordered card that calls setValue("breakeven_timeout_hours"/"max_trade_duration_hours").
          - "Risk Limits" <Section> (lines ~954-959)
          - "Target Goal" <Section> (lines ~968-980) */}
    </div>
  );
}
```

- [ ] **Step 5: Create `FiltersAdvancedTab.tsx`**

`FiltersAdvancedTab` owns Symbol Filters + Advanced (engine-level). For THIS task, move the Advanced section's CURRENT markup verbatim (it gets the toggle-pattern redesign in Task 7). Props are the base `TabProps` only.

```tsx
import { CheckField, NumberField, SymbolListField, Section, GRID } from "./fields";
import type { TabProps } from "./tabProps";

export function FiltersAdvancedTab({ control, fieldError }: TabProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* MOVE verbatim:
          - "Symbol Filters" <Section> (lines ~961-966)
          - "Advanced (engine-level)" <Section> (lines ~982-1017) — current markup,
            redesigned in Task 7. */}
    </div>
  );
}
```

- [ ] **Step 6: Render the tab components from the shell (linear, no tabs yet)**

In `BacktestConfigForm.tsx`, replace the moved `<Section>` blocks with the four components in the SAME visual order, passing the watched values the shell already computes (`scanMode`, `replayAccountId`, `mrLongEnabled`, `durationLimitsOn`, `setValue`):

```tsx
<SetupTab control={control} fieldError={fieldError} schedules={schedules} accounts={accounts} scanMode={scanMode} replayAccountId={replayAccountId} />
<StrategyTab control={control} fieldError={fieldError} mrLongEnabled={mrLongEnabled} />
<RiskExitsTab control={control} fieldError={fieldError} durationLimitsOn={durationLimitsOn} setValue={setValue} />
<FiltersAdvancedTab control={control} fieldError={fieldError} />
```

Add the imports at the top of `BacktestConfigForm.tsx`. Remove field-helper imports the shell no longer uses directly (keep `Controller`, `Input`, `Label` only if still referenced — after the move the shell should reference almost none; verify with tsc).

- [ ] **Step 7: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS. Fix any prop-type mismatches against the existing inline types.

- [ ] **Step 8: Run tests**

Run: `npm run test -- BacktestConfigForm`
Expected: PASS (everything still renders linearly; assertions unchanged from Task 3).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/backtest/config-form/ frontend/src/components/backtest/BacktestConfigForm.tsx
git commit -m "refactor(backtest): split form sections into four tab components"
```

---

## Task 5: Wrap tab components in `<Tabs>` with keepMounted panels + active-tab persistence

Introduce the 4-tab UI. **Every panel is `keepMounted`** so no `Controller` unmounts — this is what guarantees payload + draft invariance. Active tab persists into the draft.

**Files:**
- Modify: `frontend/src/components/backtest/backtestDraft.ts` (add `active_tab`)
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx`

- [ ] **Step 1: Add `active_tab` to the draft type (additive, backward-compatible)**

In `backtestDraft.ts`, extend the draft type. It currently is `export type BacktestDraft = Partial<BacktestConfigFormValues>;`. Replace with:

```tsx
import type { TabId } from "./config-form/tabMeta";

/** A partial snapshot — the form may persist before every field is touched, and
 * the schema can gain fields a stale draft predates. buildDefaults() backfills
 * anything missing, so a partial is always safe to restore. `active_tab` is a
 * UI-only addition (not a schema field); a draft predating it falls back to setup. */
export type BacktestDraft = Partial<BacktestConfigFormValues> & { active_tab?: TabId };
```

No other change to this file (load/save already JSON round-trip arbitrary keys).

- [ ] **Step 2: Write the failing tab-navigation test**

Add to `__tests__/BacktestConfigForm.test.tsx`:

```tsx
it("renders four lifecycle tabs and defaults to Setup", () => {
  render(<BacktestConfigForm onSubmit={vi.fn()} />);
  expect(screen.getByRole("tab", { name: /setup/i })).toHaveAttribute("data-active");
  expect(screen.getByRole("tab", { name: /strategy/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /risk & exits/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /filters & advanced/i })).toBeInTheDocument();
});

it("switches tabs on click and persists the active tab to the draft", async () => {
  render(<BacktestConfigForm onSubmit={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /risk & exits/i }));
  await waitFor(() => {
    const raw = localStorage.getItem("tradingagents_backtest_draft");
    expect(JSON.parse(raw ?? "{}").active_tab).toBe("risk");
  });
});

it("restores the active tab from a saved draft on remount", async () => {
  const { unmount } = render(<BacktestConfigForm onSubmit={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /strategy/i }));
  await waitFor(() =>
    expect(JSON.parse(localStorage.getItem("tradingagents_backtest_draft") ?? "{}").active_tab).toBe("strategy"),
  );
  unmount();
  render(<BacktestConfigForm onSubmit={vi.fn()} />);
  await waitFor(() =>
    expect(screen.getByRole("tab", { name: /strategy/i })).toHaveAttribute("data-active"),
  );
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm run test -- BacktestConfigForm`
Expected: FAIL (no `tab` roles yet).

- [ ] **Step 4: Add active-tab state seeded from the draft**

In `BacktestConfigForm.tsx`, near the other `useState`/`watch` setup, add (the draft was already read into `initialValues` via `loadDraft()`; read the tab from the same draft):

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { TAB_ORDER, TAB_LABELS, FIELD_PATHS_BY_TAB, type TabId } from "./config-form/tabMeta";

// inside the component, alongside initialValues:
const initialTab = React.useMemo<TabId>(() => {
  const draft = seed ? undefined : loadDraft();
  const t = draft?.active_tab;
  return t && TAB_ORDER.includes(t) ? t : "setup";
  // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-time only
}, []);
const [activeTab, setActiveTab] = React.useState<TabId>(initialTab);
```

- [ ] **Step 5: Persist the active tab into the draft when it changes**

The form already persists `getValues()` via `watch`. Add a small effect so tab changes are saved too (merging into the existing draft, not clobbering field values):

```tsx
React.useEffect(() => {
  saveDraft({ ...(getValues() as BacktestDraft), active_tab: activeTab });
}, [activeTab, getValues]);
```

> NOTE: the existing `watch(() => saveDraft(getValues()))` does NOT include
> `active_tab`. To avoid a later field-change overwriting the saved tab, update that
> existing subscription to spread the current tab too. Change its body to:
> `saveDraft({ ...(getValues() as BacktestDraft), active_tab: activeTabRef.current });`
> where `activeTabRef` is a `React.useRef(activeTab)` kept in sync via
> `activeTabRef.current = activeTab;` on each render. This keeps the non-rendering
> subscription correct without re-subscribing. (Ref pattern avoids a stale closure.)

- [ ] **Step 6: Render the Tabs structure**

Replace the four linear tab-component renders (from Task 4 Step 6) with the tabbed layout. The intro banner stays ABOVE the tab bar; the summary banner stays above that. All panels `keepMounted`:

```tsx
<Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as TabId)}>
  <TabsList>
    {TAB_ORDER.map((id) => (
      <TabsTrigger key={id} value={id}>
        {TAB_LABELS[id]}
        {/* error badge added in Task 6 */}
      </TabsTrigger>
    ))}
  </TabsList>

  <TabsContent value="setup" keepMounted>
    <SetupTab control={control} fieldError={fieldError} schedules={schedules} accounts={accounts} scanMode={scanMode} replayAccountId={replayAccountId} />
  </TabsContent>
  <TabsContent value="strategy" keepMounted>
    <StrategyTab control={control} fieldError={fieldError} mrLongEnabled={mrLongEnabled} />
  </TabsContent>
  <TabsContent value="risk" keepMounted>
    <RiskExitsTab control={control} fieldError={fieldError} durationLimitsOn={durationLimitsOn} setValue={setValue} />
  </TabsContent>
  <TabsContent value="filters" keepMounted>
    <FiltersAdvancedTab control={control} fieldError={fieldError} />
  </TabsContent>
</Tabs>
```

> `keepMounted` keeps hidden panels in the DOM (base-ui sets `hidden` on them).
> This is REQUIRED: it means every `Controller` stays mounted, so `getValues()`
> always returns the full form and `toCreateRequest` is unaffected by which tab is
> visible. It also keeps existing cross-tab `getByLabelText` test queries working.

- [ ] **Step 7: Reconcile the "renders the major sections" test**

The existing test "renders the major sections" asserts Backtest Setup + Signal Source + Execution Model + Trade Decisions are all present. With `keepMounted`, hidden panels remain in the DOM, so `getByText`/`getByLabelText` still resolve — this test should PASS unchanged. Run it specifically to confirm:

Run: `npm run test -- BacktestConfigForm -t "renders the major sections"`
Expected: PASS. If a hidden-panel query fails because base-ui marks content `hidden`, switch that assertion from `getByText` to `screen.getByText(..., { ignore: false })` is NOT needed — instead query by role/label which ignores `hidden` only for accessibility; if truly hidden, the test should click the owning tab first. Prefer: keep `keepMounted` and assert presence in the DOM via `screen.getByText(...)` (Testing Library finds `hidden` text nodes by default).

- [ ] **Step 8: Run the full form suite**

Run: `npm run test -- BacktestConfigForm`
Expected: PASS (new tab tests + all prior tests).

- [ ] **Step 9: Type-check + commit**

Run: `npx tsc --noEmit` → PASS

```bash
git add frontend/src/components/backtest/BacktestConfigForm.tsx frontend/src/components/backtest/backtestDraft.ts frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx
git commit -m "feat(backtest): organize config form into four lifecycle tabs"
```

---

## Task 6: Cross-tab error routing — per-tab badges + auto-switch on failed submit

Errors on inactive tabs must surface. Derive per-tab error counts from `FIELD_PATHS_BY_TAB`, badge the triggers, and on a failed submit switch to the earliest errored tab before focusing the invalid field.

**Files:**
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx`

- [ ] **Step 1: Write the failing error-routing test**

The existing "blocks submit and shows error when end is before start" test proves a Setup-tab error. Add a test that an error on a NON-active tab auto-switches and badges. The cool-off "enabled but blank" refinement is a reliable Filters-tab error trigger, but simpler: an out-of-range Leverage (Strategy tab). Add:

```tsx
it("auto-switches to the errored tab and badges it on failed submit", async () => {
  const onSubmit = vi.fn();
  render(<BacktestConfigForm onSubmit={onSubmit} />);
  // Start on Setup. Put an invalid value on the Strategy tab's Leverage (min 1, max 125).
  // keepMounted means the Strategy field is reachable without switching first.
  fireEvent.change(screen.getByLabelText("Leverage"), { target: { value: "9999" } });
  fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
  // Auto-switches to Strategy.
  await waitFor(() =>
    expect(screen.getByRole("tab", { name: /strategy/i })).toHaveAttribute("data-active"),
  );
  // Strategy tab shows an error count badge.
  expect(screen.getByRole("tab", { name: /strategy/i })).toHaveTextContent(/1|•/);
  expect(onSubmit).not.toHaveBeenCalled();
});
```

> Verify Leverage's bounds in `configSchema.ts` (it is `int().min(1).max(125)`).
> 9999 fails `max(125)`. If the bound differs, use a value that clearly violates it.

- [ ] **Step 2: Run to verify failure**

Run: `npm run test -- BacktestConfigForm -t "auto-switches"`
Expected: FAIL (no badge / no auto-switch yet).

- [ ] **Step 3: Compute per-tab error counts**

In `BacktestConfigForm.tsx`, add a helper that counts errors per tab using the existing `fieldError` + `FIELD_PATHS_BY_TAB`. A field with a nested error (e.g. `scan_source`) counts if any of its dotted children error; `fieldError("scan_source")` only matches a root error, so check the prefix:

```tsx
const tabErrorCount = React.useCallback(
  (id: TabId): number =>
    FIELD_PATHS_BY_TAB[id].reduce((n, path) => {
      // Direct match OR any nested child (scan_source.mode, scan_source.schedule_id…).
      const hasError =
        !!fieldError(path) ||
        validationMessages.some((m) => false) /* placeholder removed below */;
      return n + (hasError ? 1 : 0);
    }, 0),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [errors],
);
```

Replace the placeholder approach with a direct nested-error check against the RHF `errors` object. Simpler and correct:

```tsx
const fieldHasError = React.useCallback(
  (path: string): boolean => {
    // True if `path` or any nested descendant under it has a message.
    const parts = path.split(".");
    let node: unknown = errors;
    for (const p of parts) {
      if (node && typeof node === "object" && p in node) node = (node as Record<string, unknown>)[p];
      else return false;
    }
    if (!node || typeof node !== "object") return false;
    // node may be a leaf {message} or a subtree (scan_source) — detect any message within.
    let found = false;
    const visit = (n: unknown) => {
      if (found || !n || typeof n !== "object") return;
      if (typeof (n as { message?: unknown }).message === "string") { found = true; return; }
      for (const [k, v] of Object.entries(n as Record<string, unknown>)) {
        if (k === "ref" || k === "types") continue;
        visit(v);
      }
    };
    visit(node);
    return found;
  },
  [errors],
);

const tabErrorCount = React.useCallback(
  (id: TabId): number => FIELD_PATHS_BY_TAB[id].reduce((n, p) => n + (fieldHasError(p) ? 1 : 0), 0),
  [fieldHasError],
);
```

- [ ] **Step 4: Render the badge in each trigger**

Update the `TabsTrigger` map from Task 5 to show a count badge when `tabErrorCount(id) > 0`:

```tsx
<TabsTrigger key={id} value={id} className="gap-2">
  {TAB_LABELS[id]}
  {tabErrorCount(id) > 0 ? (
    <span
      aria-label={`${tabErrorCount(id)} ${tabErrorCount(id) === 1 ? "error" : "errors"}`}
      className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--neu-danger)] px-1.5 text-[0.65rem] font-bold leading-none text-white"
    >
      {tabErrorCount(id)}
    </span>
  ) : null}
</TabsTrigger>
```

- [ ] **Step 5: Auto-switch to the first errored tab on invalid submit**

The existing invalid-submit handler (second arg to `handleSubmit`) runs a `requestAnimationFrame` focus. Extend it to first select the earliest errored tab. The handler runs AFTER `errors` is populated, so compute the target from `errors` directly:

```tsx
const submit = handleSubmit(
  (values) => {
    const parsed = backtestConfigSchema.parse(values);
    onSubmit(toCreateRequest(parsed));
  },
  () => {
    // Switch to the earliest tab (lifecycle order) that has an error, then focus.
    const target = TAB_ORDER.find((id) => tabErrorCount(id) > 0);
    if (target) setActiveTab(target);
    requestAnimationFrame(() => {
      const el =
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
        summaryRef.current;
      el?.focus();
    });
  },
);
```

> `tabErrorCount` reads the latest `errors` via the `fieldHasError` closure; in the
> error callback, RHF has already set `errors`, so the counts are current. With
> `keepMounted`, the target tab's invalid control is in the DOM, so the
> `requestAnimationFrame` focus lands correctly even right after the tab switch.

- [ ] **Step 6: Run the test**

Run: `npm run test -- BacktestConfigForm -t "auto-switches"`
Expected: PASS.

- [ ] **Step 7: Full suite + type-check**

Run: `npm run test -- BacktestConfigForm` → PASS
Run: `npx tsc --noEmit` → PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/backtest/BacktestConfigForm.tsx frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx
git commit -m "feat(backtest): route validation errors to tabs with badges + auto-switch"
```

---

## Task 7: `ToggleNumberPairField` + redesign cool-off & adaptive-blacklist (core fix)

The headline UX fix. Build a reveal-when-on component for the boolean+value cool-off pairs, then rebuild the Advanced section so no dead inputs show and every toggle is bound to its value.

**Files:**
- Create: `frontend/src/components/backtest/config-form/ToggleNumberPairField.tsx`
- Test: `frontend/src/components/backtest/__tests__/ToggleNumberPairField.test.tsx`
- Modify: `frontend/src/components/backtest/config-form/FiltersAdvancedTab.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx` (the advanced-section test)

- [ ] **Step 1: Write the failing `ToggleNumberPairField` test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { ToggleNumberPairField } from "../config-form/ToggleNumberPairField";

function Harness({ enabled = false, minutes = null }: { enabled?: boolean; minutes?: number | null }) {
  const { control } = useForm({
    defaultValues: { cooloff_on_success_enabled: enabled, cooloff_on_success_minutes: minutes },
  });
  return (
    <ToggleNumberPairField
      control={control as never}
      enabledName={"cooloff_on_success_enabled" as never}
      valueName={"cooloff_on_success_minutes" as never}
      title="Cool off after a win"
      description="pause new entries after a winning cycle"
      enabledValue={60}
      unit="min"
    />
  );
}

describe("ToggleNumberPairField", () => {
  it("hides the value input when the toggle is off", () => {
    render(<Harness enabled={false} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("reveals the value input and seeds the default when toggled on", () => {
    render(<Harness enabled={false} />);
    fireEvent.click(screen.getByRole("checkbox"));
    const input = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("60");
  });

  it("shows the existing value when mounted already-enabled", () => {
    render(<Harness enabled={true} minutes={480} />);
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("480");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm run test -- ToggleNumberPairField`
Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `ToggleNumberPairField`**

Wires the checkbox to the `_enabled` boolean and reveals the `_minutes` input only when enabled. On enable, seeds `enabledValue` into the value field if it is currently null (required: the schema refines `enabled ⇒ minutes != null`). Mirrors `ToggleNumberField`'s visual structure.

```tsx
import { Controller, type Control, type FieldPath } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Hint } from "./fields";
import type { BacktestConfigFormValues } from "../configSchema";

interface ToggleNumberPairFieldProps {
  control: Control<BacktestConfigFormValues>;
  enabledName: FieldPath<BacktestConfigFormValues>;
  valueName: FieldPath<BacktestConfigFormValues>;
  title: string;
  description?: string;
  /** Seeded into the value field when toggled on (if currently null). */
  enabledValue: number;
  unit?: string;
  min?: number;
  max?: number;
  error?: string;
}

export function ToggleNumberPairField({
  control, enabledName, valueName, title, description, enabledValue, unit, min, max, error,
}: ToggleNumberPairFieldProps) {
  return (
    <div className="rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
      <Controller
        control={control}
        name={enabledName}
        render={({ field: enabledField }) => {
          const enabled = enabledField.value === true;
          return (
            <Controller
              control={control}
              name={valueName}
              render={({ field: valueField }) => (
                <div className="flex items-start justify-between gap-3">
                  <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
                    <Checkbox
                      checked={enabled}
                      onCheckedChange={(checked) => {
                        const on = checked === true;
                        enabledField.onChange(on);
                        // Seed a default so the schema's "enabled ⇒ minutes != null" holds.
                        if (on && (valueField.value == null || valueField.value === "")) {
                          valueField.onChange(enabledValue);
                        }
                      }}
                      className="mt-0.5"
                    />
                    <span className="flex flex-col">
                      {title}
                      {description ? <Hint text={description} /> : null}
                    </span>
                  </label>
                  {enabled ? (
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="number"
                          min={min}
                          max={max}
                          step="any"
                          value={valueField.value == null ? "" : String(valueField.value)}
                          onChange={(e) => {
                            const v = e.target.value;
                            valueField.onChange(v === "" ? null : v);
                          }}
                          onBlur={valueField.onBlur}
                          aria-invalid={!!error}
                          className="h-10 w-20 text-center"
                        />
                        {unit ? <span className="text-[0.72rem] text-[var(--neu-text-muted)]">{unit}</span> : null}
                      </div>
                      {error ? <span className="text-[0.72rem] text-[var(--neu-danger)]">{error}</span> : null}
                    </div>
                  ) : null}
                </div>
              )}
            />
          );
        }}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- ToggleNumberPairField`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit the new field component**

```bash
git add frontend/src/components/backtest/config-form/ToggleNumberPairField.tsx frontend/src/components/backtest/__tests__/ToggleNumberPairField.test.tsx
git commit -m "feat(backtest): add ToggleNumberPairField reveal-when-on control"
```

---

## Task 8: Rebuild the Advanced section with reveal-when-on grouping

Replace the scattered cool-off grid and always-visible adaptive-blacklist inputs in `FiltersAdvancedTab` with the new pattern: a 2-column cool-off matrix and a blacklist reveal group.

**Files:**
- Modify: `frontend/src/components/backtest/config-form/FiltersAdvancedTab.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx`

- [ ] **Step 1: Update the failing advanced-section test**

The existing test "exposes the advanced engine-level and target-goal config sections" asserts `Min trades`, `Max win rate %`, `Lookback (hours)` are present by default. After the redesign these hide until the adaptive-blacklist toggle is on. Update that test to reflect the reveal behavior:

```tsx
it("exposes the advanced engine-level and target-goal config sections", () => {
  render(<BacktestConfigForm onSubmit={vi.fn()} />);
  // Target Goal lives on the Risk & Exits tab; Advanced lives on Filters & Advanced.
  // keepMounted keeps both in the DOM, so headings resolve without switching tabs.
  expect(screen.getByText("Advanced (engine-level)")).toBeInTheDocument();
  expect(screen.getByText("Target Goal")).toBeInTheDocument();
  // Adaptive-blacklist dependent fields are HIDDEN until the toggle is enabled.
  expect(screen.queryByLabelText("Min trades")).toBeNull();
  // Enabling the blacklist reveals them.
  fireEvent.click(screen.getByText("Enable adaptive blacklist"));
  expect(screen.getByLabelText("Min trades")).toBeInTheDocument();
  expect(screen.getByLabelText("Max win rate %")).toBeInTheDocument();
  expect(screen.getByLabelText("Lookback (hours)")).toBeInTheDocument();
});

it("hides cool-off duration inputs until their tier is enabled", () => {
  render(<BacktestConfigForm onSubmit={vi.fn()} />);
  // No cool-off minutes input visible by default (all tiers off).
  expect(screen.queryByText("Win cool off (min)")).toBeNull();
  // Enabling a tier reveals an inline minutes input seeded with a default.
  fireEvent.click(screen.getByText("Cool off after a win"));
  const inputs = screen.getAllByRole("spinbutton");
  expect(inputs.length).toBeGreaterThan(0);
});
```

> The adaptive-blacklist checkbox label text is "Enable adaptive blacklist"; the
> win cool-off label is "Cool off after a win" (verified in current markup). The
> neu `Checkbox` duplicates its label text, so click the visible label via
> `getByText`, matching the existing regime test's approach.

- [ ] **Step 2: Run to verify failure**

Run: `npm run test -- BacktestConfigForm -t "advanced engine-level"`
Expected: FAIL (fields still always-visible from the verbatim move in Task 4).

- [ ] **Step 3: Rebuild the Advanced section JSX**

In `FiltersAdvancedTab.tsx`, replace the Advanced `<Section>` body (the verbatim block moved in Task 4) with this. Keep the Symbol Filters section above it unchanged. Add the `ToggleNumberPairField` import.

```tsx
import { CheckField, NumberField, SymbolListField, Section, GRID } from "./fields";
import { ToggleNumberPairField } from "./ToggleNumberPairField";
import { Controller } from "react-hook-form";
import { Checkbox } from "@/components/ui/checkbox";
import { Hint } from "./fields";
import type { TabProps } from "./tabProps";

// ... inside the Advanced <Section>:
<Section
  title="Advanced (engine-level)"
  subtitle="Auto-trade engine features that are NOT shown in the scanner's config form. They still affect the backtest unless marked not-simulated."
>
  <div className={GRID}>
    <NumberField control={control} name="max_price_drift_pct" label="Max price drift %" nullable hint="Engine-level · skip a signal if price moved this % since the scan" error={fieldError("max_price_drift_pct")} />
    <NumberField control={control} name="max_same_sector" label="Max positions same sector" nullable hint="Not simulated · sector data is live-only, no effect on results" error={fieldError("max_same_sector")} />
  </div>

  {/* Adaptive blacklist — reveal group: checkbox header + dependent fields shown only when on. */}
  <div className="mt-4 rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)]/40 px-3 py-2.5">
    <Controller
      control={control}
      name="adaptive_blacklist_enabled"
      render={({ field }) => {
        const on = field.value === true;
        return (
          <>
            <label className="flex cursor-pointer items-start gap-2.5 text-[0.85rem] text-[var(--neu-text-strong)]">
              <Checkbox checked={on} onCheckedChange={(c) => field.onChange(c === true)} className="mt-0.5" />
              <span className="flex flex-col">
                Enable adaptive blacklist
                <Hint text="Engine-level · auto-skip symbols whose recent win rate is poor" />
              </span>
            </label>
            {on ? (
              <div className={`${GRID} mt-3`}>
                <NumberField control={control} name="adaptive_blacklist_min_trades" label="Min trades" hint="Engine-level · min trades before blacklisting" error={fieldError("adaptive_blacklist_min_trades")} />
                <NumberField control={control} name="adaptive_blacklist_max_win_rate" label="Max win rate %" hint="Engine-level · blacklist below this win rate" error={fieldError("adaptive_blacklist_max_win_rate")} />
                <NumberField control={control} name="adaptive_blacklist_lookback_hours" label="Lookback (hours)" hint="Engine-level · win-rate lookback window" error={fieldError("adaptive_blacklist_lookback_hours")} />
              </div>
            ) : null}
          </>
        );
      }}
    />
  </div>

  {/* Cool Off Time — 2-column matrix of self-contained reveal-when-on cards. */}
  <div className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
    Cool Off Time
  </div>
  <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
    <ToggleNumberPairField control={control} enabledName="cooloff_on_success_enabled" valueName="cooloff_on_success_minutes" title="Cool off after a win" description="pause new entries after a winning cycle" enabledValue={60} unit="min" error={fieldError("cooloff_on_success_minutes")} />
    <ToggleNumberPairField control={control} enabledName="cooloff_on_failure_enabled" valueName="cooloff_on_failure_minutes" title="Cool off after a loss" description="pause after a losing cycle" enabledValue={60} unit="min" error={fieldError("cooloff_on_failure_minutes")} />
    <ToggleNumberPairField control={control} enabledName="cooloff_on_double_success_enabled" valueName="cooloff_on_double_success_minutes" title="Cool off after 2 wins" description="2 consecutive wins" enabledValue={120} unit="min" error={fieldError("cooloff_on_double_success_minutes")} />
    <ToggleNumberPairField control={control} enabledName="cooloff_on_double_failure_enabled" valueName="cooloff_on_double_failure_minutes" title="Cool off after 2 losses" description="2 consecutive losses" enabledValue={480} unit="min" error={fieldError("cooloff_on_double_failure_minutes")} />
  </div>
</Section>
```

> The four `enabledValue` seeds (60/60/120/480) are sensible defaults within the
> `1–43200` range. They only seed when the field is currently null, so a draft's
> stored value is preserved.

- [ ] **Step 4: Run the advanced tests**

Run: `npm run test -- BacktestConfigForm -t "advanced engine-level"`
Run: `npm run test -- BacktestConfigForm -t "cool-off duration"`
Expected: PASS both.

- [ ] **Step 5: Full suite + type-check**

Run: `npm run test -- BacktestConfigForm` → PASS
Run: `npx tsc --noEmit` → PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/backtest/config-form/FiltersAdvancedTab.tsx frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx
git commit -m "feat(backtest): redesign cool-off + adaptive-blacklist with reveal-when-on"
```

---

## Task 9: Sticky action footer

Pin the action row to the bottom so Run Backtest is reachable from any tab.

**Files:**
- Modify: `frontend/src/components/backtest/BacktestConfigForm.tsx`

- [ ] **Step 1: Wrap the existing action row in a sticky footer**

The action row (Reset / Store Reference / Reference Config / Optimized Reference / Run Backtest) is the last block in the form. Wrap it so it sticks to the bottom of the scroll container, with the neu surface behind it and a top divider so content scrolls under cleanly. Replace the current closing action `<div>` with:

```tsx
<div className="sticky bottom-0 z-10 -mx-1 mt-2 flex flex-wrap items-center justify-end gap-3 border-t border-[color:var(--neu-stroke-soft)]/50 bg-[var(--neu-surface-base)]/95 px-1 py-3 backdrop-blur supports-[backdrop-filter]:bg-[var(--neu-surface-base)]/80">
  <Button type="button" variant="outline" onClick={resetForm} disabled={isSubmitting}>Reset</Button>
  <Button type="button" variant="outline" onClick={storeReferenceConfig} disabled={isSubmitting}>Store Reference</Button>
  <Button type="button" variant="secondary" onClick={applyDadDemoReference} disabled={isSubmitting}>Reference Config</Button>
  <Button type="button" variant="secondary" onClick={applyOptimizedReference} disabled={isSubmitting}>Optimized Reference</Button>
  <Button type="submit" disabled={isSubmitting}>{isSubmitting ? "Running…" : "Run Backtest"}</Button>
</div>
```

> The footer is inside the `<form>`, so `type="submit"` still submits. `z-10`
> keeps it above scrolled content; the translucent background + `backdrop-blur`
> matches the neu surface aesthetic. `-mx-1`/`px-1` lets it span the form's padding
> edge without a visible gap.

- [ ] **Step 2: Verify the submit-disabled test still passes**

Run: `npm run test -- BacktestConfigForm -t "disables the submit button"`
Expected: PASS (the button is the same, just relocated).

- [ ] **Step 3: Full suite + type-check + commit**

Run: `npm run test -- BacktestConfigForm` → PASS
Run: `npx tsc --noEmit` → PASS

```bash
git add frontend/src/components/backtest/BacktestConfigForm.tsx
git commit -m "feat(backtest): pin config form actions to a sticky footer"
```

---

## Task 10: Payload-invariance guard + full validation gates

Lock the "no semantic change" promise with a snapshot test, then run all project gates.

**Files:**
- Modify: `frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx`

- [ ] **Step 1: Write the payload-invariance test**

This asserts a representative config — including enabled cool-off tiers across tabs — submits the expected request body. Because `keepMounted` keeps all panels mounted, switching tabs must not change the payload.

```tsx
it("submits the same payload regardless of which tab is active (keepMounted invariance)", async () => {
  const onSubmit = vi.fn();
  render(<BacktestConfigForm onSubmit={onSubmit} />);
  // Enable a cool-off tier on the Filters tab (its minutes seeds to 60).
  fireEvent.click(screen.getByText("Cool off after a win"));
  // Switch back to Setup so a non-owning tab is active at submit time.
  fireEvent.click(screen.getByRole("tab", { name: /setup/i }));
  fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  const req = onSubmit.mock.calls[0][0];
  // The enabled tier + its seeded duration both made it into the payload.
  expect(req.cooloff_on_success_enabled).toBe(true);
  expect(req.cooloff_on_success_minutes).toBe(60);
  // Untouched defaults are intact (proves no field was dropped by tab hiding).
  expect(req.leverage).toBe(20);
  expect(req.simulation_interval).toBe("5m");
  expect(req.max_drawdown_pct).toBe(100);
});
```

- [ ] **Step 2: Run it**

Run: `npm run test -- BacktestConfigForm -t "keepMounted invariance"`
Expected: PASS. If `cooloff_on_success_minutes` is null, the seed-on-enable in `ToggleNumberPairField` (Task 7 Step 3) is not firing — fix there, not here.

- [ ] **Step 3: Run the ENTIRE frontend test suite**

Run: `npm run test`
Expected: PASS. Read the full output; no failures, no unhandled errors. (Other components — e.g. BacktestResultsPage — must be unaffected.)

- [ ] **Step 4: Type-check the whole project**

Run: `npx tsc --noEmit`
Expected: PASS, zero errors.

- [ ] **Step 5: Lint**

Run: `npm run lint`
Expected: PASS (or only pre-existing warnings). Resolve any new errors introduced by this work — especially unused vars from the refactor (e.g. leftover `*HasError` consts now superseded by `tabErrorCount`; remove any that are truly unused after Task 6).

- [ ] **Step 6: Production build**

Run: `npm run build`
Expected: SUCCESS (`tsc -b && vite build` completes with no errors).

- [ ] **Step 7: Final commit**

```bash
git add frontend/src/components/backtest/__tests__/BacktestConfigForm.test.tsx
git commit -m "test(backtest): assert payload invariance across tab switches"
```

---

## Manual Verification (after Task 10)

Run `npm run dev`, open the backtest page, and confirm by eye (the spec's success criteria that tests don't fully cover):

- [ ] Four tabs render: Setup / Strategy / Risk & Exits / Filters & Advanced; Setup is active first.
- [ ] Switching tabs is instant; the sticky footer stays visible with Run Backtest reachable from every tab.
- [ ] On Filters & Advanced, no blank minutes inputs show; toggling "Cool off after a win" reveals an inline `60 min` input bound to that toggle; the four cool-off cards read as pairs in a 2-column grid.
- [ ] "Enable adaptive blacklist" off → its 3 fields hidden; on → revealed.
- [ ] Force an error on a non-active tab (e.g. clear Initial Balance on Setup, switch to Strategy, click Run): it jumps back to Setup, the Setup tab shows a red count badge, and the summary banner lists it.
- [ ] Provenance hints (Scanner: / Backtest-only / Engine-level / not simulated) and the intro paragraph above the tabs are still present.
- [ ] Reload the page after switching tabs — the active tab is restored from the draft.

---

## Spec Coverage Map

Every spec requirement maps to a task:

| Spec requirement | Task(s) |
|------------------|---------|
| Modular: thin shell + tab components + shared fields module | 1, 3, 4, 5 |
| 4 lifecycle tabs (Setup/Strategy/Risk&Exits/Filters&Advanced) | 2, 5 |
| Tab grouping field mapping (single source of truth) | 2 |
| Within-tab flat always-open sections | 3 |
| Intro explainer kept above tab bar; provenance hints kept | 5 (intro), 4 (hints preserved verbatim) |
| Reveal-when-on toggles (single-field) preserved | 4 (Close Rules moved as-is) |
| Reveal-when-on toggles (boolean+value cool-off pairs) | 7, 8 |
| Adaptive-blacklist reveal group | 8 |
| No dead/always-visible inputs | 8 |
| Cross-tab error badges | 6 |
| Auto-switch to errored tab on failed submit | 6 |
| Summary banner retained | 5 (kept above tabs) |
| Sticky footer with all 5 buttons | 9 |
| Active-tab persisted to draft (additive) | 5 |
| Payload invariance (no semantic change) | 5 (keepMounted), 10 (test) |
| Field-coverage invariant (no orphaned fields) | 2 |
| Validation gates (tsc / test / build / lint) | 10 |

## Notes for the Implementer

- **`keepMounted` is load-bearing.** Do not "optimize" it away — removing it unmounts hidden-tab Controllers and breaks both payload invariance and many cross-tab test queries.
- **Never touch `configSchema.ts`.** All cool-off seeding works around the schema, not by changing it.
- **The `*HasError` consts** (`closeRulesHasError`, etc.) become dead after Task 6 introduces `tabErrorCount`. Remove the truly-unused ones in Task 10 Step 5 (lint) — but keep `advancedHasError`/`regimeHasError` logic only if still referenced; prefer deleting and relying on `tabErrorCount`.
- **Test label strings** are copied from the live markup; if a label was changed in an earlier task, update the matching test query in the same task.










