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

**Goal:** **Prefix hygiene across all providers** (helps each provider's automatic
caching) plus **`cache_control` injection for native Anthropic only**, covering both
call sites, **preserving the model's content exactly and gating rollout on a
behavioral-parity eval** (see §4, §8.6 — a byte-identical *decision* guarantee is not
achievable across the system→user role move), with cache-metric logging to verify
hits and catch silent invalidation. **The broad, reliable win is the hygiene
refactor; the Anthropic `cache_control` win is conditional on Phase-1 token counts
and may be near-zero (§4, §6a).**

### Two mechanisms (do not conflate)

| Mechanism | Scope | Requires code |
|---|---|---|
| **Prefix hygiene** (stable-first, volatile-last) | All 9 providers' automatic caching | Prompt restructuring (provider-agnostic) |
| **`cache_control` injection** | **Native Anthropic provider only** (see routing note) | Anthropic-specific — system-block transform in the invoke override (§5) |

Prefix hygiene is the broad win — OpenAI (the default provider), Azure, DeepSeek,
xAI, Gemini, Qwen, and GLM all cache **automatically** once the prefix is
uninterrupted. `cache_control` is the native-Anthropic-only add-on.

> **Routing reality (verified against code).** In this app, `provider == "openrouter"`
> (and `qwen`, `glm`, `xai`, `deepseek`) route through the **OpenAI-compatible
> Chat Completions branch** — both in the LangChain layer (`OpenAIClient` →
> `NormalizedChatOpenAI`, base `openrouter.ai/api/v1`) and in the AI Manager httpx
> path (`call_openai`). They therefore **cannot receive Anthropic `cache_control`**.
> OpenRouter→Claude users get whatever automatic caching OpenRouter applies, not our
> injected breakpoints. The earlier draft's claim that "OpenRouter→Claude requires
> `cache_control`" is true of the OpenRouter API in the abstract but **not reachable
> through this codebase's routing** — so it is explicitly out of scope (§9), not a
> silent gap.

---

## 2. Decisions Locked (brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | **Both** — prefix hygiene + `cache_control` |
| 2 | Call sites | **Both** — trading graph + AI Manager |
| 3 | Behavior risk | **Preserve content exactly** (reorder/never drop) + **behavioral-parity eval gate** before rollout (see §4, §11.2) |
| 4 | Observability | **Log cache metrics** across **all** graph wrappers + AI Manager (no DB/UI) |
| 5 | TTL | **5-minute** for scanner/graph; AI Manager TTL **TBD by Phase 1 cadence check** with explicit 1-hr breakeven rule (§6a) |
| 6 | Adjacent bug | **Fix** hardcoded `temperature:0.2` **and `max_tokens:1024`** at 4 httpx sites; separate phase (P2), ordered **before** Anthropic injection |
| 7 | Architecture | **Neutral split** (agents) + **system-block transform in the invoke override** (NOT the native last-block kwarg — wrong block; NOT the sentinel — §5) |
| 8 | Enablement | **Global ops flag, default OFF** until eval passes (in scope, P7); **3-form UI toggle deferred** out of scope (§9, §11) |

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
² OpenRouter/Qwen *can* use explicit `cache_control` **at the OpenRouter/DashScope
API level**, but this app routes them through the OpenAI-compatible branch, so we
do **not** inject it — they rely on automatic caching only (see §2 routing note, §9).

> Confidence note: automatic-vs-code distinction is solid; exact discount %,
> thresholds, and some model names are ballpark — not contractual.

### Dependency versions (verified in the installed venv, 2026-06-06)

| Package | `uv.lock` pin | **Actually installed** | Relevance |
|---|---|---|---|
| `langchain-anthropic` | 0.3.15 | **1.4.2** | 1.4.2 has a **native `cache_control` kwarg** — design relies on it (§5) |
| `langchain-core` | — | 1.3.2 | Determines templating behavior that killed the sentinel approach (§5) |
| `langchain-openai` | — | 1.2.x | Hosts `NormalizedChatOpenAI` cache-token path |
| `anthropic` | — | 0.97.0 | Underlying SDK |

> ⚠️ **Lockfile drift + future-upgrade risk.** The implementation must reconcile
> `uv.lock` (stale 0.3.15) with the installed **1.4.2** and pin a **tested range**
> (floor **and** known-good ceiling, e.g. `>=1.4,<2`), not just a floor — a future
> `uv sync` to a major bump could change message serialization. Our §5 mechanism is
> a **system-block transform we write** (not the library's private
> `_apply_cache_control_to_last_eligible_block`, which targets the wrong block), so
> the coupling is to langchain-anthropic's **payload/serialization shape**, caught by
> the real-binding test (§8.3). **Phase 0 task: reconcile the lock + pin a range.**

