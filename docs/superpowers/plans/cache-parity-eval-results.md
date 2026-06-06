# Cache Behavioral-Parity Eval — Results

**Status: NOT RUN.** The harness (`scripts/cache_parity_eval.py`) is built and ready
but has not been executed (deferred per the post-P1 decision — caching ships
default-OFF and the benefit is narrow: 3 sites, Anthropic+Sonnet only).

## Gate rule
Before `prompt_cache_enabled` may default to ON (a separate one-line PR), this eval
MUST be run and PASS:
- new-vs-old decision-label agreement >= (1 - noise_floor) over N>=30 fixtures
- McNemar's test p > 0.05 (no systematic directional drift)

## How to run
```
export ANTHROPIC_API_KEY=...   # or the configured provider's key
python scripts/cache_parity_eval.py --run
```
Approx cost: ~180 model calls (N=30 fixtures x K=5 noise-floor + N new). Use Sonnet.

## Result
(empty — fill in when run: noise floor, agreement %, McNemar p, PASS/FAIL, date)
