# Prompt Caching — Progress Tracker

**Plan:** docs/superpowers/plans/2026-06-06-prompt-caching.md
**Spec:** docs/superpowers/specs/2026-06-06-prompt-caching-design.md
**Active skill:** superpowers (writing-plans → execution)

| Phase | Status | Notes |
|---|---|---|
| P0 Deps + tracker | DONE | pyproject pinned (eebcca4); tracker + tag (5d7d7b2). uv.lock NOT regenerated — see blocker log. |
| P1 Recon (GO/NO-GO) | DONE | A=9 B=4 C=15 D=1 (29 sites). GO only: market_analyst(1526), fundamentals_analyst(1124), crypto/technical(1030,fragile) clear Sonnet 1024; NONE clear Opus 4096; all B sub-threshold; AI Mgr 731-799 sub-threshold → DO NOT cache. See P1 sections below. |
| P2 Param fix | DONE | _sampling_params + litellm adaptive thinking; DRY shared OPUS_ADAPTIVE_SUBSTRINGS. Both reviews passed. (cd6f3a8, 0603778, bd038df) |
| P3 Restructure | DONE | helper module + 3 cacheable sites refactored (market, fundamentals, crypto/technical); byte-for-byte preserved (verified 4 ways); Pattern B verified. Both reviews passed + cleanups. |
| P4 Inject | DONE | litellm cache_control injection (4.1 85669f8), config→client flag wiring all 3 trading_graph sites (4.2 07aaa17), real-binding wire test (4.3 aa1bb63). Task 4.4 AI Manager SKIPPED per P1 (sub-threshold) — see blocker log. |
| P5 Logging | DONE | extract_cache_metrics (base_client) + log in litellm invoke; _extract_cache_usage + 4 guarded log sites in AI Manager. Review passed + parity guard. (7e3426b, d6354f2, b586d52) |
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
- **P4 Task 4.4 (AI Manager cache_control) SKIPPED per P1** — system prompt 731-799 tok,
  sub-threshold on all models; would cache nothing. The P2 sampling-param fix to that
  file already shipped (the independently-valuable part).

## OLD-prompt recovery for P6
- git tag `pre-cache-p3` marks the pre-restructure commit.

## Site classification (P1)

Enumerated via:
`grep -rn "llm.invoke\|chain.invoke\|\.bind_tools\|ChatPromptTemplate.from_messages\|with_structured_output\|invoke_structured_or_freetext\|bind_structured" tradingagents/agents/ | grep -v test`

Pattern legend (spec §4): **A** = `ChatPromptTemplate.from_messages([("system",…), MessagesPlaceholder])` invoked `prompt | llm.bind_tools()` (stable leading system msg → cacheable). **B** = `list[dict]` with leading `{"role":"system",…}` (cacheable). **C** = bare f-string → `llm.invoke()` / `invoke_structured_or_freetext`, no system msg, stable+volatile interleaved (NOT cacheable). **D** = `list[dict]` user-only, no system (NOT cacheable).

> Note: the structured agents (trader, risk_manager, compliance_officer, research_manager, portfolio_manager, crypto RM/PM) route through `bind_structured` / `invoke_structured_or_freetext` in `agents/utils/structured.py`. That helper passes the caller's `prompt` straight through, so the Pattern is determined by **what each caller builds**, not by the helper. The grep line for those is the `invoke_structured_or_freetext(...)` call site.