---

## 2.5 Implementation Phases (explicit DAG — prerequisites, not just numbers)

> Iteration-2 fix (C3): phases were scattered as prose and didn't form a valid
> dependency graph (e.g. the temp fix that *unblocks* Anthropic testing came
> *after* it; the eval that *gates* rollout came after the toggle). Corrected order:

```
P0  Deps        reconcile uv.lock, pin langchain-anthropic range          (no deps)
P1  Recon       enumerate sites + exact count; token-count every stable   (P0)
    [GO/NO-GO]   prefix vs 1024/4096; measure AI Manager cadence + prefix.
                 → decides which sites/paths get cache_control at all.
P2  Param fix   conditional temperature/max_tokens in the 4 httpx sites    (P0)
                 (§6c) — UNBLOCKS Anthropic testing on Opus 4.7/4.8 (else 400).
P3  Restructure §4 prompt hygiene, OLD builder RETAINED behind ops flag    (P1)
                 — provider-agnostic; helps automatic caching immediately.
P4  Inject      §5 system-block transform (graph) + §6a AI Manager         (P1,P2,P3)
                 Anthropic branch — ONLY for sites P1 cleared.
P5  Logging     §7 cache-metric normalizer, all wrappers + AI Manager      (P3)
P6  EVAL GATE   §8.6 behavioral-parity, old-vs-new, offline spend-capped   (P3,P4)
    [GATE]       → MUST PASS before the global flag may default ON.
P7  Ops flag    global TRADINGAGENTS_PROMPT_CACHE_ENABLED, default OFF      (P3,P4)
                 → flip to ON is a separate PR justified by P6 evidence.
                 *** P7 is the last phase in THIS scope. ***
[P8 UI toggle — DEFERRED out of scope (§9); reference table in §7.5(2)]
```

**Key dependency facts the numbering must respect:**

> Section prose may say "Phase 1/2/3…" loosely — the **canonical ordering is the
> P0–P8 DAG above**; map any loose "Phase N" to it (recon = P1, param fix = P2,
> restructure = P3, injection = P4, logging = P5, eval = P6, ops flag = P7, UI = P8).
- **P2 before P4** — §6c states the Anthropic injection is *untestable* on current
  Opus until the sampling-param fix lands (the call 400s before a cache forms).
- **P3 retains the old prompt builder behind the flag** — required so **P6** can run
  old-vs-new, and so the OFF path (§8.8) is byte-identical.
- **P6 gates the default-ON flip**, not the merge. Code can land dark (flag OFF) any
  time; only enabling it for users waits on the eval.
- **P1 is a go/no-go** — if token counts show prefixes below threshold and cadence
  exceeds TTL, P4's Anthropic injection may be **cancelled** while P3 (hygiene) still
  ships for automatic-caching providers.

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
  a `ChatPromptTemplate` (or message list) whose **system message holds only the
  stable text** and whose **first human turn holds the volatile context**, with the
  `MessagesPlaceholder("messages")` after it.
- The stable system text still contains `{tool_names}` / `{system_message}`
  template vars filled by `.partial()` exactly as today — so the helper returns a
  **template**, not a pre-built `SystemMessage`. (See §5 for why this matters.)
- Keeps all ~20 sites uniform (one-line change each, not hand-rolled).

> ⚠️ **Rejected approach — the `additional_kwargs` sentinel does NOT work.**
> An earlier draft marked the stable `SystemMessage` with
> `additional_kwargs={"cache_boundary": True}` for the Anthropic client to detect.
> **Verified against installed langchain-core 1.3.2, this is unworkable:**
> (a) the tuple form `("system", text)` the agents use renders to a `SystemMessage`
> with **empty `additional_kwargs`** — the marker has nowhere to live; and
> (b) passing a **pre-built** `SystemMessage(content="...{tool_names}...",
> additional_kwargs={...})` **bypasses `.partial()` interpolation** — the template
> vars stay literal. You cannot both carry a sentinel *and* interpolate vars. The
> design below (§5) uses langchain-anthropic's **native `cache_control` mechanism**
> instead, which needs no sentinel.

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

