
# TradingAgents Design System Summary

## What I Found

I've analyzed the design language across 5 key pages:
- ScanHistoryPage (scan results grid)
- HomeDashboard (hero section & quick stats)
- AccountsDashboard (trading accounts)
- ScanDetailPage (results table)
- AnalysisDashboard (analysis display)

## Core Design Elements

### Colors (OKLCH Color Space)
- Primary: Purple/Blue - oklch(0.55 0.24 290)
- Status: Emerald (success), Red (failure), Amber (warning)
- Dark mode with proper contrast adjustment

### Typography
- Font: Geist Variable
- Page titles: text-3xl font-bold
- Body: text-sm
- Labels: text-xs uppercase

### Spacing (4px Grid)
- Gap baseline: gap-4 (16px)
- Card padding: p-5 (20px)
- Table cells: px-4 py-3
- Radius: rounded-xl (cards), rounded-2xl (containers)

### 12 Key Component Patterns
1. Stat card grids (2→5 cols responsive)
2. Stat cards with icons
3. Status indicators (dots & boxes)
4. Signal badges (BUY/SELL/HOLD)
5. Tables with hover effects
6. Hero sections with gradients
7. Card grid items
8. Empty states
9. Modals & dialogs
10. Buttons (primary/secondary)
11. Loading states
12. Score bars

## Key Design Principles

✓ OKLCH for perceptually uniform colors
✓ Mobile-first responsive approach
✓ Opacity hierarchy for visual emphasis
✓ Subtle borders (border-border/50 standard)
✓ Smooth transitions on all interactions
✓ Status colors: Emerald/Red/Amber semantic meanings
✓ Consistent 4px spacing grid
✓ Icons for status/action, not decoration
✓ Accessible components (Base UI foundation)
✓ Monospace for numeric alignment

## Files Created

✓ DESIGN_PATTERNS.md (214 lines)
  Complete reference with all patterns, colors, and usage examples


