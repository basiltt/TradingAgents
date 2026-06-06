# Prompt Caching — Design Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorming complete, pending spec review)
**Author:** Engineering (via brainstorming workflow)

---

## 1. Problem & Goal

The TradingAgents app makes a high volume of LLM calls against **9 providers**
(openai, anthropic, azure, deepseek, xai, google, openrouter, qwen, glm) through
two distinct transports:

1. **Trading graph** (`tradingagents/`) — LangChain client wrappers, ~24 agent
   call sites, of which only **~9–12 have a cacheable leading system message**
   (Patterns A/B; the rest are bare-f-string prompts — see §4 taxonomy).
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

> **Routing reality (verified against code).** Our §5 transform fires **only for
> `anthropic/`-prefixed models** in the production litellm path. `provider ==
> openrouter / qwen / glm / xai / deepseek` get a non-Anthropic litellm prefix
> (`openrouter/`, `openai/`, …) — so even an OpenRouter→Claude model **does not**
> receive our `cache_control` injection (it goes out as `openrouter/…`, not
> `anthropic/…`). In the AI Manager httpx path these same providers use the
> `call_openai` branch. They rely on whatever **automatic** caching their endpoint
> applies. The earlier draft's "OpenRouter→Claude requires `cache_control`" is true of
> the OpenRouter API in the abstract but **not reachable through this codebase's
> routing** — explicitly out of scope (§9), not a silent gap.

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
| 7 | Architecture | **Neutral split** (agents) + **system-block transform in `NormalizedChatLiteLLM.invoke`** — the *production* path (NOT `NormalizedChatAnthropic`, which is test-only; NOT the native kwarg; NOT the sentinel — §5) |
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
| **`litellm`** | — | **1.83.7** | **The production cache path (§5).** Forwards `cache_control` to Anthropic (42 files, `anthropic_cache_control_hook.py`). |
| **`langchain-community`** | — | **0.4.1** | Hosts `ChatLiteLLM`; its `_convert_message_to_dict` **preserves** block-form `cache_control` (verified). |
| `langchain-anthropic` | 0.3.15 | 1.4.2 | Only used under `use_litellm=False` (tests). **Not** the production path. |
| `langchain-core` | — | 1.3.2 | Templating behavior (killed the iter-1 sentinel). |
| `langchain-openai` | — | 1.2.x | Hosts `NormalizedChatOpenAI`; Responses-API cache-token normalization (§7). |
| `anthropic` | — | 0.97.0 | Underlying SDK. |

> ⚠️ **Lockfile drift + future-upgrade risk.** The production caching path couples to
> **litellm 1.83.7 + langchain-community 0.4.1** (block-form `cache_control` survives
> the converter and reaches Anthropic). P0 must reconcile `uv.lock` and pin **tested
> ranges** (floor **and** known-good ceiling) for *these two* — a future major bump
> could change litellm's Anthropic transform or community's message converter and
> silently drop the breakpoint. The **real-binding test (§8.3)** runs the actual
> converter (no mock) so such an upgrade fails CI. (`langchain-anthropic`'s lock drift
> to 1.4.2 still matters only for the test-only legacy client.) **P0: reconcile lock +
> pin ranges for litellm and langchain-community.**

---

## 2.5 Implementation Phases (explicit DAG — prerequisites, not just numbers)

> Iteration-2 fix (C3): phases were scattered as prose and didn't form a valid
> dependency graph (e.g. the temp fix that *unblocks* Anthropic testing came
> *after* it; the eval that *gates* rollout came after the toggle). Corrected order:

```
P0  Deps        reconcile uv.lock, pin langchain-anthropic range          (no deps)
P1  Recon       classify all ~24 sites into Pattern A/B/C/D (§4); token-   (P0)
    [GO/NO-GO]   count every Pattern A/B stable prefix vs 1024/4096; measure
                 AI Manager cadence + prefix. → decides which (few) sites/
                 paths get cache_control. May conclude "Sonnet-only, handful
                 of sites" or "not worth the Anthropic injection at all."
P2  Param fix   conditional temperature/max_tokens in the 4 httpx sites    (P0)
                 (§6c) + litellm effort→thinking deprecated-API fix
                 (litellm_client.py:184-189). UNBLOCKS Anthropic testing on
                 Opus 4.7/4.8 — both paths 400 on those models otherwise.
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

**Core principle: reorder, don't rewrite.** For sites that *have* a stable system
prefix (Pattern A/B, §4), volatile content moves out of the system message into the
first human turn, leaving the system prefix byte-identical across all coins/dates.
Same words, different position. (Pattern C/D sites have no system message and are not
cache candidates.)

```
┌─ Agents (tradingagents/agents/...) ──────────────────────┐
│  Pattern A/B sites: STABLE system msg + VOLATILE human    │
│  turn via shared helper. Pattern C/D: untouched (no sys). │
└───────────────────────────┬───────────────────────────────┘
                            │ rendered prompt
                            ▼
