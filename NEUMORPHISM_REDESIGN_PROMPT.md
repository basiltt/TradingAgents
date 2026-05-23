# Comprehensive Neumorphism Design Overhaul — Agent Prompt

## Mission

You are a **senior UI/UX design team with 25+ years of experience** specializing in Neumorphism (soft UI) design. Your task is to systematically review and perfect EVERY page, component, and state in this React + TypeScript trading application to achieve a **world-class, best-in-class Neumorphism design** — clean, minimal, consistent, and polished.

The app is running at **http://localhost:5177/**

---

## Critical Design Problems to Fix

### 1. COLOR CONTAMINATION (HIGHEST PRIORITY)

The current implementation has **colors bleeding into shadows and backgrounds** — bluish tones, reddish tones, and accent colors mixing with the neutral surface. This destroys the neumorphic illusion.

**The Rule:** Neumorphism shadows and surfaces MUST be purely neutral (grayscale or very slightly warm/cool gray). The ONLY places color should appear are:
- Brand accent (interactive elements, CTAs, active states)
- Semantic colors (success green, warning amber, danger red) — used sparingly
- Text (neutral grays only)

**Never** tint shadows, highlights, or surface backgrounds with accent/brand colors.

### 2. COLOR SYSTEM — Implement a Strict 3-Color Architecture

Replace the current scattered color usage with an **industry-standard minimal color system:**

| Role | Purpose | Current Issue |
|------|---------|---------------|
| **Surface** (neutral gray) | All backgrounds, cards, wells, shadows | Colors are bleeding in |
| **Brand/Accent** (orange, hue ~28°) | CTAs, active nav, toggles, focus rings | Overused, tinting surfaces |
| **Text** (2-3 neutral gray shades) | Primary, secondary, disabled text | Inconsistent contrast |

**Semantic colors** (success, warning, danger) are used ONLY for status indicators — never for decoration.

**Requirement:** All colors must come from CSS custom properties defined in ONE place so the entire palette can be swapped by changing ~10 variables. The brand color (orange) must be trivially changeable to support future theming.

### 3. LAYOUT & SPACING ISSUES

Current layouts have inconsistent spacing, misaligned elements, and poor visual hierarchy. Every page needs:
- Consistent padding/margins using the spacing scale (`--neu-spacing-xs` 0.5rem, `sm` 0.75rem, `md` 1rem, `lg` 1.5rem)
- Proper visual hierarchy (larger/bolder = more important)
- Aligned grid systems
- Breathing room — neumorphism needs generous whitespace to let shadows breathe

---

## Project Architecture (What You're Working With)

### Tech Stack
- **Framework:** React 18 + TypeScript + Vite
- **Styling:** Tailwind CSS v4 + CSS custom properties
- **State:** Redux Toolkit (theme state in `neuUi` slice)
- **Router:** TanStack React Router (lazy-loaded routes)
- **Components:** Custom neumorphic design system + shadcn/ui base

### Design System Location
```
frontend/src/design-system/neumorphism/
├── styles.css          ← CSS custom properties (shadows, colors, spacing, radii)
├── theme.ts            ← Accent palette definitions, theme config
├── foundation.tsx      ← NeuSurface, NeuWell, NeuDivider, NeuThemeScope
├── inputs.tsx          ← NeuButton, NeuInput, NeuSelect, NeuToggleGroup, NeuCheckbox, etc.
├── display.tsx         ← NeuCard, NeuBadge, NeuTickerMetric, NeuTable, NeuPagination, etc.
├── shell.tsx           ← NeuSidebar, NeuTopbar, NeuAppShell, NeuCommandPalette, NeuMobileDock
├── overlays.tsx        ← NeuDialog, NeuDrawer, NeuToast, NeuAlert, NeuPopover
├── composites.tsx      ← Complex composed components
├── headers.tsx         ← Page headers
├── charts.tsx          ← Chart components
├── structure.tsx       ← Page layout structures
├── templates.tsx       ← Page templates
└── state/
    └── neu-ui-slice.ts ← Redux slice (mode, accent, contrast, sidebar state)
```

### Theme Modes
- **Light mode:** `data-neu-mode="ivory"` — Surface base: `#e0e5ec`
- **Dark mode:** `data-neu-mode="graphite"` — Surface base: `#2d3436`
- **Accent palettes:** cobalt, sage, amber, rose (defined in `theme.ts`)
- **Contrast modes:** balanced, high

### Current CSS Variables (in `styles.css`) — ACTUAL values in codebase
```css
/* Light mode (default .neu-theme) */
--neu-surface-base: #e0e5ec;
--neu-surface-muted: #d1d9e6;
--neu-surface-deep: #c8d0dc;
--neu-shadow: #b8bec7;           /* Current value — change to #a3b1c6 per neumorphism.io standard */
--neu-shadow-deep: #a0a8b4;
--neu-highlight: #ffffff;
--neu-highlight-soft: rgba(255,255,255,0.9);
--neu-accent: oklch(0.58 0.16 28);  /* Orange */
--neu-warning: oklch(0.72 0.12 28); /* BUG: same hue as accent! Should be ~85 */

/* Dark mode ([data-neu-mode="graphite"]) */
--neu-surface-base: #2d3436;
--neu-shadow: #191f20;
--neu-highlight: #414b4c;
/* Dark shadows are 9px (LARGER than light 8px — this is wrong) */

/* Accent palettes ([data-neu-accent="..."]) — cobalt|sage|amber|rose */
/* Default is "cobalt" (blue hue 257) — user wants orange as default */
```

