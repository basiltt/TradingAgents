# TradingAgents Neumorphism Design System

## Scope

This module is intentionally **not integrated into the live TradingAgents routes yet**.

The goal of this delivery is to keep the entire neumorphic system in the codebase as a reviewable, type-checked, production-grade component library with:

- a complete component inventory for the TradingAgents app
- route templates for every audited screen family
- trading-specific composites that match the current product surfaces
- isolated Redux Toolkit state for shell and appearance controls
- a standalone preview entrypoint

The live application was not rewritten to use these components in this pass.

## Where It Lives

Primary module:

- `frontend/src/design-system/neumorphism/`

Key files:

- `index.ts`
  Side-effect imports the design-system stylesheet and re-exports the whole surface.
- `styles.css`
  Contains the Ivory/Graphite token model, soft-shadow system, accents, and utility classes.
- `theme.ts`
  Theme enumerations and accent definitions.
- `foundation.tsx`
  Base surface primitives and theme scope.
- `shell.tsx`
  App shell, sidebar, topbar, command palette, mobile dock, and appearance studio.
- `structure.tsx`
  Page sections, responsive form/layout primitives, alert stacks, touch action bars, and route model cards.
- `headers.tsx`
  Page and entity headers, stat capsules, and status pills.
- `inputs.tsx`
  All form controls and picker components.
- `display.tsx`
  Cards, tables, filter bars, KPI grids, pagination, empty states, and progress indicators.
- `charts.tsx`
  Chart containers, toolbar controls, and legend chips.
- `overlays.tsx`
  Dialogs, drawer, toast card, banners, reconnect chip, and confirm flows.
- `templates.tsx`
  Route-level layout templates.
- `composites.tsx`
  TradingAgents-specific higher-order components.
- `registry.ts`
  Hard registry of every required component and checklist category.
- `route-blueprints.ts`
  Route-to-template/component mapping for all audited screens.
- `route-models.ts`
  Desktop/mobile layout models, alert rails, drawer usage, and touch-action contracts for all audited routes.
- `preview/TradingAgentsNeumorphismPreview.tsx`
  Standalone review surface.
- `state/neu-ui-slice.ts`
  Isolated shell/appearance Redux slice.
- `state/preview-store.ts`
  Standalone preview store.

Standalone preview entry:

- `frontend/neumorphism-preview.html`
- `frontend/src/neumorphism-preview.tsx`

The Vite build is configured as a multi-page build so the isolated preview entry remains available in both local dev and production-style build output.

## Theme Model

The system is built around a **single-material soft UI** instead of mixing cards from multiple visual systems.

Surface modes:

- `ivory`
- `graphite`

Accent palettes:

- `cobalt`
- `sage`
- `amber`
- `rose`

Contrast modes:

- `balanced`
- `high`

The root wrapper is `NeuThemeScope`. It sets the scoped data attributes and CSS variables used by every component.

Example:

```tsx
import { NeuThemeScope } from "@/design-system/neumorphism";

<NeuThemeScope mode="ivory" accent="cobalt" contrast="balanced">
  <YourNeumorphicRoute />
</NeuThemeScope>
```

## State Management

Use **Redux Toolkit** for the neumorphic shell state.

Reason:

- the app already uses Redux Toolkit for client state
- shell state spans routes and should stay outside local component trees
- server data should remain in TanStack Query, not be moved into Redux

State file:

- `frontend/src/design-system/neumorphism/state/neu-ui-slice.ts`

Slice contents:

- `mode`
- `accent`
- `contrast`
- `sidebarCollapsed`
- `mobileNavOpen`
- `commandPaletteOpen`
- `dockExpanded`

Recommended integration shape:

```ts
import { configureStore } from "@reduxjs/toolkit";
import { neuUiSlice } from "@/design-system/neumorphism";

export const store = configureStore({
  reducer: {
    // existing reducers...
    neuUi: neuUiSlice.reducer,
  },
});
```

Recommended root hookup:

```tsx
import { NeuThemeScope } from "@/design-system/neumorphism";
import { useAppSelector } from "@/store";

const neuUi = useAppSelector((state) => state.neuUi);

<NeuThemeScope
  mode={neuUi.mode}
  accent={neuUi.accent}
  contrast={neuUi.contrast}
>
  <AppRoutes />
</NeuThemeScope>
```

## Preview

The review surface is intentionally separate from the live router.

Entry:

- `http://127.0.0.1:4174/neumorphism-preview.html`

Local dev command:

```bash
npm run dev -- --host 127.0.0.1 --port 4174
```

That preview exercises:

- every name in `neumorphismComponentChecklist`
- foundations, structure, shell, headers, inputs, display, charts, overlays, composites, and templates
- stateful specimens for selection, loading, pagination, toggles, tabs, sliders, dialogs, drawers, and touch action bars
- route blueprint coverage, 17 route layout models, and the isolated shell/theme store
- live neumorphic fit review before route migration

## Component Inventory

Foundation:

- `NeuThemeScope`
- `NeuSurface`
- `NeuPanel`
- `NeuWell`
- `NeuDivider`
- `NeuGlowAccent`

Structure:

- `NeuPageSection`
- `NeuFormGrid`
- `NeuFormSection`
- `NeuSplitLayout`
- `NeuAlertStack`
- `NeuTouchActionBar`
- `NeuRouteModelCard`

Shell:

- `NeuAppShell`
- `NeuSidebar`
- `NeuNavItem`
- `NeuTopbar`
- `NeuMarketStrip`
- `NeuMobileDock`
- `NeuCommandPalette`
- `NeuAppearanceStudio`

Headers:

- `NeuPageHeader`
- `NeuEntityHeader`
- `NeuStatCapsule`
- `NeuStatusPill`

