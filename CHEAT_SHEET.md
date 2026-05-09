# Design Quick Reference Cheat Sheet

## Color Palette

**Primary Colors (Light Mode)**
- Background: oklch(0.97 0.002 285) - Nearly white
- Card: oklch(1 0 0) - Pure white  
- Primary: oklch(0.55 0.24 290) - Purple/blue
- Destructive: oklch(0.577 0.245 27.325) - Red

**Status Colors (Always)**
- Emerald: Success, profit, buy, active
- Red: Failure, loss, sell, destructive  
- Amber: Warning, hold, caution
- Blue: Running, active processes

---

## Spacing (4px Grid)

**Most Used:**
- gap-4: 16px (between elements)
- p-5: 20px (card padding)
- px-4 py-3: Table cells
- rounded-xl: 12px (cards)
- rounded-2xl: 16px (containers)

---

## Component Patterns

**Stat Grid:** `grid grid-cols-2 md:grid-cols-5 gap-4`
**Card:** `rounded-2xl border border-border/50 bg-card p-5`
**Button:** `px-5 py-2.5 rounded-xl bg-primary text-white hover:brightness-110 shadow-lg shadow-primary/25`
**Table Row:** `border-b border-border/30 hover:bg-muted/30 px-4 py-3`
**Badge:** `px-2 py-0.5 rounded text-xs font-bold` (+ colors)

---

## Responsive

- Mobile: grid-cols-1, text-xs, p-4
- Tablet (md): grid-cols-2, text-sm, p-8  
- Desktop (lg): grid-cols-3, text-base, p-12

---

## Text Hierarchy

- Title: text-3xl font-bold tracking-tight
- Section: text-lg font-semibold
- Body: text-sm
- Label: text-xs uppercase tracking-wider

---

## Animations

- Transitions: transition-all, transition-colors, transition-opacity
- Durations: duration-150 (fast), duration-200 (default)
- Hover: hover:brightness-110, hover:shadow-md, hover:bg-muted
- Active: active:scale-[0.98] (press feedback)

---

## Opacity Hierarchy

- Primary: text-foreground
- Secondary: text-muted-foreground
- Subtle: text-muted-foreground/50
- Very Subtle: text-muted-foreground/25

---

## Signal Badges

- BUY: `bg-emerald-500/10 text-emerald-400`
- SELL: `bg-red-500/10 text-red-400`
- HOLD: `bg-amber-500/10 text-amber-400`

---

## Top 10 Principles

1. OKLCH colors for uniformity
2. Mobile-first responsive
3. Subtle borders (border-border/50)
4. Opacity for hierarchy
5. Consistent 4px grid
6. Status: Emerald/Red/Amber
7. Smooth transitions
8. Semantic color names
9. Icons for status, not decoration
10. Monospace for numbers