### Global Styles Location
- `frontend/src/index.css` — Tailwind directives, global utilities, additional theme vars
- `frontend/tailwind.config.ts` — Tailwind v4 configuration

**CSS Cascade Order (IMPORTANT):** Both `styles.css` and `index.css` define overlapping variables like `--background`, `--card`, `--shadow-card`, `--warning`, etc. The neumorphism `styles.css` uses `.neu-theme` selector (class-based specificity) which OVERRIDES `:root` definitions in `index.css`. So `styles.css` wins for any variable defined in both places. However, `index.css` also has `.dark` rules that could compete. When fixing colors, check BOTH files for the same variable name to ensure consistency.

### All Pages (Routes)

| # | Route | Component File | Description |
|---|-------|---------------|-------------|
| 1 | `/` | `components/dashboard/HomeDashboard.tsx` | Main dashboard with KPIs |
| 2 | `/analysis/new` | `components/analysis/AnalysisDashboard.tsx` | New analysis creation |
| 3 | `/history` | `components/dashboard/HistoryList.tsx` | Analysis history |
| 4 | `/scanner` | `components/scanner/ScannerPage.tsx` | Market scanner |
| 5 | `/scanner/history` | `components/scanner/ScanHistoryPage.tsx` | Scan history |
| 6 | `/scanner/{scanId}` | `components/scanner/ScanDetailPage.tsx` | Scan detail view |
| 7 | `/scanner/schedules` | `components/scanner/ScheduledScansPage.tsx` | Scheduled scans |
| 8 | `/accounts` | `components/accounts/AccountsDashboard.tsx` | Accounts overview |
| 9 | `/accounts/{id}` | `components/accounts/AccountDetailView.tsx` | Account detail |
| 10 | `/analytics` | `components/analytics/AnalyticsDashboard.tsx` | Performance analytics |
| 11 | `/trades` | `components/trades/TradesPage.tsx` | Trade history |
| 12 | `/strategies` | `components/strategies/StrategiesPage.tsx` | Strategy management |
| 13 | `/cycles` | `components/cycles/CycleListPage.tsx` | Trading cycles list |
| 14 | `/cycles/{id}` | `components/cycles/CycleDetailPage.tsx` | Cycle detail |
| 15 | `/config` | `components/config/ConfigPage.tsx` | App configuration |
| 16 | `/memory` | `components/config/MemoryPage.tsx` | Memory/context page |

### Layout Components (Always Visible)
- `components/layout/RootLayout.tsx` — App shell wrapper
- `components/layout/AppCommandPalette.tsx` — Cmd+K command palette
- `components/layout/MobileDock.tsx` — Mobile bottom navigation
- `components/layout/AppMarketBar.tsx` — Market ticker bar
- `components/layout/AppearanceControls.tsx` — Theme switcher

### Hidden State Components to Check
- All **modals/dialogs** (add account, close positions, conditional rules, analysis config)
- All **drawers** (trade detail panel, mobile navigation)
- All **popovers** (tooltips, dropdowns, filters)
- All **loading states** (skeletons, spinners)
- All **empty states** (no data, no results)
- All **error states** (error banners, toast notifications)
- All **hover/focus/active states** on interactive elements
- **Command palette** (Cmd+K overlay)
- **Toast notifications** (success, error, warning)

---

## Neumorphism Design Principles (Your Bible)

