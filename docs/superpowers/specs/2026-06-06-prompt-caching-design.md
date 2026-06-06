# Prompt Caching — Design Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorming complete, pending spec review)
**Author:** Engineering (via brainstorming workflow)

---

## 1. Problem & Goal

The TradingAgents app makes a high volume of LLM calls against **9 providers**
(openai, anthropic, azure, deepseek, xai, google, openrouter, qwen, glm) through
two distinct transports:

1. **Trading graph** (`tradingagents/`) — LangChain client wrappers, ~20 agent
   prompt sites with large, stable system prompts.
2. **AI Manager** (`backend/services/ai_manager_llm_provider.py`) — raw httpx to
   `/v1/messages` (Anthropic) and `/v1/chat/completions` (OpenAI-compatible),
   looping over open positions with one stable system prompt per cycle.

**Today no caching is active**, and prompts are structured in the exact
anti-pattern that defeats caching on *every* provider: volatile content
(`current_date`, `instrument_context`) is interpolated into the **tail of the
system prompt**, which sits in the cacheable prefix and invalidates it on every
call (every date, every symbol).

**Goal:** Enable prompt caching across all providers via two complementary
mechanisms, covering both call sites, **preserving model behavior exactly**, with
cache-metric logging to verify hits and catch silent invalidation.

### Two mechanisms (do not conflate)

| Mechanism | Scope | Requires code |
|---|---|---|
| **Prefix hygiene** (stable-first, volatile-last) | All 9 providers' automatic caching | Prompt restructuring (provider-agnostic) |
| **`cache_control` injection** | Anthropic + OpenRouter→Claude only | Anthropic-specific block syntax |

Prefix hygiene is the broad win — OpenAI (the default provider), Azure, DeepSeek,
xAI, Gemini, Qwen, and GLM all cache **automatically** once the prefix is
uninterrupted. `cache_control` is the Anthropic-only add-on.

---

## 2. Decisions Locked (brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | **Both** — prefix hygiene + `cache_control` |
| 2 | Call sites | **Both** — trading graph + AI Manager |
| 3 | Behavior risk | **Preserve behavior exactly** — reorder only, never rewrite/drop |
| 4 | Observability | **Log cache metrics** (no DB/UI) |
| 5 | TTL | **5-minute ephemeral** (see rationale below) |
| 6 | Adjacent bug | **Fix** hardcoded `temperature:0.2` (400s on Opus 4.7/4.8) |
| 7 | Architecture | **Neutral split + client injection** (provider logic in clients, agents stay neutral) |

### TTL rationale (5-minute wins decisively)

A Bybit scan covers ~575 coins over ~75 minutes. Within one scan, each analyst's
stable catalog prompt is hit ~575 times → roughly **one hit every 7–8 seconds**,
far inside the 5-minute window. Every call refreshes the TTL, so the cache stays
continuously warm for the whole scan. The 1-hour TTL (2× write premium) would only
help bridge *between* scans — but a scan (75 min) exceeds even the 1h TTL, so it
buys nothing. 5-minute is both warm-throughout and cheapest (1.25× write).

### Provider caching matrix (research, 2026-06-06)

| Provider (code) | Caching | Needs code | Discount | Min prefix |
|---|---|---|---|---|
| Anthropic | yes | **yes — `cache_control`** | ~90% read | 1024–4096 tok |
| OpenAI (default) | yes | no (automatic) | up to ~90% | 1024 tok |
| Azure OpenAI | yes | no (automatic) | tiered→100% | 1024 tok |
| DeepSeek | yes | no (automatic) | very high | 64-tok blocks |
| xAI (Grok) | yes | no (automatic) | reduced (undocumented) | undocumented |
| Google Gemini (OAI-compat) | implicit | no¹ | ~90% | 2048+ tok |
| Qwen / DashScope | yes | no (implicit) | ~80% | ~1024 tok |
| Zhipu GLM | yes | no (automatic) | ~50% | unspecified |
| OpenRouter | depends | mixed² | passthrough | varies |

¹ Gemini implicit caching *should* fire on the OpenAI-compat endpoint but Google
doesn't document it for that path — **validate empirically**.
² OpenRouter auto-caches OpenAI/DeepSeek/Grok/Gemini; **requires `cache_control`
for Anthropic and Qwen** models routed through it.

> Confidence note: automatic-vs-code distinction is solid; exact discount %,
> thresholds, and some model names are ballpark — not contractual.

---

## 3. Architecture

