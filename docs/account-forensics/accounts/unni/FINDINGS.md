# Unni - Demo — Findings

**Account:** Unni - Demo (`3aca7442-2bd0-44c6-b4ef-bc46a9593f35`) · Cohort B
**Investigated:** 2026-06-14 · **Full report:** [REPORT.md](REPORT.md)
**Result:** $100.9 → $79.59 (**−$21.3 real**; ledger shows only −$1.64 due to FIX-001)

## Summary
~88% of the loss came from **one ESPORTS short** that the exit machinery orphaned: blocked from
the AI manager's normal close path (FIX-003), missed by the emergency close (FIX-002), left
unprotected by post-emergency disarm (FIX-004), then force-closed by the reconciler with its
loss booked as $0 (FIX-001). The trade was also a low-quality signal to begin with (FIX-005).
The "name starts with U" hypothesis was tested and **refuted**.

## Issues found in this account

| Issue | Ledger entry | Severity | Status | Notes |
|-------|-------------|----------|--------|-------|
| ESPORTS loss booked as `net_pnl=0` (`external` close) | [FIX-001](../../fixes/FIX-001-reconciler-pnl-zero.md) | High | **fixed** | Window padding + backfill (net_pnl now −19.078) |
| Emergency close omitted ESPORTS (WS buffer race) | [FIX-002](../../fixes/FIX-002-emergency-orphan-race.md) | Critical | **fixed** | Exchange-snapshot union + execution_result persisted |
| 3% loss cap blocked standard-path close of ESPORTS | [FIX-003](../../fixes/FIX-003-ai-3pct-loss-cap.md) | Critical | **fixed** | New hard cap (max_position_loss_pct=8%) force-closes big losers |
| Post-emergency disarm left loser unprotected | [FIX-004](../../fixes/FIX-004-emergency-rearm-gap.md) | High | **fixed** | Ref-equity reseed floored by open losses (+ FIX-003 backstop) |
| Counter-trend / oversold-bounce short signal | [FIX-005](../../fixes/FIX-005-short-bounce-signal-guard.md) | High | **fixed** | Deterministic trend-align + falling-knife filter (backtest +6.7pt win); shipped end-to-end as the "Best Winrate" preset + tight geometry; live gate interval bug fixed ([CHANGELOG](../../fixes/work/FIX-005/CHANGELOG.md)) |

## Hypotheses tested
| Hypothesis | Verdict | Evidence |
|-----------|---------|----------|
| "Loss is because the name starts with 'U' (low priority)" | **REFUTED** | Alphabetical order confirmed (Unni 20/21) but fills not worse; r(rank,equity)≈0; worst losers are mid-alphabet. REPORT §5 |
| "AI manager caused the losses" | **PARTLY TRUE** | AI manager's exit logic (FIX-002/003/004) is the proximate cause, but via structural flaws, not bad individual reasoning. REPORT §3 |

## Loss attribution
| Source | Amount |
|--------|--------|
| ESPORTS short orphaned → full stop-loss | ≈ −$18.6 |
| 6 other scanner trades, net | −$1.64 |
| **Total (equity)** | **≈ −$21.3** |

## Status rollup
All 5 issues are **fixed** (implemented + tested locally; not yet prod-verified). FIX-005 was
additionally **productized** end-to-end (the "Best Winrate" preset + backtest wiring) and a live
gate interval bug was fixed — see [`work/FIX-005/CHANGELOG.md`](../../fixes/work/FIX-005/CHANGELOG.md).
Track remediation in the [fixes ledger](../../fixes/README.md); update the Status column above as
each FIX is verified in production.