┌─ NormalizedChatLiteLLM.invoke (PRODUCTION path) ─────────┐
│  if cache_enabled AND model startswith "anthropic/":      │
│    rewrite first system msg → block w/ cache_control       │
│  else (openai/gemini/…): no-op → automatic prefix caching │
│  (litellm forwards cache_control to Anthropic — verified) │
└───────────────────────────────────────────────────────────┘

┌─ AI Manager (ai_manager_llm_provider.py) ────────────────┐
│  Raw httpx. Anthropic branch: system as cache_control     │
│  block (if P1 clears prefix+cadence). OpenAI-compat:      │
│  already prefix-clean. + P2 sampling-param/effort fixes.  │
└───────────────────────────────────────────────────────────┘
```

---

## 4. Component: Prefix Hygiene Refactor (Trading Graph)

### Transformation

Before (`market_analyst.py` + the 8 other Pattern A analysts — §4):
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
- Keeps the **Pattern A/B sites** uniform (one-line change each, not hand-rolled).
  Pattern C/D sites have no system message and are not touched by this helper (§4).

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

### Sites in scope — REAL taxonomy (iteration-4: verified all ~24 call sites)

> **Iteration-4 correction.** Iters 1–3 assumed "~20 sites, each a single leading
> `SystemMessage` with a volatile tail to hoist." **Verified false.** Only ~9 of ~24
> sites have a clean leading `SystemMessage`; the majority build prompts as **bare
> f-strings with NO system message**, often with stable and volatile content
> **interleaved in one string**. The transform attaches `cache_control` to the *first
> `SystemMessage`* — sites without one cache **nothing**. Four shapes:

| Pattern | Sites | Cacheable? |
|---|---|---|
| **A — clean leading `SystemMessage`** via `ChatPromptTemplate.from_messages([("system",…), MessagesPlaceholder])`, invoked `prompt \| llm.bind_tools()` | 4 stock analysts + 5 crypto analysts (`crypto_analysts.py:112/177/224/277/326`) = **9** | ✅ after §4 hoist |
| **B — `list[dict]` with leading `{"role":"system"}`** | trader (`trader.py`), risk_manager, compliance_officer = **3** | ✅ if transform handles dict-shaped system + content hoisted |
| **C — bare f-string, NO system message** (becomes one `HumanMessage`; stable+volatile interleaved) | portfolio_manager, research_manager, crypto research-mgr/PM/confluence (`crypto_analysts.py:564/894/382`), stock bull/bear, crypto bull/bear, 3 stock debators, 2 crypto risk debators = **~14** | ❌ not without a real rewrite |
| **D — `list[dict]` USER-only, no system** (crypto_trader `crypto_analysts.py:692`) | **1** | ❌ |

**Consequence for scope:** the clean win is **Pattern A (9 sites)** + Pattern B (3
sites, with dict handling). **Pattern C/D (~15 sites) are effectively out of scope for
`cache_control`** — converting an interleaved f-string into a cacheable
stable-system + volatile-user split is a **content-restructuring** of each prompt
(not a mechanical hoist), which risks exactly the behavior drift §4 guards against,
for prompts (debate/research) that are also frequently **below the cache minimum**
anyway. **P1 must classify every site into A/B/C/D and token-count it**; the plan
should target A (and B if cheap), and explicitly **defer C/D** rather than pretend
they cache. The reflection path (`reflection.py`) is Pattern A but ~150 tok →
sub-minimum, won't cache.

> This sharply narrows the realistic Anthropic-`cache_control` win to ~9–12 sites,
> several of which may still miss Opus's 4096 floor (§ minimum-prefix). The
> **provider-agnostic hygiene benefit also only applies where there's a stable
> prefix to expose** — so Pattern C/D sites don't benefit from automatic caching
> either, until/unless someone restructures those prompts. Be honest about this in
> the plan; don't carry "~20 sites" as if all cache.

### Input-shape normalization (the transform must handle 4 shapes)

`NormalizedChatLiteLLM.invoke` receives different input types per site:
`ChatPromptValue` (Pattern A), `list[BaseMessage]`, `list[dict]` (Pattern B/D),
`list[tuple]` (reflection), and bare `str` (Pattern C). The transform's
message-normalization must handle all of these and **locate a leading system message
in both `SystemMessage` and `{"role":"system"}` dict forms**, else Pattern B silently
misses. Where no system message exists (C/D), the transform is a **no-op** (correct —
nothing to cache).

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

### Within Pattern A/B: volatile placement

- **Tail-volatile (analysts, Pattern A):** volatile token at the end of the system
  text → clean hoist to the human turn. The whole system message becomes stable → caches.
- **Mid-volatile (Pattern B — trader/risk_manager/compliance):** `{instrument_context}`
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
4096**. Of the ~9–12 Pattern A/B candidate sites (§4), the analysts are the largest;
researchers/debaters/managers are Pattern C (no system message, not candidates) and
also tend to be short.

> **ROI honesty (P1 deliverable):** before implementing the Anthropic injection,
> **classify every site A/B/C/D and token-count each Pattern A/B stable prefix** (via
> `client.messages.count_tokens` or `tiktoken` estimate); record how many clear
> 1024 (Sonnet) and 4096 (Opus). Combined with the §4 finding that only ~9–12 sites
> are even candidates, the realistic outcome may be **a handful of sites caching on
> Sonnet and near-zero on Opus.** This number decides whether the Anthropic-injection
> work is worth doing at all — surface it, don't bury it. The provider-agnostic
> hygiene benefit is likewise limited to sites that *have* a stable prefix to expose.

---

## 5. Component: Anthropic `cache_control` Injection (LangChain path)

> **CRITICAL CORRECTION (iteration 3 — the target class was WRONG in iters 1 & 2).**
> Iters 1–2 put the cache transform in `NormalizedChatAnthropic`. **Verified against
> the code: that class is never instantiated in production.** `create_llm_client`
> defaults to **`use_litellm=True`** (`factory.py:15`), and `trading_graph.py:179/186/421`
> calls it **without** `use_litellm=False`. So every trading-graph Anthropic call runs
> through **`NormalizedChatLiteLLM`** (`litellm_client.py:83`, wrapping
> `langchain_community.ChatLiteLLM`). `NormalizedChatAnthropic` only instantiates in
> tests (`use_litellm=False`). A transform in `NormalizedChatAnthropic.invoke` would
> cache **nothing** for any agent.
>
> **Two earlier mechanism errors also resolved here:** the sentinel (iter 1, broke on
> templating) and the native last-block kwarg (iter 2, marks the volatile tail). The
> mechanism below is **empirically verified** against the installed libraries.

**Correct mechanism: transform the *system* message to block-form with `cache_control`
inside `NormalizedChatLiteLLM.invoke` (the production path) — AFTER langchain renders
the template.** Verified end-to-end against installed **litellm 1.83.7** +
**langchain-community 0.4.1**:
- langchain-community's `_convert_message_to_dict` **preserves** block-form content
  with `cache_control` on a `SystemMessage` (tested: emits
  `{"role":"system","content":[{"type":"text","text":…,"cache_control":{"type":"ephemeral"}}]}`).
- litellm 1.83.7 supports `cache_control` (42 files, incl. a dedicated
  `anthropic_cache_control_hook.py`) and forwards it to Anthropic's `/v1/messages`.

The transform (inside `NormalizedChatLiteLLM.invoke`, gated by `_cache_enabled` **and**
provider == anthropic — litellm carries the provider in the model prefix
`anthropic/…`, so the override can check `self.model`):

1. Normalize input to messages (reuse the existing `_input_to_messages` pattern from
   `openai_client.py:42`; handle `list[BaseMessage]` **and** `ChatPromptValue`).
2. Find the **first `SystemMessage`** (now stable-only, per §4).
3. Rewrite its string `.content` to a single text block with `cache_control:
   {"type":"ephemeral"}`.
4. Delegate to `super().invoke`.

```python
# In NormalizedChatLiteLLM.invoke (litellm_client.py), conceptually:
def invoke(self, input, config=None, **kwargs):
    if self._cache_enabled and self.model.startswith("anthropic/"):
        msgs = list(_input_to_messages(input))      # ChatPromptValue -> messages too
        for i, m in enumerate(msgs):
            if isinstance(m, SystemMessage) and isinstance(m.content, str):
                msgs[i] = m.model_copy(update={"content": [
                    {"type": "text", "text": m.content,
                     "cache_control": {"type": "ephemeral"}}]})
                break                                 # first system message only
        input = msgs
    return normalize_content(llm_rate_limited_invoke(super().invoke, input, config, **kwargs))
