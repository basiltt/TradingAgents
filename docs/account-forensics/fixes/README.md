# Fixes Ledger — TradingAgents

Central, system-wide record of every issue surfaced by account investigations and its
remediation. Most issues are **system-wide** (they affect many accounts), so the canonical
fix detail lives **here**, and each account's `accounts/<slug>/FINDINGS.md` links to the
relevant entry rather than duplicating it.

## How this works
- One numbered entry per distinct issue: `fixes/FIX-NNN-short-slug.md`.
- Account FINDINGS docs reference issues by ID (e.g. `FIX-001`).
- Update the **Status** here whenever a fix moves forward. Keep the per-entry file as the
  source of truth for root cause, fix approach, code locations, tests, and verification.

## Status legend
`identified` → root-caused, not yet fixed · `planned` → fix designed/approved ·
`in-progress` → being implemented · `fixed` → merged, not yet verified in prod ·
`verified` → confirmed working in prod · `wontfix` → intentionally not changing

## Ledger

| ID | Issue | Severity | Status | First seen | Accounts affected |
|----|-------|----------|--------|-----------|-------------------|
| [FIX-001](FIX-001-reconciler-pnl-zero.md) | Reconciler closed-PnL lookup window starts at `opened_at`, excluding records whose Bybit `createdTime` predates it → loss booked as `net_pnl=0` | High (data integrity) | **fixed** | Unni | Unni, Brother (both backfilled) |
| [FIX-002](FIX-002-emergency-orphan-race.md) | Emergency "close all losers" reads a racy WS buffer mid-cascade → omits a still-open loser | Critical | **fixed** | Unni | system-wide (any AI-managed account) |
| [FIX-003](FIX-003-ai-3pct-loss-cap.md) | Big-but-calm losers never closed: `max_single_decision_loss_pct=3%` skips them before the LLM, with no force-close backstop | Critical | **fixed** | Unni | system-wide (AI-managed) |
| [FIX-004](FIX-004-emergency-rearm-gap.md) | Post-emergency ref-equity reset + cooldown + circuit breaker can fully disarm protection while a large loser is still open | High | identified | Unni | system-wide (AI-managed) |
| [FIX-005](FIX-005-short-bounce-signal-guard.md) | Structured signal shorts oversold/bounce-prone coins; MiniMax replay disagreed 5/7, flagging reversal risk | High (signal quality) | identified | Unni | system-wide (all accounts) |

## Notes
- Severity reflects blast radius + dollar impact, not effort.
- "Accounts affected" lists where we've *observed* the issue; system-wide issues affect more
  than the observed set — investigate before assuming an account is clean.
- When an account's investigation surfaces a NEW issue, add a row here (next ID) and link it
  from that account's FINDINGS.md.