> ⚠️ **Honest caveat — "preserve behavior EXACTLY" is weaker than it sounds, and
> the ⊆ test does NOT prove it.** Moving the date/instrument from the **system**
> role into a **human** turn changes the *role* the model sees that text in. Claude
> is trained to weight system vs user content differently, so identical words in a
> different role **can** shift outputs — and for trading decisions that means
> potentially different trades. The substring-⊆ test checks *text presence*, not
> *role* and not *decision parity*. Two consequences:
>
> 1. **Reframe the guarantee:** the design preserves **content**, and *aims* to
>    preserve behavior, but cannot *guarantee* byte-identical decisions across the
>    role move. The spec should not over-claim "exactly."
> 2. **Add a behavioral-parity gate (P6, pre-rollout):** run N fixed
>    (symbol, date, market-state) fixtures through representative agents **old prompt
>    vs new prompt**, and assert the **decision/score output matches** (e.g. same
>    BUY/HOLD/SELL, same indicator selection, or score within tolerance). If parity
>    holds, ship. If it drifts, the kill-switch (below) keeps the old path until
>    resolved. This is the real safety net; the ⊆ test is necessary but not
>    sufficient.

### Two site shapes

- **Tail-volatile (analysts):** volatile token at the end → clean hoist to the
  human turn. The whole system message is stable → caches.
- **Mid-volatile (compliance/managers/trader — 6 sites):** `{instrument_context}`
  is embedded mid-prompt (e.g. `## Asset\n{instrument_context}\n\n## Rules...`).
  Our cache breakpoint covers the **entire system block** (§5), so a system message
  that still embeds volatile bytes **does not cache at all** — there is no way to
  cache "only the span before the insertion" with this mechanism (that would need a
  hand-placed mid-content breakpoint, which we rejected). Therefore, per site:
  - **(b) hoist** the volatile block out to the human turn **only if** the remaining
    stable text reads identically without it → then it caches like a tail-volatile site.
  - **otherwise accept no caching** for that site (keep content order exactly; never
    reorder stable text around the insertion). **Correctness wins over cache coverage.**

  > Iteration-1 listed an "option (a): cache only the stable span before the
  > insertion." **Removed** — it's impossible with the §5 single-block breakpoint and
  > would silently yield `cache_read = 0`. Don't imply a sub-span cache the mechanism
  > can't produce.

### Minimum-prefix caveat (and honest ROI)

Anthropic minimum cacheable prefix is model-dependent: **Sonnet 4.x = 1024 tok,
Opus 4.x / Haiku 4.5 = 4096 tok, older Haiku/Sonnet 3.x = 2048 tok**. A stable
prefix below the threshold **silently won't cache** (no error, `cache_creation = 0`).

`market_analyst`'s catalog (~1.5–2K tok) clears Sonnet but **likely misses Opus's
4096**. Many of the ~20 agent prompts are short (researchers, debators, managers).

> **ROI honesty (Phase 1 deliverable):** before implementing the Anthropic
> injection, **count tokens for each of the ~20 stable prefixes** (via
> `client.messages.count_tokens` or `tiktoken` estimate) and record how many clear
> 1024 (Sonnet) and 4096 (Opus). If most sites are sub-4096, the **Opus cache win
> is near-zero** and the value concentrates on Sonnet + the automatic-caching
> providers. This number determines whether the Anthropic-injection work is worth
> it at all — surface it, don't bury it.

---

## 5. Component: Anthropic `cache_control` Injection (LangChain path)

> **CORRECTION (iteration 2 — the iteration-1 "native kwarg" fix was ALSO wrong).**
> Iteration 1 replaced the rejected sentinel with langchain-anthropic's native
> `cache_control` kwarg. **Verified against installed 1.4.2 source, that is wrong for
> our use case.** `_apply_cache_control_to_last_eligible_block` walks messages
> **newest-to-oldest** and puts the breakpoint on the **last eligible block** — i.e.
> the **conversation tail**, not the stable system prefix. Our prompt shape is
> `stable system → volatile human turn → growing MessagesPlaceholder`, so the native
> kwarg would mark the **volatile tail** → `cache_read = 0` forever. The native kwarg
> is designed for "cache everything up to the latest turn" (multi-turn prefix
> growth), **not** "cache the system prefix while the tail varies."

**Correct mechanism: transform the *system* message to block-form with
`cache_control` inside the `NormalizedChatAnthropic.invoke` override — AFTER
langchain has rendered the template.** The override already wraps `super().invoke`;
it receives the fully-rendered input (a `list[BaseMessage]` or a `ChatPromptValue`).
The transform:

1. Normalize input to messages (the codebase already has this exact helper pattern —
   `_input_to_messages` in `openai_client.py:42`, used by DeepSeek).
2. Find the **first `SystemMessage`** (it now holds only stable text, per §4).
3. Rewrite its `.content` from a string to a single text block with
   `cache_control: {"type": "ephemeral"}`:
   `[{"type": "text", "text": <stable>, "cache_control": {"type": "ephemeral"}}]`.