### 1. Surface & Shadow Rules
- Background and elements share the SAME base color (they're "extruded from" the surface)
- Light comes from top-left → shadow bottom-right, highlight top-left
- Shadow color = surface darkened by ~20-25% (for #e0e5ec → #a3b1c6 is the standard)
- Highlight color = pure white or surface lightened to white
- NEVER use colored shadows (no blue-tinted, no red-tinted, no accent-tinted)
- Raised elements: outer shadows (light top-left, dark bottom-right)
- Pressed/inset elements: inner shadows (dark top-left, light bottom-right)
- Shadow colors should be desaturated neutral grays — a slight cool-gray undertone (like #a3b1c6) is acceptable and standard, but NO chromatic accent color should be visible in shadows

### 2. Depth Hierarchy (Max 3 Levels)
- **Level 0 (Flat):** The page background itself
- **Level 1 (Raised):** Cards, buttons, navigation items
- **Level 2 (Floating):** Modals, dropdowns, tooltips (stronger shadow)
- **Inset:** Input fields, wells, pressed buttons (inner shadow)
- **NOT every element gets a shadow.** Dense areas (table rows, list items, small badges) should remain flat to avoid visual noise. Only primary containers and interactive controls get depth.

### 3. Color Rules for Perfect Neumorphism
- Surface colors: NEUTRAL grays only (warm gray `#e0e5ec` for light, cool dark `#2d3436` for dark)
- Accent/brand: ONE color (orange), used ONLY for:
  - Active/selected state indicators
  - Primary CTA buttons (small area, not full background)
  - Focus rings
  - Progress indicators
  - Active navigation items (subtle, not overwhelming)
- Text: 3 shades of neutral gray (strong, muted, soft)
- NEVER tint the surface, shadows, or large areas with accent color

### 4. Typography in Neumorphism
- Use weight and size for hierarchy, NOT color variety
- Headers: bold/semibold, larger size
- Body: regular weight, base size
- Captions/labels: regular weight, smaller size, muted color
- AVOID colored text except for links and semantic states

### 5. Spacing & Layout
- Generous padding — elements need room for shadows to breathe
- Minimum 16px padding inside cards
- Minimum 16-24px gap between raised elements
- Consistent grid alignment
- Use the defined spacing scale from CSS vars: `--neu-spacing-xs`(8px/0.5rem), `--neu-spacing-sm`(12px/0.75rem), `--neu-spacing-md`(16px/1rem), `--neu-spacing-lg`(24px/1.5rem)

### 6. Interactive States
- **Default:** Raised (outer shadow)
- **Hover:** Slightly stronger shadow OR subtle scale
- **Active/Pressed:** Inset shadow (pressed into surface)
- **Focus:** Subtle accent ring (not glowing, not thick)
- **Disabled:** Flat, reduced opacity, no shadow

### 7. Dark Mode Specifics
- Surface: very dark neutral gray (#2d3436 or similar)
- Shadow: darker than surface (#191f20)
- Highlight: lighter than surface (#414b4c)
- Text: light grays (#ecf0f1 strong, #b2bec3 muted)
- Accent still orange but potentially slightly adjusted for contrast
- Shadows should be MORE subtle in dark mode (less visible naturally)

---

## Execution Process (For Each Page)

### Workflow Per Page (20 Iterations)
1. **Navigate** to the page in dark mode using Playwright
2. **Screenshot** the current state
3. **Analyze** against neumorphism principles — identify:
   - Color contamination (colored shadows, tinted surfaces)
   - Layout issues (spacing, alignment, hierarchy)
   - Component inconsistencies
   - Shadow quality (too strong, too weak, wrong direction)
   - Typography issues
   - Missing depth cues
4. **Fix** the identified issues in the source code
5. **Screenshot** again to verify improvement
6. **Repeat** for 20 iterations until pixel-perfect
7. **Switch to light mode** and verify the same page
8. **Fix** any light-mode-specific issues
9. **Move** to next page

### Order of Operations
1. **Global first:** Fix `styles.css`, `theme.ts`, `index.css` — establish the correct color system
2. **Layout shell:** Sidebar, topbar, mobile dock, app shell
3. **Shared components:** Buttons, inputs, cards, badges, tables
4. **Pages in order:** Dashboard → Scanner → Accounts → Analytics → Trades → Strategies → Cycles → Analysis → Config → Memory
5. **Hidden states:** Dialogs, drawers, toasts, loading states, empty states, error states

---

## Known Bugs & Codebase Reality (READ FIRST)

Before implementing, understand these critical facts about the CURRENT state:

### Bug 1: `--neu-warning` has the SAME hue as accent (hue 28)
In `styles.css` line 33: `--neu-warning: oklch(0.72 0.12 28)` — this is indistinguishable from accent orange. **Fix:** Change to hue ~85 (proper amber/yellow).

### Bug 2: `.neu-surface-accent` contaminates surfaces with color
Lines 288-298 in `styles.css` use `color-mix` to blend accent color INTO the surface background. This is one of the PRIMARY sources of color bleeding. **Fix:** Remove color mixing or make it so subtle it's barely perceptible.

### Bug 3: `.neu-button-tonal` bleeds accent into surface
Line 532: `background: color-mix(in oklch, var(--neu-accent-muted) 20%, var(--neu-surface-raised))` — tints the button surface. **Fix:** Use a neutral raised surface with only a thin accent border or icon color.

### Bug 4: Dark mode shadows are LARGER than light mode (wrong)
Current: Light raised = 8px, Dark raised = 9px. Light hover = 10px, Dark hover = 12px. Light float = 12px, Dark float = 14px. Light pill = 5px, Dark pill = 6px. ALL dark values exceed their light equivalents. Research says dark mode should be MORE subtle. **Fix:** Dark ≤ Light for every shadow level (see Shadow Distance Specifications section for corrected values).

### Bug 5: Default accent is "cobalt" (blue), NOT orange
`theme.ts` line 23: `DEFAULT_NEU_ACCENT = "cobalt"`. The user wants orange as default. **Fix:** Change to an orange palette or make the default the orange hue.

### Bug 6: `.neu-table-wrap` and `.neu-chart-well` use gradient backgrounds (IVORY MODE ONLY)
Lines 577-592: These use `linear-gradient(145deg, ...)` mixing shadow/highlight colors into the surface. While the colors ARE neutral (not accent-tinted), the gradient creates a visible directional tone shift that competes with the shadow-based depth cues. This muddies the clean neumorphic illusion. **Note:** Graphite mode already overrides these to flat `var(--neu-surface-muted)` at lines 489-493 — so this bug is ivory-only. **Fix:** Use flat `var(--neu-surface-muted)` with inset shadow only in ivory mode too — let the box-shadow handle depth, not the background gradient.

### Bug 7: `--warning` in `index.css` ALSO uses brand hue (TWO instances)
`index.css` line 97 (light mode): `--warning: oklch(0.72 0.12 var(--brand-hue))`
`index.css` line 183 (dark mode): `--warning: oklch(0.78 0.12 var(--brand-hue))`
Both make warning indistinguishable from accent. **Fix:** Replace `var(--brand-hue)` with a dedicated `--warning-hue: 85` variable in both places.

### Bug 8: `gradient-primary` / `gradient-hero` used across 14+ component files
These classes paint large accent-colored gradient backgrounds (defined in `styles.css` lines 700-717). While appropriate for small accent elements (CTA buttons, progress bar fills), verify they're NOT being used on large card surfaces or section backgrounds. **Audit files:**
- `ScannerPage.tsx`, `ScanHistoryPage.tsx`, `ScanDetailPage.tsx`, `ScheduledScansPage.tsx`
- `AccountsDashboard.tsx`, `StrategiesPage.tsx`, `CycleListPage.tsx`, `CycleDetailPage.tsx`
- `AnalyticsDashboard.tsx`, `ConfigPage.tsx`, `MemoryPage.tsx`
- `PlaceTradeDialog.tsx`, `CloseHistoryDialog.tsx`, `AutoTradeSection.tsx`

**Rule:** `gradient-primary` is OK on: buttons, pills, progress bar fills, small indicators (<10% visual area). It is NOT OK on: card backgrounds, section headers, large panels.

### Existing Architecture You MUST Preserve

The codebase uses a **multi-palette accent system** via `data-neu-accent` attribute:
- `cobalt` (hue 257), `sage` (hue 154), `amber` (hue 72), `rose` (hue 9)
- Each palette sets `--neu-accent`, `--neu-accent-muted`, `--neu-accent-ink`
- These are defined BOTH in `styles.css` (lines 679-698) AND `theme.ts`

**DO NOT remove the palette system.** Instead:
1. Add an "orange" palette (hue ~28) and make it the default
2. Keep other palettes available
3. Ensure NO palette causes color contamination on surfaces/shadows

### Variables That Exist But Are Missing From This Prompt's Color Spec

These variables ALREADY exist in the codebase and must be preserved (values may be updated as specified in the Color Spec section):
```css
--neu-shadow-deep: #a0a8b4;         /* Deeper shadow — Color Spec changes this to #8e99a8 */
--neu-highlight-soft: rgba(255,255,255,0.9);  /* Soft highlight for gradients */
--neu-stroke-soft: rgba(255,255,255,0.7);     /* Subtle border highlight */
--neu-stroke-strong: rgba(0,0,0,0.1);         /* Stronger border */
--neu-surface-accent-bg: oklch(0.94 0.03 28); /* Accent-tinted surface (use sparingly!) */
--neu-surface-overlay: rgba(245,245,245,0.92); /* Modal/overlay backdrop */
--neu-focus: oklch(0.58 0.16 28 / 0.4);       /* Focus ring color with opacity */
--neu-accent-ink: #ffffff;                      /* Text color ON accent backgrounds */
--neu-noise: none;                              /* Texture overlay (currently disabled) */
```

Also preserves shadow-to-tailwind bridge variables:
```css
--background, --foreground, --card, --primary, --secondary, --muted, --destructive,
--border, --input, --ring, --sidebar-*, --success, --warning, --danger, --radius,
--glass-bg, --shadow-card, --shadow-popover, --terminal-*
```

---

## Color System to Implement (Research-Verified)

> **Sources:** neumorphism.io defaults, CSS-Tricks neumorphism guide, Themesberg Neumorphic UI Kit, 60-30-10 industry standard color distribution rule.

### The 60-30-10 Rule Applied to Neumorphism
- **60% — Neutral surface** (`--neu-surface-base`): All backgrounds, cards, wells. This IS the neumorphism canvas.
- **30% — Neutral text/borders** (`--neu-text-*`): Content hierarchy using weight/size/opacity only.
- **10% — Brand accent** (`--neu-accent`): CTAs, active states, focus rings, progress indicators. MAX 10% of visual area.

### Light Mode (Ivory) — Verified Values
```css
/* === SURFACES (60%) — Industry standard neumorphism base === */
--neu-surface-base: #e0e5ec;      /* THE canonical neumorphism light bg (neumorphism.io default) */
--neu-surface-raised: #e0e5ec;    /* Same as base — elements extrude FROM the surface */
--neu-surface-muted: #d1d9e6;     /* 5% darker for subtle depth (wells, recessed areas) */
--neu-surface-deep: #c8d0dc;      /* 8% darker for deep insets */
--neu-surface-accent-bg: oklch(0.94 0.03 28); /* BARELY tinted — only for active nav bg */
--neu-surface-overlay: rgba(245, 245, 245, 0.92); /* Modal backdrop */

/* === SHADOWS — Must be PURELY NEUTRAL (no hue contamination) === */
--neu-shadow: #a3b1c6;            /* neumorphism.io verified shadow for #e0e5ec */
--neu-shadow-deep: #8e99a8;       /* CHANGED from current #a0a8b4 — darker for better high-contrast separation */
--neu-highlight: #ffffff;          /* Pure white highlight */
--neu-highlight-soft: rgba(255, 255, 255, 0.9); /* Softer highlight for subtle use */
/* NOTE: #a3b1c6 is the STANDARD neumorphism shadow for #e0e5ec backgrounds.
   It has a natural cool-gray undertone (slightly blue-gray) which is expected and correct.
   This is NOT "color contamination" — it's the natural darkening of the cool-gray base.
   Color contamination means accent/brand hues (orange, blue, red) bleeding into shadows.
   Verified from neumorphism.io and Themesberg design system. */

/* === STROKES (borders) === */
--neu-stroke-soft: rgba(255, 255, 255, 0.7);  /* Inner highlight border */
--neu-stroke-strong: rgba(0, 0, 0, 0.1);      /* Subtle dark border */

/* === TEXT (30%) — Neutral gray scale only === */
--neu-text-strong: #2d3436;       /* Near-black — primary content, headings */
--neu-text-muted: #636e72;        /* Medium gray — secondary content, labels */
--neu-text-soft: #7f8c8d;         /* Light gray — placeholders, disabled, captions */

/* === ACCENT (10%) — Brand color, the ONLY chromatic color on surfaces === */
--neu-accent: oklch(0.58 0.16 28);     /* Orange brand — matches current codebase format */
--neu-accent-muted: oklch(0.94 0.03 28); /* Very subtle warm tint for active bg */
--neu-accent-ink: #ffffff;              /* Text on accent backgrounds */
--neu-focus: oklch(0.58 0.16 28 / 0.4); /* Focus ring with transparency */

/* === SEMANTIC — Used ONLY for status indicators, never decoration === */
--neu-success: oklch(0.64 0.14 155);   /* Green — profit, connected, complete */
--neu-warning: oklch(0.72 0.12 85);    /* TRUE amber/yellow (NOT hue 28!) — caution */
--neu-danger: oklch(0.58 0.16 4);      /* Red — loss, error, disconnect */
```

### Dark Mode (Graphite) — Verified Values
```css
/* === SURFACES === */
--neu-surface-base: #2d3436;      /* Verified dark neumorphism base */
--neu-surface-raised: #2d3436;    /* Same as base */
--neu-surface-muted: #252b2d;     /* Slightly darker for wells */
--neu-surface-deep: #1e2426;      /* Deep insets */
--neu-surface-accent-bg: oklch(0.3 0.04 28); /* Dark accent tint */
--neu-surface-overlay: rgba(30, 30, 30, 0.94);

/* === SHADOWS — Purely neutral, SMALLER than light mode === */
--neu-shadow: #191f20;            /* ~15% darker than base — pure neutral */
--neu-shadow-deep: #111516;       /* Extra dark for high contrast */
--neu-highlight: #414b4c;         /* ~15% lighter than base — pure neutral */
--neu-highlight-soft: rgba(65, 75, 76, 0.5); /* Softer highlight */

/* === STROKES === */
--neu-stroke-soft: rgba(255, 255, 255, 0.06);
--neu-stroke-strong: rgba(255, 255, 255, 0.1);

/* === TEXT === */
--neu-text-strong: #ecf0f1;      /* Off-white — primary content */
--neu-text-muted: #b2bec3;       /* Light gray — secondary content */
--neu-text-soft: #7f8c8d;        /* Medium gray — placeholders, disabled */

/* === ACCENT — Same oklch format, slightly adjusted for dark bg === */
/* NOTE: The current codebase does NOT override --neu-accent in graphite mode.
   The palette system handles accent color. The values below are SUGGESTED additions
   for better dark-mode contrast. Apply them per-palette in the [data-neu-mode="graphite"]
   section, or skip if the palette system already provides sufficient contrast. */
--neu-accent: oklch(0.65 0.16 28);     /* Slightly lighter for dark bg visibility */
--neu-accent-muted: oklch(0.30 0.04 28);
--neu-accent-ink: #ffffff;
--neu-focus: oklch(0.72 0.14 28 / 0.3);

/* === SEMANTIC === */
--neu-success: oklch(0.70 0.12 155);
--neu-warning: oklch(0.75 0.10 85);    /* Hue 85, NOT 28 */
--neu-danger: oklch(0.62 0.14 4);
```

### Shadow Distance Specifications
```css
/* Light mode (Ivory) — current codebase values, verified as good */
--neu-shadow-raised: 8px 8px 16px var(--neu-shadow), -8px -8px 16px var(--neu-highlight);
--neu-shadow-raised-hover: 10px 10px 20px var(--neu-shadow), -10px -10px 20px var(--neu-highlight);
--neu-shadow-inset: inset 4px 4px 8px var(--neu-shadow), inset -4px -4px 8px var(--neu-highlight);
--neu-shadow-press: inset 6px 6px 12px var(--neu-shadow), inset -6px -6px 12px var(--neu-highlight);
--neu-shadow-float: 12px 12px 24px var(--neu-shadow), -12px -12px 24px var(--neu-highlight);
--neu-shadow-accent: 8px 8px 16px var(--neu-shadow), -8px -8px 16px var(--neu-highlight); /* Same as raised — for accent depth class */
--neu-shadow-pill: 5px 5px 10px var(--neu-shadow), -5px -5px 10px var(--neu-highlight);
--neu-shadow-input: inset 3px 3px 6px var(--neu-shadow), inset -3px -3px 6px var(--neu-highlight);

/* Dark mode (Graphite) — SAME or SMALLER than light (fix current bug where dark > light) */
--neu-shadow-raised: 7px 7px 14px var(--neu-shadow), -7px -7px 14px var(--neu-highlight);
--neu-shadow-raised-hover: 9px 9px 18px var(--neu-shadow), -9px -9px 18px var(--neu-highlight);
--neu-shadow-inset: inset 4px 4px 8px var(--neu-shadow), inset -4px -4px 8px var(--neu-highlight);
--neu-shadow-press: inset 5px 5px 10px var(--neu-shadow), inset -5px -5px 10px var(--neu-highlight);
--neu-shadow-float: 10px 10px 20px var(--neu-shadow), -10px -10px 20px var(--neu-highlight);
--neu-shadow-accent: 7px 7px 14px var(--neu-shadow), -7px -7px 14px var(--neu-highlight); /* Must match raised — currently missing from dark, inherits light 8px */
--neu-shadow-pill: 5px 5px 10px var(--neu-shadow), -5px -5px 10px var(--neu-highlight);
--neu-shadow-input: inset 3px 3px 6px var(--neu-shadow), inset -3px -3px 6px var(--neu-highlight);
```

### Brand Color Changeability Architecture

The codebase uses a **palette system** with `data-neu-accent` attributes. To add orange as default:

```typescript
// In theme.ts — ADD this palette and set it as DEFAULT_NEU_ACCENT
export const DEFAULT_NEU_ACCENT: NeuAccentPalette = "flame"; // renamed from "cobalt"

// New palette definition:
flame: {
  key: "flame",
  label: "Flame",
  description: "Energetic orange for trading momentum and call-to-action.",
  accent: "oklch(0.58 0.16 28)",
  muted: "oklch(0.94 0.03 28)",
  ink: "oklch(0.25 0.04 28)",
  previewIvory: "linear-gradient(135deg, oklch(0.65 0.15 28), oklch(0.78 0.10 40), oklch(0.90 0.03 50))",
  previewGraphite: "linear-gradient(145deg, oklch(0.30 0.05 28), oklch(0.42 0.09 30) 48%, oklch(0.68 0.13 28) 100%)",
}
```

```css
/* In styles.css — add the palette selector */
.neu-theme[data-neu-accent="flame"] {
  --neu-accent: oklch(0.58 0.16 28);
  --neu-accent-muted: oklch(0.94 0.03 28);
  --neu-accent-ink: oklch(0.25 0.04 28);
}
```

**NOTE on redundancy:** The base `.neu-theme` block ALREADY defines `--neu-accent: oklch(0.58 0.16 28)` (same value as the "flame" selector). This means the "flame" CSS rule is technically a no-op — it exists purely for **architectural consistency** so that every palette has an explicit selector. If a user clears `data-neu-accent` entirely, the base still renders orange. This is intentional and correct.

To change brand color in the future: add a new palette entry with different hue, set it as default. All palettes remain available for user choice.

### Color Format Decision: Use oklch (Match Existing Codebase)

The codebase already uses `oklch()` for all accent and semantic colors. **Do NOT switch to hex for accents/semantics** — this would create inconsistency. Use:
- **Hex** for surfaces/shadows/text (where exact cross-browser rendering matters)
- **oklch** for accent/semantic colors (where hue manipulation and palette flexibility matters)

This matches the existing dual approach in `styles.css`.

---

## Quality Checklist (Per Component)

- [ ] No colored shadows (shadows are pure neutral gray, light or dark)
- [ ] No accent color bleeding into surface backgrounds
- [ ] Surface, shadow, and highlight are the same hue family (neutral gray)
- [ ] Proper shadow direction (light from top-left consistently)
- [ ] Appropriate depth level (flat/raised/floating/inset)
- [ ] Consistent border-radius (use --neu-radius-sm/md/lg only)
- [ ] Proper spacing using spacing scale
- [ ] Text hierarchy using only weight/size/gray-shade
- [ ] Interactive states all work (hover → stronger shadow, active → inset)
- [ ] Works in both dark and light mode
- [ ] No jarring color contrast issues
- [ ] Accent color used sparingly and purposefully
- [ ] No gradient backgrounds on surfaces (flat surfaces only — exception: `.neu-surface-disabled` and high-contrast mode use intentional micro-gradients)
- [ ] Loading/empty/error states styled consistently
- [ ] Mobile responsive and still neumorphic

---

## Files You Will Primarily Edit

### Global (Fix First)
1. `frontend/src/design-system/neumorphism/styles.css` — CSS variables (THE source of truth for all colors/shadows)
2. `frontend/src/design-system/neumorphism/theme.ts` — Accent palette definitions + defaults
3. `frontend/src/design-system/neumorphism/types.ts` — TypeScript types for palettes/modes
4. `frontend/src/design-system/neumorphism/state/neu-ui-slice.ts` — Redux slice + `isNeuAccent()` validation
5. `frontend/src/index.css` — Global utilities and Tailwind overrides (has its OWN color system that must align)

### Components (Fix Second)
6. `frontend/src/design-system/neumorphism/foundation.tsx`
7. `frontend/src/design-system/neumorphism/inputs.tsx`
8. `frontend/src/design-system/neumorphism/display.tsx`
9. `frontend/src/design-system/neumorphism/shell.tsx`
10. `frontend/src/design-system/neumorphism/overlays.tsx`
11. `frontend/src/design-system/neumorphism/composites.tsx`
12. `frontend/src/design-system/neumorphism/headers.tsx`
13. `frontend/src/design-system/neumorphism/charts.tsx`

### Pages (Fix Third — One at a Time)
14-29. Each page component listed in the 16 routes in the table above

### Layout
30. `frontend/src/components/layout/RootLayout.tsx`
31. `frontend/src/components/layout/MobileDock.tsx`
32. `frontend/src/components/layout/AppMarketBar.tsx`

---

## Non-Negotiable Rules

1. **DO NOT break any functionality.** This is purely visual. No logic changes.
2. **DO NOT remove features.** Every button, form, chart, table must still work.
3. **Always test both modes.** Dark mode first, then verify light mode.
4. **Use Playwright MCP** to take screenshots and visually verify every change.
5. **Track progress** — maintain a checklist of every page/component reviewed.
6. **20 iterations minimum per page** — don't stop at "good enough."
7. **Colors from variables only** — no hardcoded hex/rgb in component files.
8. **The brand color (orange) must be changeable** by swapping the default palette (one TypeScript const + one CSS rule). Future themes = new palette entry.
9. **Shadows must be neutral** — zero color tint in any shadow or highlight.
10. **Generous whitespace** — neumorphism needs breathing room.

---

## Success Criteria

When done, the app should look like:
- A premium, high-end financial dashboard
- Soft, tactile surfaces that look extruded from the background
- Clean, minimal color usage (surfaces are gray, accent is orange, text is gray)
- Consistent depth and shadow language across every element
- Professional typography hierarchy
- Smooth, polished interactive states
- Equally beautiful in both dark and light mode
- Could be featured in a "Best Neumorphism UI" design showcase

---

## Getting Started

1. First, read `frontend/src/design-system/neumorphism/styles.css` and `frontend/src/index.css` to understand current color definitions
2. Fix the global color system to eliminate all color contamination
3. Navigate to http://localhost:5177/ in dark mode
4. Begin the systematic page-by-page review starting with the layout shell
5. Use Playwright to screenshot → analyze → fix → verify in a tight loop

---

## How to Switch Dark/Light Mode in Browser (Via Playwright)

The theme is controlled via `data-neu-mode` attribute on `<html>`. To toggle:

```javascript
// Switch to dark mode (graphite)
document.documentElement.dataset.neuMode = "graphite";
document.documentElement.classList.add("dark");
document.documentElement.dataset.theme = "dark";
document.documentElement.style.colorScheme = "dark";

// Switch to light mode (ivory)
document.documentElement.dataset.neuMode = "ivory";
document.documentElement.classList.remove("dark");
document.documentElement.dataset.theme = "light";
document.documentElement.style.colorScheme = "light";

// Change accent palette
document.documentElement.dataset.neuAccent = "flame"; // or cobalt, sage, amber, rose
```

Use Playwright's `browser_evaluate` to execute these snippets when you need to switch modes for verification.

**NOTE:** These DOM manipulations bypass Redux state and localStorage — they're for TRANSIENT visual verification during screenshots only. The actual app switches themes via Redux dispatch in `useThemeEffect.ts`. Don't worry about persistence during your review loop — just use these to toggle views quickly.

---

## TypeScript Type Updates Required

When adding the "flame" palette, you MUST update ALL of these locations:

**1. `types.ts` line 8:**
```typescript
// FROM:
export type NeuAccentPalette = "cobalt" | "sage" | "amber" | "rose";
// TO:
export type NeuAccentPalette = "flame" | "cobalt" | "sage" | "amber" | "rose";
```

**2. `theme.ts` line 8:**
```typescript
export const neuAccentPalettes = ["flame", "cobalt", "sage", "amber", "rose"] as const;
```

**3. `theme.ts` line 23:**
```typescript
export const DEFAULT_NEU_ACCENT: NeuAccentPalette = "flame";
```

**4. `state/neu-ui-slice.ts` line 35-36 — CRITICAL (hardcoded validation):**
```typescript
function isNeuAccent(value: unknown): value is NeuAccentPalette {
  return value === "flame" || value === "cobalt" || value === "sage" || value === "amber" || value === "rose";
}
```

**5. CSS selector in `styles.css` (after line 698):**
```css
.neu-theme[data-neu-accent="flame"] {
  --neu-accent: oklch(0.58 0.16 28);
  --neu-accent-muted: oklch(0.94 0.03 28);
  --neu-accent-ink: oklch(0.25 0.04 28);
}
```

**6. `theme.ts` — Add palette definition in `neuAccentDefinitions`:**
```typescript
flame: {
  key: "flame",
  label: "Flame",
  description: "Energetic orange for trading momentum and call-to-action.",
  accent: "oklch(0.58 0.16 28)",
  muted: "oklch(0.94 0.03 28)",
  ink: "oklch(0.25 0.04 28)",   // NOTE: This is text color on MUTED accent bg, not on primary buttons
  previewIvory: "linear-gradient(135deg, oklch(0.65 0.15 28), oklch(0.78 0.10 40), oklch(0.90 0.03 50))",
  previewGraphite: "linear-gradient(145deg, oklch(0.30 0.05 28), oklch(0.42 0.09 30) 48%, oklch(0.68 0.13 28) 100%)",
}
```

**Note on `--neu-accent-ink`:** The base theme (line 30) sets `--neu-accent-ink: #ffffff` — this is for text on PRIMARY accent buttons (white on orange). Each palette OVERRIDES this with a dark color — that's for text on MUTED accent backgrounds (dark text on light tint). Both are correct for their contexts.

**Note on localStorage:** Users who already have `tradingagents-neu-accent = "cobalt"` in localStorage will keep seeing blue after this change. This is expected — only new users or cleared storage will see the new default. Do NOT clear localStorage.

**Note on palette UI:** The `NeuAppearanceStudio` component (shell.tsx line 604) accepts `palette`/`onPaletteChange` props but currently renders NO palette picker — only surface mode and contrast toggles. This means "flame" becomes the default via code but users have no visible way to switch palettes in the current UI. This is intentional — do NOT add a palette picker as part of this design overhaul. It may be added later as a separate feature.

---

## Potential Pitfalls

1. **`index.css` has its OWN parallel color system** with `--brand-hue`, `--surface-hue`, `--primary`, etc. These are separate from the neumorphism variables but some bridge vars connect them (lines 62-109 in `styles.css`). If you change neumorphism vars, verify the bridge vars still produce correct values.

2. **High-contrast mode** (`data-neu-contrast="high"`) has its own shadow override (lines 160-171 in `styles.css`) using `color-mix` with `var(--neu-shadow-deep)`. Changing `--neu-shadow-deep` (from `#a0a8b4` to `#8e99a8`) will make high-contrast shadows darker — verify visually that this still looks good and doesn't create harsh black blobs.

3. **The `filter: saturate(1.04)` on hover** (line 320 in `styles.css`) can subtly shift colors. Also `backdrop-filter: ... saturate(1.2)` on the command overlay (line 596) and mobile dock (line 602). These are minor but could make neutral surfaces appear slightly warm/cool under certain conditions.

4. **Chart libraries** (likely Recharts or similar) may have their own hardcoded colors. Check `frontend/src/design-system/neumorphism/charts.tsx` and any chart wrapper components for inline color values that bypass the CSS variable system.

5. **Vite HMR** — After editing CSS files, the browser will hot-reload. After editing `.tsx` files, it may need a page refresh. Take screenshots AFTER the reload completes.

6. **The `.neu-surface-accent` depth class** (line 288) is used when `depth="accent"` is passed to `NeuSurface`. Grep for `depth="accent"` or `depth: "accent"` in components to find all usages — these are the color-contaminated surfaces.

7. **`.dark` class in `index.css` hardcodes shadow values** — Lines 188-199 define `--shadow-card`, `--shadow-soft`, `--shadow-accent`, `--shadow-popover`, `--shadow-inset` with literal hex colors (`#191f20`, `#414b4c`) and 9px distances. The `.neu-theme` selector in `styles.css` overrides these via bridge variables (line 94: `--shadow-card: var(--neu-shadow-raised)`), so the neumorphism system wins. But if you modify shadow values in `styles.css`, verify the bridge still works correctly. Also: if ANY component uses `--shadow-card` directly from a non-`.neu-theme` context, it would get the hardcoded 9px values.

8. **Dark mode accent is NOT per-mode in the current codebase.** The `[data-neu-mode="graphite"]` block does NOT override `--neu-accent`. Accent color comes ONLY from the palette system (`[data-neu-accent="..."]`). If you want slightly brighter orange in dark mode, you'd need to add a per-palette-per-mode override like `.neu-theme[data-neu-mode="graphite"][data-neu-accent="flame"]` — or accept the same accent in both modes.

9. **`--radius` defined in BOTH files with different values.** `index.css` line 100: `--radius: 1.1rem`. `styles.css` line 91: `--radius: 1rem`. The `.neu-theme` class wins (loaded after `:root`). Do NOT change either without understanding this override relationship — if you "fix" `index.css` to match, you'd break any non-neumorphism context.

10. **Chart colors in `index.css` derive from `--brand-hue`.** Lines 82-86 and 169-172 define `--chart-1` through `--chart-5` using `calc(var(--brand-hue) ± offset)`. Since `--brand-hue: 28` (orange), charts will have warm-adjacent tones. These vars are defined in `:root`/`.dark` and are NOT overridden by `styles.css`. If the agent changes `--brand-hue`, ALL chart colors shift — which is fine and intentional, but be aware of it during visual review.
