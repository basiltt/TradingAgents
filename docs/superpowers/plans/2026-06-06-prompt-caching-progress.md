# Prompt Caching — Progress Tracker

**Plan:** docs/superpowers/plans/2026-06-06-prompt-caching.md
**Spec:** docs/superpowers/specs/2026-06-06-prompt-caching-design.md
**Active skill:** superpowers (writing-plans → execution)

| Phase | Status | Notes |
|---|---|---|
| P0 Deps + tracker | DONE | pyproject pinned (eebcca4); tracker + tag (5d7d7b2). uv.lock NOT regenerated — see blocker log. |
| P1 Recon (GO/NO-GO) | PENDING | classify sites A/B/C/D; token-count; cadence |
| P2 Param fix | PENDING | temp/max_tokens httpx + litellm effort→thinking |
| P3 Restructure | PENDING | Pattern-A hygiene, old builder retained behind flag |
| P4 Inject | PENDING | litellm cache_control + AI Manager — A/B only |
| P5 Logging | PENDING | cache-metric normalizer |
| P6 EVAL GATE | PENDING | behavioral-parity; must pass before default ON |
| P7 Ops flag | PENDING | global flag, default OFF |
| P8 UI toggle | PENDING | 3-form per-run toggle |

## Decisions / blockers log
- **P0 (uv.lock):** The committed `uv.lock` was already stale (litellm absent from
  it). Running `uv lock` re-resolves to UNTESTED majors: litellm 1.87.1,
  langchain-core 0.3.83→1.4.1, openai→2.41 (~100 pkgs), driven by the existing
  `langchain-google-genai>=4.0.0` pin forcing langchain-core 1.x. **Decision:** commit
  only the pyproject pins; leave uv.lock untouched. The *installed* env is already
  correct (litellm 1.83.7, lc-community 0.4.1, lc-anthropic 1.4.2), so caching work is
  unblocked. **Follow-up (separate, out of this feature):** a tested lock
  reconciliation pass before any `uv sync` in CI/deploy.

## OLD-prompt recovery for P6
- git tag `pre-cache-p3` marks the pre-restructure commit.