4. Delegate to `super().invoke` with the modified message list.

This places the breakpoint **exactly on the stable system prefix**, regardless of
how many turns follow. No sentinel needed — the override operates on rendered
messages where `{tool_names}`/`{system_message}` are already interpolated, sidestepping
the templating trap entirely (the iteration-1 reason the sentinel failed).

```python
# In NormalizedChatAnthropic.invoke, conceptually (gated by prompt_cache_enabled):
def invoke(self, input, config=None, **kwargs):
    if self._cache_enabled:
        msgs = _input_to_messages(input)            # reuse existing helper pattern
        for m in msgs:
            if isinstance(m, SystemMessage) and isinstance(m.content, str):
                m = m.model_copy(update={"content": [
                    {"type": "text", "text": m.content,
                     "cache_control": {"type": "ephemeral"}}]})
                # replace in list; break after first system message
        input = msgs
    return normalize_content(llm_rate_limited_invoke(super().invoke, input, config, **kwargs))
```

> Exact construction (mutate vs `model_copy`, `ChatPromptValue` handling, where the
> `_cache_enabled` flag is set from config — see §7.5) is confirmed in Phase 3 and
> asserted by the **real-binding wire-payload test (§8.3)** — which must run against
> the actual `langchain_anthropic` serializer, not a mock, so the block reaches the
> wire as `cache_control` on the system message.

**TTL:** 5-minute ephemeral (§2 rationale). **Beta header:** none — `cache_control`
is GA on current Claude models. **Failure safety:** on a non-cacheable/sub-threshold
prompt the block is inert (`cache_creation = 0`); on any unexpected input shape the
override falls through to today's behavior. **Mid-volatile sites (§4):** because the
breakpoint sits on the whole system block, a system message that *embeds* volatile
content does **not** cache at all (the volatile bytes are inside the cached span) —
see §4 corrected handling.

**Non-Anthropic clients** (`NormalizedChatOpenAI`, `DeepSeekChatOpenAI`,
`NormalizedChatGoogleGenerativeAI`) get **no** `cache_control` — they rely on
automatic prefix caching, which the §4 hygiene refactor unlocks.

**Non-Anthropic clients** (`NormalizedChatOpenAI`, `DeepSeekChatOpenAI`,
`NormalizedChatGoogleGenerativeAI`) get **no** `cache_control` — they rely on
automatic prefix caching, which the §4 hygiene refactor unlocks.

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

> **Corrected mechanism (earlier draft was factually wrong).** The earlier draft
> claimed the AI Manager "loops `for pos in positions` (`ai_account_manager_service.py:471`)
> with one identical `system_prompt` → written once, read N−1 times **within a
> cycle**." **That is false:** line 471 is inside `get_status()`, builds the status
> response, and makes **zero LLM calls**. The real LLM call fires **once per
> evaluation cycle** via the async graph node `action_generation_node`
> (`ai_manager_graph.py`), invoked through `self._graph.ainvoke(...)` in
> `ai_manager_task.py`. The system prompt evaluates **all** positions in one call
> ("act on ONE position per evaluation"), so there is **one read per cycle**, not
> N−1.
>
> **Where the benefit actually comes from:** `build_system_prompt`
> (`ai_manager/prompts.py`) depends only on **account config** (`risk_tolerance`,
> `cold_start`, `daily_profit_target_pct`) — **no per-symbol data** — so the system
> prefix is **stable across cycles** for a given account. All per-position context
> lives in `build_context_prompt` (the user turn). Caching therefore helps
> **across cycles** (consecutive evaluations of the same account reuse the cached
> system prefix), governed by the 5-min TTL and the cycle cadence.
>
> ⚠️ **This path needs BOTH independent conditions true, or it pays ≤0 — do the
> math, don't ship on vibes (M2):**
> 1. **Prefix size ≥ minimum for the configured model:** system prompt is ~600–900
>    tok — **likely below the 1024 (Sonnet) / 4096 (Opus) minimum**, so it may
>    **never cache**. Phase 1 token-counts it for the *actual models in use*.
> 2. **Median inter-cycle spacing < chosen TTL:** caching only pays if consecutive
>    cycles for an account land inside the TTL. The AI Manager is event-driven
>    (`safety_net_interval_s` fallback + emergency fast-path) — cadence is variable.
>
> **Decision rule (default-drop unless proven):** implement the AI Manager Anthropic
> injection **only if Phase 1 shows (1) AND (2)**. For the TTL choice, the 1-hour
> option costs a **2× write premium**, so it breaks even only at **reads/write ≥ 2** —
> i.e. ≥2 cache *hits* per *write*. If cadence is sparse enough to *need* 1-hour, hits
> are rare and the inequality likely fails → **don't use 1-hour; drop caching on this
> path instead.** Pick 5-min, 1-hour, or none on this inequality, not intuition.
> Prefix hygiene on the user turn still helps automatic-caching providers regardless.

