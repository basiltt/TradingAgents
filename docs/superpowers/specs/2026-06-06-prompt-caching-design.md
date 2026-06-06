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
mechanisms, covering both call sites, **preserving the model's content exactly and
verifying behavioral parity before rollout** (see §4 — a strict byte-identical
*decision* guarantee is not achievable across the system→user role move, so we gate
on an eval instead), with cache-metric logging to verify hits and catch silent
invalidation.

### Two mechanisms (do not conflate)

| Mechanism | Scope | Requires code |
|---|---|---|
| **Prefix hygiene** (stable-first, volatile-last) | All 9 providers' automatic caching | Prompt restructuring (provider-agnostic) |
| **`cache_control` injection** | **Native Anthropic provider only** (see routing note) | Anthropic-specific, via langchain-anthropic native kwarg |

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
| 5 | TTL | **5-minute** for scanner/graph; AI Manager TTL **TBD by Phase 1 cadence check** (§6a) |
| 6 | Adjacent bug | **Fix** hardcoded `temperature:0.2` **and `max_tokens:1024`** (400s/param-mismatch on Opus 4.7/4.8); separate revertable commit |
| 7 | Architecture | **Neutral split** (agents) + **native `cache_control` kwarg** in the Anthropic client (sentinel approach rejected — §5) |
| 8 | Kill-switch | **Open decision (§11.1)** — recommend `PROMPT_CACHE_ENABLED` (default on); was "no flag" |

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

> ⚠️ **Lockfile drift is a real risk.** The implementation must pin/verify
> `langchain-anthropic >= 1.4` (the native `cache_control` kwarg and the
> `usage_metadata['input_token_details']['cache_read']` path both depend on it).
> A `uv sync` that honors the stale 0.3.15 pin would break the design. **Phase 0
> task: reconcile `uv.lock` with the installed version and pin a floor.**

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
> 2. **Add a behavioral-parity gate (Phase 5, pre-rollout):** run N fixed
>    (symbol, date, market-state) fixtures through representative agents **old prompt
>    vs new prompt**, and assert the **decision/score output matches** (e.g. same
>    BUY/HOLD/SELL, same indicator selection, or score within tolerance). If parity
>    holds, ship. If it drifts, the kill-switch (below) keeps the old path until
>    resolved. This is the real safety net; the ⊆ test is necessary but not
>    sufficient.

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

**Mechanism: langchain-anthropic's native `cache_control` (verified in 1.4.2).**
No sentinel, no manual block rewriting. `langchain-anthropic >= 1.4` accepts
`cache_control={"type": "ephemeral"}` and auto-applies it to the last eligible
content block (`_apply_cache_control_to_last_eligible_block`), promoting a string
system prompt to a text block automatically.

**Where it's applied:** in `AnthropicClient.get_llm()`
(`tradingagents/llm_clients/anthropic_client.py`), bind the cache kwarg so every
invoke through `NormalizedChatAnthropic` carries it. Because the volatile content
now lives in the human turn (§4), the system block is the stable prefix and is the
correct cache breakpoint. The `NormalizedChatAnthropic.invoke` override
(confirmed to fire on every agent call — all agent nodes use sync `chain.invoke`,
zero `ainvoke`) needs no change for *injection*; it only gains metric logging (§7).

```python
# In AnthropicClient.get_llm(), conceptually:
llm = NormalizedChatAnthropic(model=..., cache_control={"type": "ephemeral"})
# langchain-anthropic applies it to the last eligible (stable system) block.
```

> The exact binding surface (constructor kwarg vs `.bind()` vs per-call) will be
> confirmed against the installed 1.4.2 API during Phase 2 and asserted by the
> wire-payload test (§8.6). The design commitment is: **use the native kwarg, not a
> hand-rolled block rewrite, and not the rejected sentinel.**

**TTL:** 5-minute ephemeral (§2 rationale). **Beta header:** none — `cache_control`
is GA on current Claude models. **Failure safety:** the kwarg is inert on
non-cacheable prompts (just `cache_creation = 0`); no behavior change.

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
> ⚠️ **Two caveats that decide whether this is worth doing:**
> 1. **Prefix size:** the system prompt is ~600–900 tokens — **likely below
>    Anthropic's 1024-token minimum**, so it may **never cache**. Phase 1 must
>    token-count it; if sub-1024, the AI Manager Anthropic-injection delivers
>    nothing and should be dropped (prefix hygiene on the user turn still helps
>    automatic-caching providers).
> 2. **Cycle cadence vs 5-min TTL:** caching only pays off if consecutive cycles
>    for an account land **within 5 minutes**. The AI Manager is event-driven with a
>    `safety_net_interval_s` fallback and an emergency fast-path; cadence is
>    variable. Phase 1 must check typical inter-cycle spacing — if cycles are
>    routinely >5 min apart, the 5-min TTL expires between them and the 1-hour TTL
>    (2× write) may be the better choice **for this path specifically** (distinct
>    from the scanner, where 5-min is correct).

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
> 400s first). It will be a **separate phase/commit** (Phase 4) so it can be
> reviewed and reverted independently.

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

## 7.5 Kill-Switch (revisits decision — was "no flag")

