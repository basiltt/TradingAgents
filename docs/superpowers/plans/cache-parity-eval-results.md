# Cache Behavioral-Parity Eval — Results

**Status: RUN — PASS** (executed 2026-06-06 10:37 UTC, symmetric K-sampling, via the
local Anthropic-compatible proxy at `localhost:4141` — `claude-sonnet-4.6`, no
Anthropic spend). The P3 system→human role move shows **no systematic directional
drift** (McNemar p=1.0000) and modal agreement 1.000 vs OLD across
N=30 fixtures. See methodology below.

## Gate rule (must PASS before `prompt_cache_enabled` may default ON)
- new-MODAL vs old-MODAL decision-label agreement >= (1 − noise_floor) over N>=30 fixtures
- McNemar's exact test p > 0.05 (no systematic directional drift)

## Result
- Date: 2026-06-06 10:37 UTC
- Model: anthropic / claude-sonnet-4.6 (via localhost:4141 proxy; dummy key)
- N fixtures: 30
- K samples per arm: 5 (both OLD and NEW sampled symmetrically; 300 calls total)
- Noise floor (pooled, both arms): 0.007
- New-vs-old MODAL agreement: 1.000 (threshold >= 0.993)
- McNemar exact p: 1.0000 (alpha 0.05)
- **Verdict: PASS** — every NEW modal decision matched OLD's across all 30 fixtures;
  zero directional drift.

## Methodology (and the bug a first run exposed)
The eval samples BOTH prompt forms K=5 times per fixture at temperature 0.7,
reduces each arm to its modal label, and compares mode-vs-mode. This symmetry
matters: an earlier run sampled OLD 5× (denoised) but NEW only once, then compared
OLD's denoised mode against NEW's single noisy draw against a threshold derived
from OLD alone. That asymmetric 1-vs-5 comparison failed an event that is ~18%
likely under the null hypothesis (≥1 lone-tail disagreement across 30 fixtures) —
a brittle point estimate sitting next to a proper exact-binomial test. It produced
a spurious FAIL on exactly one fixture (SOLUSDT 2026-02-11: OLD drew SELL 5/5, NEW
drew HOLD 1/1).

A direct disambiguation probe resampled that fixture's NEW arm:
```
SOLUSDT 2026-02-11
  OLD x7: [SELL,SELL,SELL,HOLD,SELL,SELL,SELL]  mode=SELL (6/7)
  NEW x7: [SELL,SELL,SELL,SELL,SELL,SELL,SELL]  mode=SELL (7/7)
  => MATCH — NEW's lone HOLD was the ~1/6 tail of a SELL-heavy mixture, not a
     role-move effect. OLD itself threw a HOLD that round.
```
The fixture's true decision distribution is ~85% SELL / ~15% HOLD on BOTH arms;
the role move did not change it. In the definitive symmetric run this same fixture
came back OLD=5/5 SELL, NEW=5/5 SELL. The harness was corrected to sample NEW K
times too (budget N*K*2 = 300 calls) and the change is locked by regression tests
(`test_evaluate_pass_symmetric_*`).

## Harness decision-extraction fix (decision-first task template)
The very first attempt produced ~50% `None` decisions: `market_analyst`, driven
tool-less, wrote a long analysis report and ran out of `max_tokens` before the
`FINAL TRANSACTION PROPOSAL` line. The task template was changed to demand the
proposal line FIRST (then ≤2 sentences of justification), applied IDENTICALLY to
OLD and NEW so it cannot bias the comparison. Post-fix parseability was ~100%.

## Static evidence the branch also rests on
- **Content preserved byte-for-byte** across the 3 restructured sites — verified
  four ways (AST extraction, live render, two independent reviewers:
  `stable_system + volatile_context == original`, char-for-char).
- The role move (volatile date/instrument: system → first human turn) is the ONLY
  change; the model receives identical content.
- Feature ships **default-OFF**; caching only activates on an explicit
  Anthropic+Sonnet config (P1: 3 of 29 sites clear threshold). Blast radius small.

## How to reproduce
```
# Against real Anthropic (spends ~300 calls):
export ANTHROPIC_API_KEY=sk-...     # direct api.anthropic.com (bypass any proxy)
python scripts/cache_parity_eval.py --run
# Against the local Copilot proxy (free): translate messages to the Anthropic
# Messages API, model claude-sonnet-4.6, x-api-key: dummy, trust_env bypassed —
# the proxy passes Anthropic cache fields through and accepts a dummy key.
```
Budget: N*K*2 = 30*5*2 = 300 model calls (both arms, K=5). Temperature 0.7.
NOTE: a local proxy that sets `ANTHROPIC_BASE_URL` must serve the requested model
(the Copilot proxy serves dot-notation `claude-sonnet-4.6`, not dash-notation).

## Operational caveats (must-know before enabling)
1. **The prompt restructure ships to ALL users unconditionally.** P3 moved the
   volatile date/instrument/price from the system role into a human turn for 3
   analysts (market, fundamentals, crypto/technical) — for every provider, flag on
   or off. Content is byte-for-byte identical (verified 4 ways) and litellm merges
   the two consecutive user turns, so no 400 and no dropped content. The only change
   is role placement, now validated by the parity eval above (agreement 1.000,
   McNemar p=1.0). The `prompt_cache_enabled` flag gates ONLY the `cache_control`
   marker, NOT the restructure.
2. **`prompt_cache_enabled` does nothing for non-Anthropic providers.** The default
   provider is OpenAI, which auto-caches server-side. Our injection only fires for
   `anthropic/*` models. A user enabling the flag on OpenAI/Gemini/etc. gets no
   change from us (those providers cache automatically regardless). Set expectations
   accordingly in any UI copy.
3. **Caching only helps 3 sites, Anthropic+Sonnet only** (P1: those clear the 1024
   minimum; none clear Opus's 4096; the AI Manager prompt is sub-threshold and is
   intentionally NOT cached). The feature is correct and safe but its savings are
   narrow — set ROI expectations accordingly.
4. **Deploy: reconcile uv.lock first.** pyproject pins litellm/langchain-community/
   langchain-anthropic/langchain-core ranges; the committed uv.lock predates the
   litellm pin. `uv sync --frozen` will fail until the lock is regenerated AND the
   re-resolved versions (litellm 1.87.x etc.) are tested. Do this as a separate,
   verified step before deploying — do not blind-commit a re-resolved lock.

### uv.lock regeneration — TESTED, found un-installable (2026-06-06)
Per the "regenerate + test the lock" decision, `uv lock` was run. It resolves to
litellm 1.87.1, langchain-core 1.4.1, openai 2.41.0, anthropic 0.106.0 (all within
the pinned `<2`/`<0.5` ranges). **`uv sync` to that lock FAILS in this environment:**
litellm 1.87.1 pulls `tiktoken 0.9.0`, which has no prebuilt wheel for the
Python 3.14 / platform combo and needs a Rust toolchain to build from source.
Result: the regenerated lock is **not installable/testable here**, so it must NOT
be committed (shipping an unvalidated, possibly-unbuildable lock to a money path is
the larger risk). The committed lock is left at its prior state; the installed,
fully-tested env stays litellm 1.83.7 / langchain-core 1.3.2 / anthropic 0.x.
**Deploy action:** reconcile the lock in the actual deploy environment (which must
have a Rust toolchain or prebuilt tiktoken wheels), run the suite there against the
resolved versions, and commit the lock only after it installs+passes. Do not commit
a lock that can't be installed in the dev environment.