**(b) OpenAI-compat branch — already prefix-clean.** `system_prompt` and
`context_prompt` are separate messages (system first). Stable system message
already sits at the front → automatic caching works as-is. **No structural change.**
This branch also serves `openrouter`, `qwen`, `glm`, `xai`, `deepseek` — none get
`cache_control` (§2 routing note); they rely on their providers' automatic caching.

**(c) Sampling/token-param fix (broader than just temperature).** Both branches
hardcode **`temperature: 0.2` AND `max_tokens: 1024`** — at **4 sites**
(`call_openai`/`call_anthropic` × `create_llm_callable`/`_with_cleanup`).
`temperature` **400s on Opus 4.7/4.8** (sampling params removed); reasoning models
may also expect `max_completion_tokens` rather than `max_tokens`. The raw-httpx
file has **no per-provider param gating today** (unlike the LangChain path, which
has allowlists in `anthropic_client.py` / `openai_client.py` and the litellm
auto-drop at `litellm_client.py:174-177`; precedent test `tests/test_provider_kwargs.py`).
Fix: introduce conditional param assembly in the httpx path — **omit `temperature`
(and `top_p`/`top_k`) for models/providers that reject them**, conservative default
omit-when-unsure. Required for caching to even be testable on current Anthropic
models, since the call 400s before any cache can form.

> **Scope note (reviewer flagged as scope creep):** this fix is logically separable
> from caching. It is **kept in scope** because (1) it lives in the exact same 4
> call-construction sites the caching change edits, and (2) the Anthropic
> `cache_control` path is **untestable on Opus 4.7/4.8 without it** (the request
> 400s first). It will be **phase P2**, ordered **before** the Anthropic injection
> (P4), so it can be reviewed and reverted independently.

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

**Where logging lives (must cover ALL providers, not just Anthropic):**

The trading graph runs through **three** wrapper classes, each with its own
`invoke` override. Logging only in the Anthropic wrapper would leave the **default
provider (OpenAI)** and Google with zero cache visibility — half-defeating the
"detect silent invalidation" goal. So the normalizer goes in a **shared place all
wrappers reach**:

- **Preferred:** a shared helper called from `llm_rate_limited_invoke`
  (`base_client.py`) — every wrapper already funnels its `super().invoke` through it,
  so one insertion point covers Anthropic, OpenAI, DeepSeek, and Google. The helper
  reads `result.usage_metadata['input_token_details']` (langchain populates
  `cache_read` / `cache_creation` uniformly across providers in current versions)
  and logs the normalized record. **Verify** the `usage_metadata` shape per wrapper
  during Phase 3 (Anthropic confirmed: `input_token_details.cache_read` /
  `cache_creation`; OpenAI-compat exposes `cache_read`).
- **AI Manager path:** read from the `resp.json()` `usage` object (currently **not
  read at all** — must be added). Anthropic: `usage.cache_read_input_tokens` /
  `cache_creation_input_tokens`. OpenAI-compat: `usage.prompt_tokens_details.cached_tokens`.

> **Reconcile with existing logging infra.** `backend/services/ai_manager_llm_logger.py`
> already exists (DB-backed, buffered flush) and `ai_manager_task.py` logs
> `result.get("_input_tokens", 0)` — which is **currently always 0** because
> `action_generation_node` never populates `_input_tokens` from `usage`. Phase 3
> should **populate that existing field from the parsed `usage`** rather than add a
> parallel logging system, and decide whether cache tokens join the existing
> DB-backed logger or stay log-only. **Do not build a second logging stack beside
> the one that's already there.**