> **This reverses the earlier "no flag" choice and needs user sign-off.** The
> original spec deliberately had no toggle. The review surfaced that this change
> touches **~20 live trading prompts** whose role-restructuring *could* shift
> decisions (§4 caveat), and "no flag" means **any regression requires a code
> redeploy to revert**. For a money-handling path, a one-line env guard is cheap
> insurance and makes the behavioral-parity gate (§8.6) and rollback trivial.

**Proposed:** a single env var `PROMPT_CACHE_ENABLED` (default **on**), read once at
client/prompt construction:
- **ON:** new prompt structure + `cache_control` (the design).
- **OFF:** original prompt assembly, no `cache_control` — **byte-identical to
  today**, verified by test §8.8.

One flag gates **both** the prompt-hygiene restructuring and the `cache_control`
injection together (they're behaviorally coupled — the restructure is what makes
the cache breakpoint meaningful). The AI Manager `temperature`/`max_tokens` fix
(§6c) is **not** gated — it's a straight bug fix that should always apply.

> If the user prefers to keep "no flag," delete this section and accept redeploy-to-
> revert; the rest of the design stands. Flagged as an open decision in §11.

---

## 8. Testing Strategy

1. **Content-preservation** (§4) — old-content ⊆ new-content per site (necessary,
   not sufficient — see #6).
2. **Prefix-stability** — assemble the stable system block for two (date, symbol)
   pairs → assert **byte-identical**. Proves the prefix *is reusable*; does **not**
   by itself prove caching engages (see #7).
3. **`cache_control` presence** — Anthropic client binds the native cache kwarg;
   the **outgoing wire payload** carries `cache_control` on the system block.
   Non-Anthropic clients emit **no** `cache_control`.
4. **Sampling-param omission** — Opus 4.7/4.8 payload carries no `temperature`
   (and the `max_tokens`/`max_completion_tokens` handling is correct); older
   models/providers keep their current params.
5. **Metric-normalizer** — each provider's usage JSON/`usage_metadata` maps to the
   unified record; covers Anthropic **and** OpenAI/Google paths.
6. **Behavioral parity (pre-rollout gate, §4)** — N fixed fixtures through
   representative agents, old vs new prompt, assert decision/score parity. This is
   the real behavior guard, not the ⊆ test.
7. **End-to-end cache engagement** — one integration test that runs a real (mocked-
   transport) graph invoke and asserts (a) the override fires and (b) on a repeat
   call with an identical prefix the parsed usage shows `cache_read > 0` (or, against
   a recorded fixture, that the wire payload would produce a hit). Byte-stability
   (#2) proves *reusability*; this proves *engagement*.
8. **Kill-switch** — with the cache flag OFF, prompts/payloads are byte-identical to
   today (no `cache_control`, original prompt structure) — proving instant rollback.

TDD: tests written before implementation per phase.

---

## 9. Out of Scope (YAGNI)

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

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Role move (system→user) shifts trading decisions (real money) | Behavioral-parity gate (§8.6) before rollout + kill-switch (§7.5); ⊆ test alone is **not** sufficient — acknowledged in §4 |
| Silent cache invalidation | Prefix-stability test (§8.2) + end-to-end engagement test (§8.7) + all-provider cache-metric logging (§7) |
| Anthropic injection delivers ~0 because prefixes < min tokens | Phase 1 token-count gate (§4, §6a); drop Anthropic injection per-site/path if sub-threshold; automatic-caching providers still benefit from hygiene |
| AI Manager cycles spaced > 5-min TTL → no cross-cycle reuse | Phase 1 cadence check (§6a caveat 2); choose 5-min vs 1-hour TTL for that path on evidence |
| langchain-anthropic native kwarg API differs in 1.4.2 | Wire-payload test (§8.3) gates it; pin `>=1.4` and reconcile `uv.lock` drift (§2) |
| `cache_control` leaks to non-Anthropic provider | Injected only via the Anthropic client's native kwarg; presence test (§8.3) guards |
| Sampling-param fix changes behavior on models that accepted 0.2 | Omit only where the provider/model rejects it; existing models keep current params; separate revertable commit (Phase 4) |
| Regression in any of 20 live prompts | `PROMPT_CACHE_ENABLED` kill-switch (§7.5) → instant revert without redeploy |

---

## 11. Open Decisions (need user sign-off)

These surfaced during the verification/review pass and **change two earlier
choices** — confirm before planning:

1. **Kill-switch (§7.5):** earlier decision was "no flag." Recommend **adding**
   `PROMPT_CACHE_ENABLED` (default on) given 20 live trading prompts. Keep, or stay
   no-flag?
2. **"Preserve behavior exactly" (§4):** cannot be *guaranteed* across the
   system→user role move. Recommend reframing to "preserve **content**; verify
   behavior via a parity gate (§8.6) before rollout." Accept the reframe + the eval
   gate?
3. **Per-path TTL (§6a):** scanner/graph = 5-min (settled); AI Manager TTL deferred
   to a Phase 1 cadence measurement. OK to decide that empirically rather than now?
4. **Scope of `cache_control`:** confirmed it reaches **native Anthropic only** in
   this app (not OpenRouter→Claude). Accept that the broad win for the other 7
   providers is **prefix hygiene → automatic caching**, with explicit `cache_control`
   limited to native Anthropic + the AI Manager Anthropic branch?