| Site (file:line) | Pattern | Candidate? | Notes |
|---|---|---|---|
| analysts/market_analyst.py:75 (chain.invoke) | A | yes | `from_messages([(system,…), MessagesPlaceholder])`; system = boilerplate + `{tool_names}` + `{system_message}` (large indicator catalog) + volatile date/instrument tail |
| analysts/news_analyst.py:49 | A | yes | same shape; smaller catalog |
| analysts/social_media_analyst.py:44 | A | yes | same shape |
| analysts/fundamentals_analyst.py:55 | A | yes | same shape |
| crypto_analysts.py:125 (technical) | A | yes | shared `_ANALYST_SYSTEM_PREFIX`; stable = boilerplate+`{tool_names}`+`{system_message}`; volatile tail adds date/instrument/`current_price_context` |
| crypto_analysts.py:190 (derivatives) | A | yes | shared prefix |
| crypto_analysts.py:237 (news) | A | yes | shared prefix |
| crypto_analysts.py:290 (fundamentals) | A | yes | shared prefix |
| crypto_analysts.py:339 (social) | A | yes | shared prefix |
| trader/trader.py:147 (Pass 1 Direction) | B | yes | `[{"role":"system","content":_DIRECTION_SYSTEM}, {"role":"user",…}]` — clean static system const |
| trader/trader.py:198 (Pass 2 Levels) | B | yes | `[{"role":"system","content":_LEVELS_SYSTEM}, …]` — clean static system const (trader is **two** B sites) |
| risk/risk_manager.py:108 | B | yes | `[{"role":"system","content":_RISK_SYSTEM}, …]` — clean static const |
| compliance/compliance_officer.py:80 | B | yes | `[{"role":"system","content":_COMPLIANCE_SYSTEM}, …]` — clean static const |
| compliance/execution_monitor.py:63 | C | no | `_MONITOR_PROMPT` is ONE f-string (instrument/price/decision interleaved) → `llm.invoke(prompt)`, no system msg |
| crypto_analysts.py:409 (confluence_checker) | C | no | f-string → `llm.invoke(prompt)` |
| crypto_analysts.py:462 (bull_researcher) | C | no | f-string (reports interleaved) → `llm.invoke` |
| crypto_analysts.py:517 (bear_researcher) | C | no | f-string → `llm.invoke` |
| crypto_analysts.py:591 (research_manager) | C | no | f-string → `invoke_structured_or_freetext` (string prompt → HumanMessage, no system) |
| crypto_analysts.py:786 (risk_bull_debater) | C | no | f-string → `llm.invoke` |
| crypto_analysts.py:845 (risk_bear_debater) | C | no | f-string → `llm.invoke` |
| crypto_analysts.py:928 (crypto PM) | C | no | f-string → `invoke_structured_or_freetext`, no system |
| managers/research_manager.py:60 | C | no | f-string → `invoke_structured_or_freetext`, no system |
| managers/portfolio_manager.py:80 | C | no | f-string → `invoke_structured_or_freetext`, no system |
| researchers/bull_researcher.py:34 | C | no | f-string (reports interleaved) → `llm.invoke` |
| researchers/bear_researcher.py:36 | C | no | f-string → `llm.invoke` |
| risk_mgmt/aggressive_debator.py:33 | C | no | f-string → `llm.invoke` |
| risk_mgmt/conservative_debator.py:33 | C | no | f-string → `llm.invoke` |
| risk_mgmt/neutral_debator.py:33 | C | no | f-string → `llm.invoke` |
| crypto_analysts.py:697 (crypto_trader) | D | no | `messages = [{"role":"user","content":base_prompt}]` — user-only, no system; retry loop appends assistant/user |