- **Cost:** log-line normalizer is logging-only — no new DB schema, no migration,
  no UI (matches decision #4). Reusing the existing `_input_tokens`/LLM-logger
  plumbing is wiring, not a new stack.

---

## 7.5 Enablement controls — ops flag (safety) + optional UI toggle (product)

> **Iteration-2 split (was: one user-facing toggle, default on).** The review
> showed these are **two different concerns** that iteration 1 conflated:
> 1. **A global ops flag** — the actual *safety* mechanism. Cheap, no UI.
> 2. **A per-run UI toggle** — a *product* choice. Larger (3 forms + schema + types
>    + plumbing), and arguably bigger than the caching change it guards.
>
> They are now specified separately, and the **default is OFF** until the behavioral-
> parity eval (§8.6) records a pass (see C1 rationale in §6/§8). This makes the eval
> a *real* rollout gate instead of decoration.

### (1) Global ops flag — the safety mechanism (ships with the feature)

- `DEFAULT_CONFIG["prompt_cache_enabled"] = False` in
  `tradingagents/default_config.py`, env-overridable via
  `TRADINGAGENTS_PROMPT_CACHE_ENABLED` (mirror the `os.getenv` pattern used by
  `llm_provider` at `default_config.py:15` — **not** the hardcoded
  `checkpoint_enabled` at `:30`, which has no env override).
- **Default OFF** until §8.6 passes; flipping to ON is a one-line follow-up PR
  justified by recorded eval evidence. This is the gate.
- Read once where the config dict is assembled; threaded to both call sites (below).
- Gates **both** the §4 restructuring and the §5 `cache_control` together
  (behaviorally coupled). The §6c sampling-param bug fix is **not** gated.

### (2) Optional per-run UI toggle — DEFERRED out of scope (§9, §11.2)

> **Confirmed deferred.** Not built in this scope — the global ops flag (1) is the
> safety mechanism. The schema/frontend table below is **reference for future product
> work**, retained so that effort doesn't have to re-derive the plumbing. Skip on a
> first read of the implementation scope.

If built, it surfaces in the LLM/Engine section of three forms, default following
the global flag. **Schema — corrected models (iteration-1 named the wrong one):**

| Form | Submits to | Add field to |
|---|---|---|
| New Analysis | `AnalysisRequest` (`schemas/__init__.py:110`) | `prompt_cache_enabled: Optional[bool] = None` (✓ iteration-1 correct) |
| Market Scan | **`ScanRequest`** (`:475`) | same — **iteration-1 wrongly said `AutoTradeConfig`** |
| Scheduled Market Scan | `CreateScheduledScanRequest.scan_config: Dict` (`:898`, freeform) | sibling key in `scan_config` (frontend already places `checkpoint_enabled` there, `ScheduledScansPage.tsx:1022`) |

> ⚠️ **Do NOT add it to `AutoTradeConfig` (`:425`)** — it has
> `model_config = ConfigDict(extra="forbid")` and would **reject** the field, and
> it's the wrong layer (per-account trade config, not LLM settings). This was a
> concrete error in iteration 1.

`checkpoint_enabled` is the faithful end-to-end template (verified wired in all 3
forms): ConfigForm RHF schema + payload `:434`; ScannerPage state→payload `:503`;
ScheduledScansPage state→payload `:1022`. (Iteration-1's cited payload lines
426/494/1009 pointed at `deep_think_llm`, not the boolean — correct rows are
**434 / 503 / 1022**.) TS interfaces in `client.ts:194` (`StartAnalysisRequest`)
and the scan request type (`:290`) take an extra boolean with no runtime allowlist.

### Backend plumbing — every link (verified; iteration-1 under-specified)

- **Trading-graph read site:** `analysis_service._build_config` (`:319`) — single
  chokepoint copying request→config, used by New Analysis **and** Market Scan.
- **Scan→analysis hop:** `scanner_service._run_single` re-assembles the per-ticker
  request field-by-field (`~:887-911`, mirror the `checkpoint_enabled` relay at
  `:903`) — **an unlisted field is dropped here**, so the flag must be added.
- **Config→client→`cache_control`:** the graph is built fresh per run
  (`analysis_service.py:596` `TradingAgentsGraph(config=…)`), so a per-run flag is
  feasible — but the value currently stops at `self.config`. `AnthropicClient.get_llm`
  only forwards `_PASSTHROUGH_KWARGS` (`anthropic_client.py:48`); **new plumbing is
  required** from config → `NormalizedChatAnthropic._cache_enabled` (§5).
- **AI Manager trio (separate path, fully unplumbed today):**
  `create_llm_callable_with_cleanup` (`ai_manager_llm_provider.py:199`) accepts only
  `provider/api_key/model/backend_url` — add a `cache_enabled` param;
  `_create_llm_from_scan_configs` (`ai_account_manager_service.py:798`) passes it;
  `_extract_llm_identity` (`:774`) must include it in the identity hash so a toggle
  change rebuilds the callable. The httpx Anthropic payload (`:281-287`) reads it.

**OFF path = byte-identical to today** (original prompt assembly, no `cache_control`),
verified by test §8.8.

> **Scope honesty (M1):** the **UI toggle plumbing is plausibly larger than the
> caching change itself** — 3 React forms, schema on 2–3 models, TS types, 2 backend
> read sites, and the AI Manager trio. The *safety* goal needs only control (1). The
> UI toggle is optional product polish; size it as its own feature, don't smuggle it
> in as "the kill-switch."

---

## 8. Testing Strategy

1. **Content-preservation** (§4) — old-content ⊆ new-content per site (necessary,
   not sufficient — see #6). For **mid-volatile** sites where text legitimately
   moves, compare the *union of system + first-human-turn* content, not the system
   block alone.
2. **Prefix-stability (per site SHAPE)** — for **tail-volatile** sites, assemble the
   stable system block for two (date, symbol) pairs → assert byte-identical. For
   **mid-volatile** sites that don't hoist, the system block is **not** byte-stable
   (it embeds volatile bytes) — assert instead that those sites are **flagged
   non-caching** and skipped, not silently expected to cache. Proves reusability of
   the prefix where one exists; does not by itself prove engagement (see #7).
3. **`cache_control` presence — REAL binding, not a mock.** Assert the
   `NormalizedChatAnthropic.invoke` transform produces a serialized request whose
   **system message** carries `cache_control` — exercised through the **actual
   installed `langchain_anthropic` payload builder** (`_get_request_payload` /
   transport-capture), **not** a hand-rolled mock. This is what catches a future
   library upgrade silently moving/dropping the breakpoint (M3). Non-Anthropic
   clients emit **no** `cache_control`.
4. **Sampling-param omission** — Opus 4.7/4.8 payload carries no `temperature`
   (and `max_tokens`/`max_completion_tokens` handling is correct); older
   models/providers keep their current params. Covers all 4 httpx call sites.
5. **Metric-normalizer** — each provider's usage maps to the unified record; covers
   Anthropic **and** OpenAI/Google paths. **Distinguish `None` (field absent →
   provider didn't report) from `0` (reported zero)** so a missing
   `prompt_tokens_details` on xAI/GLM/Qwen doesn't false-alarm as invalidation (m4).
6. **Behavioral-parity eval (pre-rollout GATE, §4) — concrete protocol:**
   - **Noise floor first:** run the *old* prompt against itself K≈5 times per fixture;
     record intrinsic decision-label disagreement rate + score variance (these are
     stochastic LLM calls — `temperature=0` does **not** make Opus 4.7/4.8
     deterministic, and those models reject the param anyway).
   - **Compare structured decisions, not text:** the BUY/HOLD/SELL label and the
     selected-indicator set (text moves legitimately; never diff raw text).
   - **Pre-registered pass rule:** over **N=30–50 fixtures** spanning bull/bear/chop,
     new-vs-old label agreement ≥ (1 − noise_floor), **and** McNemar's test p>0.05
     (no *systematic/directional* drift, not just net agreement). Score tolerance =
     f(measured variance), not an arbitrary epsilon.
   - **Execution:** a **spend-capped offline job** with recorded transcripts, run with
     real keys against the actual configured model(s). **Not in CI** (non-deterministic,
     costs money). State the budget; archive the transcript as the gate's evidence.
   - This eval **must run and pass before the global flag (§7.5) defaults ON.**
7. **End-to-end cache engagement** — split into two: (a) **CI**: assert the outgoing
   wire payload *structure* would produce a hit (mock transport) — structural only;
   (b) **once, offline**: against recorded live `usage`, confirm `cache_read > 0` on a
   repeat call. Do **not** claim CI proves `cache_read > 0` (it can't — that needs a
   live second call).
8. **OFF-path identity** — with the global flag OFF, prompts/payloads are
   byte-identical to today (no `cache_control`, original prompt structure) — proving
   the design is dark until deliberately enabled.

TDD: tests written before implementation per phase. The §5 transform reference to a
wire-payload assertion is **§8.3** (iteration-1 mis-cited "§8.6").

---

## 9. Out of Scope (YAGNI)

- **The 3-form user-facing UI toggle** (New Analysis / Market Scan / Scheduled
  Market Scan) — **confirmed deferred (§11.2)**. Safety is met by the global ops
  flag; the UI toggle is optional future product work. The schema/frontend/plumbing
  table in §7.5(2) is **reference for that future effort**, not this implementation.
- DB persistence / UI surfacing of cache savings (future "full metrics + UI").
- Gemini explicit `CachedContent` objects (implicit caching covers the win).
- **`cache_control` injection for OpenRouter / Qwen / GLM / xAI / DeepSeek.** These
  route through the OpenAI-compatible branch in this app (§2 routing note), so we
  cannot attach Anthropic-style `cache_control` to them. They rely on their
  providers' **automatic** caching, which the §4 hygiene refactor unlocks. (If a
  future need arises, OpenRouter and DashScope *do* accept explicit cache breakpoints
  at their API level — but wiring that through the OpenAI-compat client is a separate
  effort, not this one.)
- 1-hour TTL **for the scanner/trading-graph path** (5-min is strictly better
  there). Note: the AI Manager path may need 1-hour depending on cycle cadence
  (§6a caveat 2) — decided in Phase 1, not pre-judged here.
- Prompt wording/cleanup beyond reordering (content-preservation constraint).

### Schema-persistence note (not "no migration" — that claim covered only logging)

The §7 "no DB schema / no migration" statement is about **logging**. The optional UI
toggle (§7.5) *does* touch persistence: `AutoTradeConfig`/scan config serializes into
the `scheduled_scans.config` JSON column (`async_persistence.py:1152`,
`json.loads(d["config"])`). Two consequences to handle in P8:
- **Existing scheduled scans** have no `prompt_cache_enabled` key → resolve to the
  global default. With the **default OFF** (C1), they correctly stay on the old
  behavior post-deploy — they do **not** silently adopt the new path. (This is
  another reason default-OFF is the safe choice.)
- **Rollback:** an orphaned `prompt_cache_enabled` key in persisted JSON is harmless
  **only if** the reverted model ignores unknown keys. The freeform `scan_config:
  Dict` does; **do not** route the field through a model with `extra="forbid"`.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Role move (system→user) shifts trading decisions (real money) | **Default OFF** until behavioral-parity eval (§8.6) passes; eval compares structured decisions w/ noise-floor + McNemar, not text; ops flag = rollout control |
| Silent cache invalidation | Prefix-stability test (§8.2, per-shape) + real-binding presence test (§8.3) + offline engagement check (§8.7b) + all-provider cache-metric logging (§7) |
| Anthropic injection delivers ~0 because prefixes < min tokens | **P1 go/no-go** token-count gate (§4, §6a); default-drop the injection per-site/path if sub-threshold; hygiene still helps automatic-caching providers |
| AI Manager path pays ≤0 (sub-1024 prefix AND/OR cadence > TTL) | P1 must show **both** conditions; 1-hr TTL only if reads/write ≥ 2 breakeven holds (§6a) — else drop caching on that path |
| **Future** langchain-anthropic upgrade silently moves/drops the breakpoint | Pin a **tested range** (`>=1.4,<2`), not just a floor (§2); **real-binding** payload test (§8.3) fails CI if `cache_control` stops reaching the system block — mock tests would NOT catch this |
| **Third-party** auto-cache threshold drift (OpenAI/Gemini raise min prefix) | Unpinnable; **cache-metric logging (§7) is the sole detector** — add an alert on sustained `cache_read==0` rate rather than manual grep; distinguish absent-field from zero (§8.5) |
| `cache_control` leaks to a non-Anthropic provider | Injected only inside `NormalizedChatAnthropic.invoke`; real-binding presence test (§8.3) asserts non-Anthropic clients emit none |
| Sampling-param fix changes behavior on models that accepted 0.2 | Omit only where the provider/model rejects it; existing models keep current params; separate phase **P2**, ordered before injection |
| Regression once enabled | Global ops flag (§7.5, default OFF) → instant disable without redeploy; optional per-run UI toggle for finer control |
| Schema field orphaned on rollback | Field lives only in freeform `scan_config`/non-`forbid` models (§9 note) |

---

## 11. Decisions — all confirmed

2. **Behavior guarantee (§4):** preserve **content** exactly + **behavioral-parity
   eval gate** (§8.6), not a byte-identical decision guarantee.
3. **Per-path TTL (§6a):** scanner/graph = 5-min; AI Manager TTL decided in P1 on the
   breakeven inequality.
4. **`cache_control` scope:** native Anthropic (+ AI Manager Anthropic branch) only;
   others get prefix-hygiene → automatic caching.

**Iteration-2 reversals — now CONFIRMED by user:**

1. **Default OFF (was default-on).** `DEFAULT_CONFIG["prompt_cache_enabled"] = False`
   until the behavioral-parity eval (§8.6/P6) records a pass. Flipping ON is a
   separate one-line PR backed by the recorded eval evidence. The eval is a **real
   rollout gate**, not decoration.
2. **Ops flag now; UI toggle deferred (was: 3-form UI toggle in scope).** Ship the
   **global ops flag** (`TRADINGAGENTS_PROMPT_CACHE_ENABLED`, no UI) as the safety
   mechanism. The **3-form user-facing toggle is OUT of this scope** (§9) — optional
   future product work. This removes P8 and all frontend/schema/TS plumbing from the
   critical path; §7.5(2)'s schema/frontend table is **reference for that future
   work**, not this implementation.