**Core principle: reorder, don't rewrite.** Volatile content moves out of the
system-prompt tail into the first human/message turn, leaving the system prompt
byte-identical across all 575 coins and all dates. The same words reach the model;
only their position changes.

```
┌─ Agents (tradingagents/agents/...) ──────────────────────┐
│  Build prompt as STABLE system block + VOLATILE message   │
│  segment via a shared helper. Provider-NEUTRAL.           │
└───────────────────────────┬───────────────────────────────┘
                            │ provider-neutral prompt
        ┌───────────────────┴───────────────────┐
        ▼                                         ▼
┌─ AnthropicClient ─────────┐      ┌─ OpenAI/Gemini/DeepSeek/… ─┐
│ Inject cache_control on   │      │ No-op: automatic prefix     │
│ stable block (5-min TTL)  │      │ caching now works           │
└───────────────────────────┘      └─────────────────────────────┘

┌─ AI Manager (ai_manager_llm_provider.py) ────────────────┐
│  Raw httpx. Anthropic branch: system as cache_control     │
│  block. OpenAI-compat branch: already prefix-clean.       │
│  + fix hardcoded temperature:0.2 (400s on Opus 4.7/4.8)   │
└───────────────────────────────────────────────────────────┘
```

---

## 4. Component: Prefix Hygiene Refactor (Trading Graph)

### Transformation

Before (`market_analyst.py` + ~17 siblings):
```
system = "...You have access to {tool_names}.{system_message}For your reference,
          the current date is {current_date}. {instrument_context}"   ← volatile tail
messages = MessagesPlaceholder("messages")
```
After:
```
system = "...You have access to {tool_names}.{system_message}"   ← STABLE
messages = [ HumanMessage("Context for this analysis — current date:
                           {current_date}. {instrument_context}"),  ← VOLATILE
             MessagesPlaceholder("messages") ]
```

### Shared helper — `tradingagents/agents/utils/prompt_cache.py`

- `split_cacheable_prompt(stable_system, volatile_context, tool_names, ...)` →
  structured message list with the stable/volatile boundary marked.
- Marks the stable `SystemMessage` with `additional_kwargs={"cache_boundary": True}`
  — a sentinel the Anthropic client reads (§5). Non-Anthropic clients ignore it.
- Keeps all ~20 sites uniform (one-line change each, not hand-rolled).

### Sites in scope (~20)

4 stock analysts, 5 crypto analyst nodes (`crypto_analysts.py`), bull/bear
researchers (2), 3 risk debators, research + portfolio managers (2), trader,
risk_manager, 2 compliance (`compliance_officer`, `execution_monitor`).
Exact count to be confirmed during Phase 1 enumeration; "~20" is the working
estimate.

### CONTENT-PRESERVATION INVARIANT (hard requirement)

Every content segment the model receives today — `current_date`,
`instrument_context`, `tool_names`, `system_message`, collaboration preamble,
`get_language_instruction()` output, surrounding prose — **must still reach the
model**. Reorder only; never drop.

**Verified mechanically:** per-site test assembles old vs new prompt with
identical inputs, normalizes whitespace, asserts **old-content ⊆ new-content**.

### Two site shapes

- **Tail-volatile (analysts):** volatile token at the end → clean hoist to message
  turn. Full stable prefix caches.
- **Mid-volatile (compliance/managers/trader — 6 sites):** `{instrument_context}`
  is embedded mid-prompt (e.g. `## Asset\n{instrument_context}\n\n## Rules...`).
  **Do NOT reorder stable content around it** (would risk behavior drift). Per-site:
  either (a) keep content order exactly and cache only the stable span *before* the
  insertion, or (b) hoist the volatile block to the message turn **only if** the
  remaining stable text reads identically without it. Content never dropped;
  order never scrambled. **Correctness wins over cache coverage.**

### Minimum-prefix caveat

Anthropic needs ≥1024 tokens (Sonnet) / ≥4096 (Opus/Haiku) of stable prefix to
cache. `market_analyst`'s catalog (~1.5–2K tok) clears Sonnet; some smaller agent
prompts may not hit 4096 on Opus — those won't cache on Opus (no error) and still
benefit on other providers. Sub-threshold sites flagged during implementation.

---

## 5. Component: Anthropic `cache_control` Injection (LangChain path)

In `NormalizedChatAnthropic` (`tradingagents/llm_clients/anthropic_client.py`),
before delegating to `super().invoke()`:

- Detect the stable `SystemMessage` carrying the `cache_boundary` marker (§4).
- Rewrite its content into Anthropic block form with
  `cache_control: {"type": "ephemeral"}` (5-min TTL) on the last stable block.
  ChatAnthropic already accepts block-format content — content-shape transform,
  not a transport change.
