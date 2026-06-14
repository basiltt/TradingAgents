# Account Investigations

Per-account forensic root-cause investigations. Each account has its own folder:

```
accounts/<slug>/
  REPORT.md     full forensic root-cause report (scan → signal → AI-manager → exit → reconciliation)
  FINDINGS.md   issues found in this account + fix status, linking to the central fixes ledger
  runs/<date>/  the scratch run artifacts (s1–s5 scripts, logs, JSON) that produced the report
```

Investigations are produced by the **`investigate-account`** skill (`/investigate-account <account>`).
System-wide fixes are tracked once in the [central fixes ledger](../fixes/README.md); each
account's FINDINGS links to the relevant `FIX-NNN` entries rather than duplicating them.

## Investigations

| Account | Slug | Investigated | Result | Report | Findings | Open issues |
|---------|------|-------------|--------|--------|----------|-------------|
| Unni - Demo | [unni](unni/) | 2026-06-14 | −$21.3 (−21%) | [REPORT](unni/REPORT.md) | [FINDINGS](unni/FINDINGS.md) | FIX-001..005 (all identified) |

## How to add an investigation
Run `/investigate-account <label-or-uuid> [hypothesis]`. The skill writes `REPORT.md`,
scaffolds `FINDINGS.md`, and saves run artifacts under `accounts/<slug>/runs/<date>/`, then adds
any NEW issue to the [fixes ledger](../fixes/README.md). Add a row to the table above.

## Related
- [Forensics root](../README.md) — overview of this initiative
- [Fixes ledger](../fixes/README.md) — system-wide issues + remediation status
- [Environment map](../../ENVIRONMENT.md) — prod/dev access, DB, MCP, skills