**Tally: Pattern A = 9 (4 stock + 5 crypto analysts), Pattern B = 4 (trader ×2, risk_manager, compliance_officer), Pattern C = 15, Pattern D = 1. Total = 29 sites.** Only A + B (13 sites) are structural cache candidates. (Matches the plan's ~9 A / ~3 B / ~14 C / ~1 D estimate; trader is actually **two** B sites because of its two-pass Direction/Levels design.)

## Token counts (P1)

Measured with `scripts/measure_cache_prefixes.py` (litellm `token_counter`, model `claude-sonnet-4-6` — the Anthropic tokenizer is shared across Sonnet/Opus 4.x, so it's a valid proxy for both thresholds). Method: a capture LLM intercepts each analyst's fully-rendered system message, the volatile tail (`For your reference, the current date is …` / instrument / live-price) is stripped, and the **REAL** tool JSON schemas are counted via `convert_to_openai_tool`. **This models the post-P3-restructure cacheable prefix** = tool schemas + stable system text (boilerplate + `tool_names` + static catalog), which is what an Anthropic cache breakpoint on the first system block actually covers (tools precede system in the request).

Anthropic minimum cacheable prefix: **Sonnet 4.x = 1024 tok, Opus 4.x = 4096 tok**. Below threshold → silently no cache.

| Site | tokens (sys + tools) | clears Sonnet (1024) | clears Opus (4096) |
|---|---|---|---|
| stock/market_analyst (A) | **1526** (990 + 536) | **YES** | no |
| stock/fundamentals_analyst (A) | **1124** (298 + 826) | **YES** | no |
| crypto/technical_analyst (A) | **1030** (349 + 681) | **YES** (fragile, +6) | no |
| crypto/derivatives_analyst (A) | 693 (314 + 379) | no | no |
| stock/news_analyst (A) | 677 (264 + 413) | no | no |
| crypto/news_analyst (A) | 630 (217 + 413) | no | no |
| crypto/social_analyst (A) | 563 (272 + 291) | no | no |
| stock/social_media_analyst (A) | 517 (315 + 202) | no | no |
| crypto/fundamentals_analyst (A) | 381 (275 + 106) | no | no |
| risk_manager/_RISK_SYSTEM (B) | 332 | no | no |
| trader/_LEVELS_SYSTEM (B) | 263 | no | no |
| compliance/_COMPLIANCE_SYSTEM (B) | 227 | no | no |
| trader/_DIRECTION_SYSTEM (B) | 148 | no | no |

(Pattern B has no tools — counts are the static system constant alone. These are the *system* prefix; the volatile data lives in the user turn, so the system const is the whole cacheable prefix.)

### GO/NO-GO decision

- **Sites caching on Sonnet (≥1024):** stock/market_analyst (1526), stock/fundamentals_analyst (1124), crypto/technical_analyst (1030 — only +6 over the line, **fragile**: any prompt/tool trim drops it below). **3 of 9 Pattern A sites; 0 of 4 Pattern B sites.**
- **Sites caching on Opus (≥4096):** **NONE.** The largest prefix (1526) is 2.7× short of Opus's 4096 floor. On Opus, prompt caching does nothing for any agent site.
- **Pattern B (trader ×2 / risk / compliance):** 148–332 tok — all far sub-threshold on every model. **SKIP all B sites.**
- **Pattern C / D (16 sites):** not cacheable by structure (no stable leading system msg). Out of scope regardless of tokens.

**REALISTIC VERDICT — Anthropic `cache_control` is LOW-VALUE for this codebase:**

1. **Default models are OpenAI** (`gpt-5.4` / `gpt-5.4-mini` per project config). OpenAI **auto-caches** prompts ≥1024 tokens with **zero code changes** — the `cache_control` path we're building only ever executes for users who explicitly configure an Anthropic model. So this whole feature is a niche-config optimization, not a default-path win.
2. **For those Anthropic users, only 3 analyst sites clear Sonnet 1024, and 0 clear Opus 4096.** Opus users get nothing. Sonnet users get caching on at most 3 of 29 sites — and one of those (crypto/technical) is +6 tokens over the line, so it's one prompt edit away from silently falling out of cache.
3. **Pattern A is a single-shot system prefix per agent** (the MessagesPlaceholder holds the ReAct tool-call loop, so within one analyst run the cached prefix IS reused across the 2–4 tool-call iterations — that's the genuine, if modest, win). Across separate scans the prefix only caches if the run lands inside the 5-min TTL of a prior run for the same agent+model, which is unlikely at scan cadence.

**DECISION:**
- **Implement P4 `cache_control` ONLY for the 3 sites that clear Sonnet 1024:** `stock/market_analyst`, `stock/fundamentals_analyst`, `crypto/technical_analyst`. Gate behind the provider==Anthropic + model-is-Sonnet check (Opus gets no breakpoint since nothing clears 4096).
- **SKIP all Pattern B sites** (148–332 tok, sub-threshold everywhere) and the other 6 Pattern A sites (381–693 tok, sub-threshold).
- **Treat crypto/technical as optional/fragile** — if P3 restructuring shaves any tokens it drops below 1024; re-measure after P3 before wiring it.
- Because the realistic payoff is small and Anthropic-Sonnet-only, keep the global flag **default OFF** (already the P7 plan) and do not expand scope. The P2 param-fix work (temp/max_tokens/effort→thinking) is independently worthwhile and unaffected by this verdict.

## AI Manager caching decision (P1)

Path: `backend/services/ai_manager_prompts.py::build_system_prompt` (system) +
`build_context_prompt` (volatile user turn). Provider split lives in
`ai_manager_llm_provider.py` (`call_anthropic` / `call_openai`). The system
prompt is built **separately** from the context — clean structural candidate
(stable system + volatile user), unlike the Pattern-C agents.

- **System prompt tokens:** 731 (moderate / no target / warm) to 799 (conservative + daily target + cold_start). Measured via `build_system_prompt(...)` + litellm. **Clears 1024? NO** (and nowhere near Opus 4096). Only the system prompt is stable; `build_context_prompt` (positions, wallet, indicators, regime, memory) changes every cycle and is non-cacheable by nature.
- **Per-account stability:** the only system-prompt inputs (`risk_tolerance`, `cold_start`, `daily_profit_target_pct`) are fixed for a given account across cycles, so the prefix WOULD be byte-identical cycle-to-cycle — the structure is cache-friendly; the size is not.
- **Typical inter-cycle spacing:** legacy fixed mode `evaluation_interval_s` default **60s** (range 30–300); event-driven mode `safety_net_interval_s` default **180s** (range 60–600) with event triggers able to fire sooner. So **~1–3 min median**, frequently shorter on event triggers — comfortably inside a 5-min TTL.
- **1-hr TTL breakeven (reads/write ≥ 2)?** Cadence-wise **YES, easily** — at 1–3 min spacing a single account drives ~20–60 reuses/hour of a byte-stable prefix, far past the ≥2 reads/write breakeven, and even past the 1-hr-write (2×) vs 5-min-write (1.25×) tradeoff. **But this is moot:** the prefix is 731–799 tok < the 1024 Sonnet minimum, so Anthropic will not create a cache block at all regardless of TTL.
- **OpenAI note:** default AI Manager runs on OpenAI, which auto-caches ≥1024 tok — and this prefix is also under 1024 there, so it isn't auto-cached either. The size, not the provider, is the blocker.

**DECISION: DO NOT cache this path.** The stable system prefix (731–799 tok) is sub-threshold on every supported model (Sonnet 1024 / Opus 4096), so `cache_control` would be a silent no-op. Cadence is favorable (a 5-min TTL would suffice — no need for 1-hr), so **if** the system prompt is later expanded past ~1100 tokens, revisit with a **5-min TTL** (not 1-hr; the breakeven is met but 5-min is cheaper to write and the cadence never exceeds it). Skip the P4.4 AI Manager Anthropic branch for now.

## SCOPE DECISION (post-P1, user-confirmed)
- **FULL PLAN as written.** User accepts the narrow caching benefit (3 sites,
  Anthropic+Sonnet config only) in exchange for the complete instrumented feature:
  P4 cache_control for the 3 Sonnet-clearing sites, P5 logging, P6 eval gate, P7 ops
  flag, P8 3-form UI toggle. P2 param fixes ship regardless (independent bug fixes).
- P4 cache_control sites: market_analyst, fundamentals_analyst, crypto/technical (the
  3 that clear Sonnet 1024). AI Manager caching: SKIPPED (sub-threshold). Pattern B +
  the other 6 A sites: restructured by P3 for hygiene but won't cache (sub-threshold).
