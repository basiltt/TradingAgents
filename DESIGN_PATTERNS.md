# TradingAgents Design Language & Patterns

A comprehensive guide to the UI/UX design patterns used throughout the TradingAgents application.

## Color Palette & Theme

### Core Colors (OKLCH Color Space)

Light Mode:
- --background: oklch(0.97 0.002 285) - Nearly white bg
- --card: oklch(1 0 0) - Pure white cards
- --primary: oklch(0.55 0.24 290) - Purple/Blue
- --secondary: oklch(0.955 0.015 285) - Very light gray
- --destructive: oklch(0.577 0.245 27.325) - Red warnings

Dark Mode:
- --background: oklch(0.12 0.008 290) - Deep dark bg
- --card: oklch(0.15 0.01 290) - Slightly lighter cards
- --primary: oklch(0.55 0.20 290) - Adjusted purple/blue

### Status Colors

- Success/Green: oklch(0.6 0.19 155) - Completed, active, profit, buy signals
- Warning/Amber: oklch(0.75 0.15 85) - Caution, hold signals
- Error/Red: oklch(0.577 0.245 27.325) - Failures, losses, sell signals
- Info/Blue: oklch(0.55 0.24 290) - Running, active states

## Typography

Font Stack: 'Geist Variable', sans-serif

Text Styles:
- Page Titles: text-3xl font-bold tracking-tight
- Section Titles: text-lg font-semibold
- Card Titles: text-base font-medium
- Body Text: text-sm
- Labels: text-xs uppercase tracking-wider font-medium
- Tiny: text-[10px]
- Mono: font-mono (tickers, IDs)

## Spacing & Layout

Base unit: 0.25rem (4px)

- px-4 py-3: Standard cell padding (16px/12px)
- p-5: Card padding (20px)
- gap-4: Flex/grid gaps (16px)
- rounded-xl: Cards (12px)
- rounded-2xl: Large containers (16px)
- rounded-lg: Buttons (8px)

## Borders & Shadows

### Borders

- Standard: border border-border/50 (soft)
- Strong: border-border (full opacity)
- Colored: border-emerald-500/20, border-red-500/20

### Shadows

- Cards: shadow-[0_1px_3px_0_rgb(0_0_0/0.04)]
- Hover: shadow-sm
- Modals: shadow-2xl
- Hero: shadow-xl shadow-primary/15

## Component Patterns

### 1. Stat Cards

Basic structure:
- rounded-2xl border border-border/50 bg-card p-5
- Value: text-2xl font-bold tabular-nums
- Label: text-xs text-muted-foreground uppercase tracking-wider mt-1

With icon:
- flex items-center gap-3.5
- Icon box: w-10 h-10 rounded-xl bg-primary/10
- Text stacked vertically beside icon

### 2. Status Badges & Dots

Badge: <Badge variant="default|secondary">{status}</Badge>
Dot: w-2 h-2 rounded-full shadow-[0_0_6px] with color
Icon box: w-8 h-8 rounded-xl flex center with ring-1

### 3. Signal Badges

BUY: text-emerald-400 bg-emerald-500/10
SELL: text-red-400 bg-red-500/10
HOLD: text-amber-400 bg-amber-500/10

### 4. Tables

- Header row: border-b border-border/50
- Body rows: border-b border-border/30 hover:bg-muted/30
- Padding: px-4 py-2.5 (header), px-4 py-3 (body)
- Responsive: hidden md:table-cell

### 5. Hero Section

- gradient-hero p-8 md:p-10 text-white
- shadow-xl shadow-primary/15
- Dot pattern overlay at opacity-[0.07]
- Blur orbs for depth

### 6. Grid Layouts

- Stats: grid-cols-2 md:grid-cols-5 gap-4
- Cards: grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4
- Fixed: grid-cols-3 gap-4

### 7. Card Grid Items

- rounded-2xl border border-border/30 bg-card p-5
- hover:shadow-lg hover:border-primary/30 transition-all
- Header: flex justify-between (title + status icon)
- Status: w-8 h-8 rounded-xl with bg-color/10 ring-color/20
- Stats: grid-cols-3 gap-3 (value + label pairs)
- Footer: flex justify-between (date + view link)

### 8. Empty State

- Card with border-dashed border-2 shadow-none
- py-16 flex flex-col items-center
- Icon: w-16 h-16 rounded-2xl bg-primary/5
- CTA button with primary styling

### 9. Modal/Confirmation Dialog

- fixed inset-0 bg-black/60 backdrop-blur-md (backdrop)
- bg-card border border-border/50 rounded-2xl shadow-2xl
- p-7 space-y-5
- Icon: w-12 h-12 rounded-2xl with color background
- Buttons: flex gap-2.5 (flex-1 for equal width)

### 10. Buttons

- Primary: bg-primary text-white hover:brightness-110 shadow-lg shadow-primary/25
- Secondary: bg-secondary hover:bg-secondary/80
- Text: text-primary hover:underline
- Active: active:scale-[0.98]

### 11. Loading

- Skeleton: <Skeleton className="h-10 w-56" />
- Spinner: w-4 h-4 border-2 rounded-full animate-spin

### 12. Score Bars

- flex items-center gap-2 w-24
- Bar: flex-1 h-2 rounded-full bg-muted
- Fill: bg-emerald-500 (positive) or bg-red-500 (negative)
- Value: text-xs font-mono

## Gradients

.gradient-primary: 135deg purple to blue
.gradient-success: 135deg emerald to teal
.gradient-hero: 3-stop purple gradient (light to dark)

## Animations

.animate-pulse-slow: 3s infinite pulse
.animate-flash: 0.6s scale flash

Transitions: transition-all, transition-colors, transition-opacity, transition-transform
Durations: duration-150 (fast), duration-200 (default)

## Opacity Hierarchy

Text:
- text-muted-foreground (main secondary)
- text-muted-foreground/50 (secondary)
- text-muted-foreground/40 (subtle)
- text-muted-foreground/25 (very subtle)

Backgrounds:
- bg-primary/10 (light tint)
- bg-primary/[0.04] (ultra-light)
- border-border/50 (semi-transparent)
- shadow-black/60 (backdrop)

## Interactive States

- Hover: hover:brightness-110, hover:shadow-md, hover:bg-muted, hover:translate-x-0.5
- Active: active:scale-[0.98], active:translate-y-px
- Disabled: disabled:opacity-50, disabled:pointer-events-none

## Responsive Design

Breakpoints:
- Mobile (default)
- md: 768px (tablet)
- lg: 1024px (desktop)

Patterns:
- grid-cols-1 md:grid-cols-2 lg:grid-cols-3
- hidden md:block
- text-xs md:text-sm
- p-4 md:p-8

## Best Practices

1. Use semantic color names
2. Opacity variants for visual hierarchy
3. Consistent spacing with gap-4 baseline
4. Status colors: Emerald (success), Red (failure), Amber (warning)
5. Subtle borders with border-border/50
6. Smooth transitions on all interactions
7. Mobile-first responsive approach
8. Monospace for numeric alignment
9. Icons with shrink-0 to prevent sizing
10. Consistent radius scale (lg/xl/2xl)