Inputs:

- `NeuButton`
- `NeuIconButton`
- `NeuInput`
- `NeuTextArea`
- `NeuSelect`
- `NeuMultiSelect`
- `NeuCombobox`
- `NeuToggleGroup`
- `NeuTabs`
- `NeuCheckbox`
- `NeuRadioGroup`
- `NeuSlider`
- `NeuDateField`
- `NeuModelPicker`
- `NeuAccountPicker`

Display:

- `NeuCard`
- `NeuBadge`
- `NeuTable`
- `NeuFilterBar`
- `NeuEmptyState`
- `NeuSkeleton`
- `NeuPagination`
- `NeuKpiGrid`
- `NeuTickerMetric`
- `NeuScoreBar`
- `NeuProgressTrack`

Charts:

- `NeuChartCard`
- `NeuChartToolbar`
- `NeuLegendChip`

Overlays:

- `NeuDialog`
- `NeuDrawer`
- `NeuToast`
- `showNeuToast`
- `NeuBanner`
- `NeuReconnectionChip`
- `NeuConfirmDialog`

Trading composites:

- `AnalysisLaunchWizard`
- `AnalysisRunConsole`
- `ScanWorkbench`
- `ScanResultsBoard`
- `AccountsGrid`
- `AccountSummaryHero`
- `TradeDeskWorkspace`
- `StrategyLibraryBoard`
- `CycleBoard`
- `ConfigInspector`
- `MemoryRecordList`

Templates:

- `NeuOverviewTemplate`
- `NeuWizardTemplate`
- `NeuConsoleTemplate`
- `NeuArchiveTemplate`
- `NeuWorkbenchTemplate`
- `NeuPortfolioGridTemplate`
- `NeuEntityDetailTemplate`
- `NeuAnalyticsTemplate`
- `NeuLibraryTemplate`
- `NeuTableIndexTemplate`
- `NeuInspectorTemplate`

## Route Blueprint

The hard route map is stored in:

- `frontend/src/design-system/neumorphism/route-blueprints.ts`
- `frontend/src/design-system/neumorphism/route-models.ts`

Current audited mapping:

| Route | Template | Main building block |
| --- | --- | --- |
| `/` | `NeuOverviewTemplate` | overview cards and KPI surfaces |
| `/analysis/new` | `NeuWizardTemplate` | `AnalysisLaunchWizard` |
| `/analysis/$runId` | `NeuConsoleTemplate` | `AnalysisRunConsole` |
| `/history` | `NeuArchiveTemplate` | archive table surfaces |
| `/scanner` | `NeuWorkbenchTemplate` | `ScanWorkbench` |
| `/scanner/history` | `NeuArchiveTemplate` | scan history archive |
| `/scanner/schedules` | `NeuWorkbenchTemplate` | schedule builder |
| `/scanner/$scanId` | `NeuEntityDetailTemplate` | run detail board |
| `/accounts` | `NeuPortfolioGridTemplate` | `AccountsGrid` |
| `/accounts/$accountId` | `NeuEntityDetailTemplate` | `AccountSummaryHero` |
| `/analytics` | `NeuAnalyticsTemplate` | chart workspace |
| `/strategies` | `NeuLibraryTemplate` | `StrategyLibraryBoard` |
| `/cycles` | `NeuTableIndexTemplate` | cycle index |
| `/cycles/$cycleId` | `NeuEntityDetailTemplate` | `CycleBoard` |
| `/config` | `NeuInspectorTemplate` | `ConfigInspector` |
| `/memory` | `NeuTableIndexTemplate` | `MemoryRecordList` |
| `/trades` | `NeuTableIndexTemplate` | `TradeDeskWorkspace` |

## Recommended Migration Order

Use route migration in this order:

1. Root shell and appearance wiring
2. Dashboard `/`
3. Analysis wizard `/analysis/new`
4. Scanner `/scanner`
5. Accounts `/accounts`
6. Trades `/trades`
7. Detail routes `/analysis/$runId`, `/accounts/$accountId`, `/scanner/$scanId`, `/cycles/$cycleId`
8. Library/archive routes `/history`, `/strategies`, `/memory`, `/cycles`
9. Analytics `/analytics`
10. Config `/config`

Reason:

- it migrates the shared shell and token scope first
- then the highest-traffic routes
- then detail screens that reuse the same primitives

## Integration Rules

When you start replacing live routes:

1. Wrap the active route tree in `NeuThemeScope`.
2. Register `neuUiSlice.reducer` in the real store.
3. Keep API data in TanStack Query and pass query results into the composites.
4. Keep route navigation in TanStack Router; these components intentionally avoid owning routing.
5. Replace one route family at a time using `route-blueprints.ts` as the contract.
6. Do not mix old card primitives and new neumorphic surfaces in the same route once migration begins.

## Verification Performed

Targeted tests:

- `src/design-system/neumorphism/__tests__/registry.test.ts`
- `src/design-system/neumorphism/__tests__/preview-store.test.ts`
- `src/design-system/neumorphism/__tests__/preview.test.tsx`

The preview test now asserts that every checklist component name is rendered on the isolated review surface.

Commands used:

```bash
npm test -- src/design-system/neumorphism/__tests__/registry.test.ts src/design-system/neumorphism/__tests__/preview-store.test.ts src/design-system/neumorphism/__tests__/preview.test.tsx
./node_modules/.bin/tsc.cmd -b --pretty false
npm run build
```

## Notes

- The preview system is fully shippable code, but it is not mounted in the production router.
- The design-system stylesheet is loaded from `frontend/src/design-system/neumorphism/index.ts`.
- The registry, route blueprint, and route model files exist specifically to prevent missed components, route structures, or mobile drawer/touch patterns during the later migration phase.
