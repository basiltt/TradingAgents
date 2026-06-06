# Cache Behavioral-Parity Eval — Results

**Status: ATTEMPTED — INCONCLUSIVE (harness limitation found).** The harness was run
against real `api.anthropic.com` (claude-sonnet-4-6) on 2026-06-06 but **cannot
produce a trustworthy result as designed** — see "Known limitation" below. The branch
ships on STATIC evidence instead (default-OFF; byte-for-byte content preservation
proven four ways in P3). A trustworthy eval requires the harness redesign noted below
and is **not a blocker for merging a default-OFF feature** — it IS a prerequisite
before `prompt_cache_enabled` is ever defaulted ON.

## Known limitation (why the run was inconclusive)
The harness drives `market_analyst` **without its tools**. In production that analyst
calls indicator tools and then emits `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`.
Tool-less, the model writes analysis prose and frequently never reaches the proposal
line within the token budget — so the strict parser (correctly) returns `None` for
~half the calls. A live probe + the first fixture confirmed this:
```
[1/30] BTCUSDT 2026-01-08  old=[None, None, None, 'BUY', 'BUY']  new=None
```
Comparing mostly-`None` distributions is statistically meaningless, so the run was
stopped after 1 fixture (~6 calls, negligible spend). NOTE: an earlier version of the
parser had a worse bug — a "last BUY/HOLD/SELL token anywhere" fallback that misread
"RSI is **not a sell signal**" as a SELL decision. That fallback was removed (commit
`fix(caching): strict decision parser...`); the parser is now honest, which is what
exposed the deeper harness-design issue.

## What a trustworthy eval needs (harness redesign — future work)
Pick one, then re-probe before spending the full budget:
1. **Force a decision-only response** — strip the report/tool framing; prompt the model
   to output ONLY the `FINAL TRANSACTION PROPOSAL` line for the snapshot. Cleanest;
   still exercises the system→human role move (the variable under test).
2. **Wire mock tools** so `market_analyst` behaves like production and reaches its
   proposal line.
3. **Use a structured-decision agent** (e.g. `trader` via `bind_structured`) — but note
   that's Pattern B (already-stable system), so it doesn't test the P3 role-move.
Option 1 is recommended: minimal, and it isolates exactly the role-move variable.

## Static evidence the branch ships on (in lieu of the eval)
- **Content preserved byte-for-byte** across the 3 restructured sites — verified four
  ways: AST extraction, live render check, and two independent reviewers
  (`stable_system + volatile_context == original`, char-for-char).
- The role move (volatile date/instrument: system → first human turn) is the ONLY
  change; the model receives identical content.
- Feature ships **default-OFF**; caching only activates on an explicit
  Anthropic+Sonnet config (P1: 3 of 29 sites clear threshold). Blast radius is small.

## Gate rule (unchanged — applies before any default-ON)
Before `prompt_cache_enabled` may default to ON (a separate, evidence-backed PR), a
**fixed** harness MUST be run and PASS:
- new-vs-old decision-label agreement >= (1 - noise_floor) over N>=30 fixtures
- McNemar's test p > 0.05 (no systematic directional drift)

## How to run (after the harness is fixed)
```
export ANTHROPIC_API_KEY=...   # direct api.anthropic.com (bypass any local proxy)
python scripts/cache_parity_eval.py --run
```
Approx cost: ~180 model calls (N=30 fixtures x K=5 noise-floor + N new). Use Sonnet.
NOTE: if a local proxy sets `ANTHROPIC_BASE_URL` (e.g. a Copilot proxy on :4141 that
doesn't serve Claude models), unset it so calls reach real Anthropic.

## Operational caveats (must-know before enabling)
1. **The prompt restructure ships to ALL users unconditionally.** P3 moved the
   volatile date/instrument/price from the system role into a human turn for 3
   analysts (market, fundamentals, crypto/technical) — for every provider, flag on
   or off. Content is byte-for-byte identical (verified 4 ways) and litellm merges
   the two consecutive user turns, so no 400 and no dropped content. The only change
   is role placement, which the (currently inconclusive) parity eval was meant to
   validate. The `prompt_cache_enabled` flag gates ONLY the `cache_control` marker,
   NOT the restructure.
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