- Non-Anthropic clients never see this — they get the plain neutral prompt and
  rely on automatic caching.

**TTL:** 5-minute (§2 rationale). **Beta header:** none — `cache_control` is GA on
current Claude models. **Failure safety:** if marker absent or content not a clean
string, fall through to today's exact behavior (no caching, no error).

---

## 6. Component: AI Manager httpx Path + temperature Fix

**File:** `backend/services/ai_manager_llm_provider.py` — two branches
(`call_anthropic`, `call_openai`), each appearing in both `create_llm_callable`
and `create_llm_callable_with_cleanup`. **All four builders** get the treatment.

**(a) Anthropic branch — `cache_control` on system block:**
```python
"system": [{"type": "text", "text": system_prompt,
            "cache_control": {"type": "ephemeral"}}],
```
Cleanest win: AI Manager loops `for pos in positions`
(`ai_account_manager_service.py:471`) with one identical `system_prompt` per cycle
→ written once, read N−1 times.

**(b) OpenAI-compat branch — already prefix-clean.** `system_prompt` and
`context_prompt` are separate messages (system first). Stable system message
already sits at the front → automatic caching works as-is. **No structural change.**

**(c) temperature fix.** Both branches hardcode `temperature: 0.2`, which **400s on
Opus 4.7/4.8** (sampling params removed). Make sampling params **conditional** —
omit `temperature`/`top_p`/`top_k` for models/providers that reject them, matching
the provider-kwargs pattern the LangChain clients already use (precedent:
`tests/test_provider_kwargs.py`). Conservative default: when unsure, omit. Required
for caching to be testable on current Anthropic models.

---

## 7. Component: Cache-Metric Logging

**Problem:** caching silently no-ops if a stray volatile byte enters the prefix —
no error. Only the usage numbers prove it works.

**Normalizer** maps each provider's fields to one shape:

| Provider family | Cache-read field | Cache-write field |
|---|---|---|
| Anthropic | `cache_read_input_tokens` | `cache_creation_input_tokens` |
| OpenAI / Azure / DeepSeek / Grok / Qwen / GLM / Gemini-compat | `prompt_tokens_details.cached_tokens` | (none) |

Normalized record: `{provider, model, input_tokens, cache_read, cache_write,
call_site}`. Log one INFO line per call:
```
LLM cache | site=ai_manager provider=anthropic model=... input=312 cache_read=1840 cache_write=0
```
`cache_read == 0` across a fan-out → silent invalidator; grep flags it.

- **LangChain path:** read from `result.usage_metadata` / `response_metadata`
  inside the `NormalizedChatAnthropic` wrapper.
- **AI Manager path:** read from the `resp.json()` already parsed.
- **Cost:** logging only — no DB schema, no migration, no UI (matches decision #4).

---

## 8. Testing Strategy

1. **Content-preservation** (§4 invariant) — old-content ⊆ new-content per site.
2. **Prefix-stability** — assemble stable system block for two (date, symbol) pairs
   → assert **byte-identical**. This proves caching will fire.
3. **`cache_control` shape** — Anthropic path emits block w/ `ephemeral` TTL;
   non-Anthropic path emits plain content (no `cache_control` leakage).
4. **temperature-omission** — Opus 4.7/4.8 payload carries no `temperature`; older
   models/providers unaffected.
5. **Metric-normalizer** — each provider's usage JSON maps to the unified record.

TDD: tests written before implementation per phase.

---

## 9. Out of Scope (YAGNI)

- DB persistence / UI surfacing of cache savings (future "full metrics + UI").
- Gemini explicit `CachedContent` objects (implicit caching covers the win).
- 1-hour TTL (5-min is strictly better for this workload).
- Prompt wording/cleanup beyond reordering (behavior-preservation constraint).
- OpenRouter-specific `cache_control` passthrough tuning (works via Anthropic
  block format already; revisit if OpenRouter→Claude users report misses).

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Reorder changes model decisions (real money) | Reorder-only invariant + content-⊆ tests + prefix never scrambled on mid-volatile sites |
| Silent cache invalidation | Prefix-stability byte-equality test + cache-metric logging |
| Sub-4096-token prompts don't cache on Opus | Accepted; flagged per-site; still benefit on other providers |
| `cache_control` leaks to non-Anthropic provider | Injection lives only in Anthropic client/branch; shape test guards |
| temperature fix changes behavior on models that accepted 0.2 | Only omit where provider rejects it; existing models keep current params |