```

> **Confirmed empirically** (not "to be confirmed in a later phase"): the block reaches
> the Anthropic `system` param with `cache_control` intact through the
> langchain-community→litellm chain. The §8.3 test asserts this against the **real**
> converter, not a mock.

**Scope note:** because production is litellm-only, the legacy `NormalizedChatAnthropic`
(used solely under `use_litellm=False`, i.e. tests / explicit opt-out) is **out of
scope** — caching it would only help a path no production user takes. If a future
change flips the default to `use_litellm=False`, this section must move to
`NormalizedChatAnthropic` (track as a known coupling).

**TTL:** 5-minute ephemeral (§2 rationale). **Beta header:** none — `cache_control`
is GA on current Claude models. **Failure safety:** on a sub-threshold prompt the
block is inert (`cache_creation = 0`); on any unexpected input shape or non-Anthropic
model the override falls through to today's behavior. **Mid-volatile sites (§4):** the
breakpoint covers the whole system block, so a system message that still embeds
volatile bytes does **not** cache — see §4.

> ✅ **Iteration-4 runtime confirmation (executed, not reasoned).** Ran the realistic
> production payload through litellm 1.83.7's `AnthropicConfig.transform_request`
> with **`drop_params=True`** and **tools bound** (the bind_tools path all analysts
> use). Result: the final Anthropic request carried **exactly one `cache_control`
> breakpoint, on the top-level `system` param**, with `tools` coexisting correctly.
> So `drop_params` does **not** strip `cache_control`, and tools+system+cache compose
> cleanly. The mechanism is verified end-to-end for Pattern A/B sites.
>
> **Input-shape handling (§4):** the transform must normalize `ChatPromptValue` /
> `list[BaseMessage]` / `list[dict]` / `list[tuple]` / `str`, and detect a leading
> system message in **both** `SystemMessage` and `{"role":"system"}` dict forms
> (Pattern B uses dicts). No system message (Pattern C/D) → no-op.

**Other providers via litellm** (openai, gemini, deepseek, xai, qwen, glm, openrouter)
get **no** `cache_control` injection — they rely on automatic prefix caching, which
the §4 hygiene refactor unlocks.

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

> **Related latent bug found iter-3 (litellm path) — same P2 family, flag don't
> silently inherit.** `litellm_client.py:184-189` maps `effort` →
> `thinking: {"type": "enabled", "budget_tokens": N}` — the **deprecated** extended-
> thinking API that **400s on Opus 4.7/4.8** (those models require adaptive thinking;
> `budget_tokens` is removed). Since litellm is the **production** trading-graph path
> (§5), any Anthropic-Opus-4.7/4.8 run with `anthropic_effort` set would 400 here too,
> independently of caching. **Decision needed (§11):** fold this into P2 (it's the
> same "current-Opus rejects the param" class and would otherwise block caching tests
> on those models), or file separately. Recommend **fold into P2** — caching is
> untestable on current Opus while either param 400s. `litellm.drop_params = True`
> (`litellm_client.py:28`) drops *unsupported* params but does **not** rewrite a
> deprecated-but-recognized `thinking` shape, so it won't save us here.

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

**Where logging lives — the single litellm chokepoint makes this simple:**

Since production routes **all** providers through `NormalizedChatLiteLLM` (§5), and
every wrapper funnels `super().invoke` through **`llm_rate_limited_invoke`**
(`base_client.py:59`), that one helper is the natural insertion point — it covers
Anthropic, OpenAI, Gemini, DeepSeek, etc. in a single place.

- **Read langchain's normalized `usage_metadata`, not raw provider JSON.** Research
  confirmed langchain normalizes all providers to the **same path**:
  `result.usage_metadata['input_token_details']['cache_read']` (and `['cache_creation']`
  where the provider reports it). This holds for **Anthropic**, **OpenAI Responses
  API** (langchain's `_create_usage_metadata_responses` maps
  `input_tokens_details.cached_tokens` → `cache_read`), and **Gemini** (maps
  `cached_content_token_count` → `cache_read`). So a single read works across the board.
  > ⚠️ **Do NOT read raw `prompt_tokens_details.cached_tokens`** — that path is **Chat
  > Completions only**. The app's native OpenAI uses the **Responses API**
  > (`use_responses_api=True`), whose raw field is `input_tokens_details.cached_tokens`.
  > Reading the raw object would report 0 for OpenAI. Reading `usage_metadata` avoids
  > this entirely.
  > ⚠️ **Gemini caveat:** `cache_read` is best-effort — known langchain_google_genai
  > issues leave `cached_content_token_count` unpopulated in a ~9K–17K token "dead
  > zone." Treat Gemini `cache_read == 0` as *inconclusive*, not proof of invalidation.
- **AI Manager path** (raw httpx, not litellm): read the `resp.json()` `usage` object
  (currently **not read at all**). Anthropic: `usage.cache_read_input_tokens` /
  `cache_creation_input_tokens`. OpenAI-compat (chat completions): `usage.prompt_tokens_details.cached_tokens`.

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
  feasible — but the value currently stops at `self.config`. The production client is
  `LiteLLMClient.get_llm` (`litellm_client.py:135`), which forwards only a fixed kwarg
  allowlist (`:174-177`); **new plumbing is required** from config →
  `NormalizedChatLiteLLM._cache_enabled` (§5). (The legacy `AnthropicClient` path is
  test-only and out of scope.)
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
   `NormalizedChatLiteLLM.invoke` transform produces a request whose **system
   message** carries `cache_control` — exercised through the **actual installed
   langchain-community→litellm chain** (`_convert_message_to_dict` →
   litellm Anthropic transform), **not** a hand-rolled mock. This is what catches a
   future library upgrade silently moving/dropping the breakpoint (M3). Non-Anthropic
   models (`openai/…`, `gemini/…`, etc.) emit **no** `cache_control`.
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
9. **Pattern coverage (§4) + no-op safety** — assert the transform attaches
   `cache_control` for Pattern A (`ChatPromptValue`) and Pattern B (`list[dict]` with
   leading `{"role":"system"}`), and is a **clean no-op** for Pattern C/D (bare `str`
   / user-only — no system message). Guards against the iter-4 finding: a Pattern-B
   dict-form system message must be detected, and a Pattern-C string must not crash or
   wrongly wrap a human turn. Run the matrix across the real input shapes
   (`ChatPromptValue` / `list[BaseMessage]` / `list[dict]` / `list[tuple]` / `str`).

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
| Anthropic injection delivers ~0 (few cacheable sites AND/OR prefixes < min tokens) | **P1 go/no-go**: only ~9–12 of ~24 sites have a cacheable system message (§4 taxonomy), and several miss Opus's 4096 floor. Token-count + classify per-site; default-drop sub-threshold/Pattern-C-D sites. Realistic win may be a handful of Sonnet sites — surfaced, not buried. |
| Pattern C/D sites (~15) silently assumed to cache | §4 taxonomy marks them **not candidates** (no system message / interleaved f-string); helper skips them; ⊆ test only runs on Pattern A/B. They benefit from neither injected nor automatic caching until someone restructures those prompts (separate future work). |
| AI Manager path pays ≤0 (sub-1024 prefix AND/OR cadence > TTL) | P1 must show **both** conditions; 1-hr TTL only if reads/write ≥ 2 breakeven holds (§6a) — else drop caching on that path |
| **Future** litellm / langchain-community upgrade silently moves/drops the breakpoint | Pin **tested ranges** for `litellm` (1.83.7) and `langchain-community` (0.4.1), not just floors (§2); **real-binding** payload test (§8.3) runs the actual converter chain → fails CI if `cache_control` stops reaching Anthropic's system param — mock tests would NOT catch this |
| **Future** flip of `use_litellm` default to False | §5 transform would silently stop firing (legacy `NormalizedChatAnthropic` path). Tracked as a known coupling in §5; the §8.3 test (if run only against litellm) would not cover the legacy path |
| **Third-party** auto-cache threshold drift (OpenAI/Gemini raise min prefix) | Unpinnable; **cache-metric logging (§7) is the sole detector** — add an alert on sustained `cache_read==0` rate rather than manual grep; distinguish absent-field from zero (§8.5) |
| `cache_control` leaks to a non-Anthropic provider | Injected only inside `NormalizedChatLiteLLM.invoke`, gated on `model.startswith("anthropic/")`; real-binding presence test (§8.3) asserts non-Anthropic models emit none |
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

**Iteration-3 — CONFIRMED:**

1. **litellm `effort→thinking` deprecated-API bug folded into P2 (§6c note).** Iter-3
   found `litellm_client.py:184-189` emits the deprecated `thinking:{type:"enabled",
   budget_tokens}` that **400s on Opus 4.7/4.8** — the **production** trading-graph
   path. **Confirmed: fix it in P2** alongside the AI Manager sampling-param fix (same
   "current Opus rejects the param" class; caching is untestable on current Opus while
   either 400s). P2 now covers both the httpx sampling params **and** the litellm
   `effort`→thinking mapping (migrate to adaptive thinking / drop `budget_tokens` for
   models that reject it).

