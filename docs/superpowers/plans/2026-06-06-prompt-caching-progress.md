# Prompt Caching — Progress Tracker

**Plan:** docs/superpowers/plans/2026-06-06-prompt-caching.md
**Spec:** docs/superpowers/specs/2026-06-06-prompt-caching-design.md
**Active skill:** superpowers (writing-plans → execution)

| Phase | Status | Notes |
|---|---|---|
| P0 Deps + tracker | IN_PROGRESS | |
| P1 Recon (GO/NO-GO) | PENDING | classify sites A/B/C/D; token-count; cadence |
| P2 Param fix | PENDING | temp/max_tokens httpx + litellm effort→thinking |
| P3 Restructure | PENDING | Pattern-A hygiene, old builder retained behind flag |
| P4 Inject | PENDING | litellm cache_control + AI Manager — A/B only |
| P5 Logging | PENDING | cache-metric normalizer |
| P6 EVAL GATE | PENDING | behavioral-parity; must pass before default ON |
| P7 Ops flag | PENDING | global flag, default OFF |
| P8 UI toggle | PENDING | 3-form per-run toggle |

## Decisions / blockers log
- (append rows as work proceeds)

## OLD-prompt recovery for P6
- git tag `pre-cache-p3` marks the pre-restructure commit.
