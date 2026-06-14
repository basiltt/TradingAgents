# Account Forensics

Dedicated home for the **account loss-investigation initiative** — forensic root-cause
deep dives into why specific trading accounts lost (or unexpectedly gained) money, and the
tracked remediation of every issue those investigations surface.

Everything related to this task lives under this one root:

```
docs/account-forensics/
  README.md                      ← you are here (overview + index)
  accounts/
    README.md                    ← index of all per-account investigations
    <slug>/                      ← one folder per investigated account
      REPORT.md                  ← full forensic root-cause report
      FINDINGS.md                ← this account's issues + fix status (links to fixes ledger)
      runs/<date>/               ← the scratch run artifacts that produced the report
                                   (s1–s5 scripts, logs, JSON) — preserved for reproducibility
  fixes/
    README.md                    ← central fixes ledger (every issue, status, accounts affected)
    FIX-NNN-<slug>.md            ← one entry per distinct issue (root cause, fix, verification)
```

## Why this layout
- **One root** for the whole initiative — reports, findings, run details, and fixes together.
- **Per-account folders** keep each investigation self-contained, including the raw run
  artifacts that produced it (so any number can be re-checked or re-run later).
- **A central fixes ledger** because most issues are **system-wide** (e.g. the reconciler
  `net_pnl=0` bug hit several accounts; the AI-manager loss cap affects all AI-managed
  accounts). Fix detail lives once in `fixes/`; each account's FINDINGS links to it instead of
  duplicating. This keeps the truth in one place as fixes progress.

## Index

**Investigations:** [accounts/README.md](accounts/README.md)

| Account | Investigated | Result | Links |
|---------|-------------|--------|-------|
| Unni - Demo | 2026-06-14 | −$21.3 (−21%) | [REPORT](accounts/unni/REPORT.md) · [FINDINGS](accounts/unni/FINDINGS.md) · [runs](accounts/unni/runs/2026-06-14/) |

**Fixes ledger:** [fixes/README.md](fixes/README.md)

| ID | Issue | Severity | Status |
|----|-------|----------|--------|
| [FIX-001](fixes/FIX-001-reconciler-pnl-zero.md) | Reconciler closed-PnL window excludes records whose `createdTime` predates `opened_at` (hides real losses) | High | **fixed** |
| [FIX-002](fixes/FIX-002-emergency-orphan-race.md) | Emergency close omits a still-open loser (WS buffer race) | Critical | **fixed** |
| [FIX-003](fixes/FIX-003-ai-3pct-loss-cap.md) | Big-but-calm losers never closed (3% soft cap skips them, no force-close backstop) | Critical | **fixed** |
| [FIX-004](fixes/FIX-004-emergency-rearm-gap.md) | Post-emergency disarm leaves a large loser unprotected | High | identified |
| [FIX-005](fixes/FIX-005-short-bounce-signal-guard.md) | Structured signal shorts oversold/bounce-prone coins | High | identified |

## How to run a new investigation
Use the **`investigate-account`** skill: `/investigate-account <account label or UUID> [hypothesis]`.
It runs the full six-stage deep dive against production (read-only), and on completion writes
`accounts/<slug>/REPORT.md` + `FINDINGS.md`, saves run artifacts under `accounts/<slug>/runs/<date>/`,
and reconciles findings into the [fixes ledger](fixes/README.md) (linking to an existing `FIX-NNN`
or adding a new one). See the skill at `~/.claude/skills/investigate-account/`.

## Related
- [Environment map](../ENVIRONMENT.md) — prod/dev access, DB, MCP, skills
