# Prompt Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Anthropic prompt caching (via `cache_control`) and provider-agnostic prefix-hygiene to the TradingAgents LLM call paths, gated OFF-by-default behind a flag, so cache hits cut input-token cost without changing model behavior.

**Architecture:** Two mechanisms. (1) **Prefix hygiene** — for agent prompts that have a stable leading system message, move volatile content (date/instrument) into the first human turn so the system prefix is byte-stable and cacheable. (2) **`cache_control` injection** — inside `NormalizedChatLiteLLM.invoke` (the production LLM wrapper), rewrite the first system message to block-form with `cache_control` when the model is `anthropic/*`. The AI Manager's separate raw-httpx path gets the same `cache_control` on its Anthropic branch. Everything is gated by a `prompt_cache_enabled` config flag (default OFF) plus a user-facing per-run toggle.

**Tech Stack:** Python 3.12 / FastAPI / LangChain + litellm 1.83.7 / langchain-community 0.4.1 / pytest + pytest-asyncio; React + TypeScript + Vite frontend.

**Spec:** `docs/superpowers/specs/2026-06-06-prompt-caching-design.md` (read it — this plan implements it).

---

## CRITICAL CONTEXT (read before any task)

- **The production LLM path is litellm, NOT the per-provider clients.** `create_llm_client` defaults to `use_litellm=True` (`tradingagents/llm_clients/factory.py:15`). Every trading-graph agent runs through `NormalizedChatLiteLLM` (`tradingagents/llm_clients/litellm_client.py:83`). `NormalizedChatAnthropic` only runs in tests. **All `cache_control` work for the graph goes in `NormalizedChatLiteLLM`.**
- **Only ~9–12 of ~24 agent sites are cacheable** (have a leading system message). The rest are bare f-strings with no system message — out of scope (see spec §4 taxonomy).
- **Default OFF.** `prompt_cache_enabled` defaults to `False` until the behavioral-parity eval (P6) passes. Code lands dark.
- **Mechanism is runtime-verified:** block-form `cache_control` on a system message survives langchain-community's converter and litellm's Anthropic transform (with tools + `drop_params=True`) and lands on Anthropic's top-level `system` param. Do not second-guess it; the P4 test asserts it against the real libraries.
- **Test command:** `python -m pytest tests/ -x -q` (all) or a specific file/test as shown per task.
- **Frontend type-check:** `cd frontend && npx tsc --noEmit`.

---

## File Structure

**New files:**
- `tradingagents/agents/utils/prompt_cache.py` — shared helper: `split_cacheable_prompt(...)` builds a Pattern-A prompt template with stable system + volatile human turn; `apply_cache_control_to_messages(messages)` transforms the first system message to block-form. One responsibility: prompt-cache shaping. Pure functions, no I/O.
- `tests/test_prompt_cache_helper.py` — unit tests for the helper.
- `tests/test_litellm_cache_injection.py` — tests the `NormalizedChatLiteLLM.invoke` transform + real-binding wire assertion.
- `tests/backend/test_ai_manager_cache.py` — tests the AI Manager httpx `cache_control` + sampling-param fix.
- `docs/superpowers/plans/2026-06-06-prompt-caching-progress.md` — progress tracker (created in P0).

**Modified files:**
- `tradingagents/default_config.py` — add `prompt_cache_enabled` default + env override.
- `tradingagents/llm_clients/litellm_client.py` — `NormalizedChatLiteLLM`: add `_cache_enabled`, the invoke transform, and the metric log; fix `effort→thinking` for current-Opus.
- `tradingagents/llm_clients/base_client.py` — add the cache-metric normalizer/log helper.
- `tradingagents/llm_clients/factory.py` — thread `prompt_cache_enabled` into the client.
- `tradingagents/graph/trading_graph.py` — pass `prompt_cache_enabled` from config to `create_llm_client`.
- `backend/services/ai_manager_llm_provider.py` — `cache_control` on Anthropic branch; conditional sampling params; usage logging.
- `tradingagents/agents/analysts/*.py` + `tradingagents/agents/crypto_analysts.py` — Pattern-A hygiene refactor (P3), via the helper, gated.
- `backend/schemas/__init__.py` — add `prompt_cache_enabled: Optional[bool]` to `AnalysisRequest` + `ScanRequest`.
- `backend/services/analysis_service.py`, `backend/services/scanner_service.py` — read/relay the flag.
- `frontend/src/components/analysis/ConfigForm.tsx`, `scanner/ScannerPage.tsx`, `scanner/ScheduledScansPage.tsx`, `frontend/src/api/client.ts` — UI toggle (P8).

---

## Phase P0 — Dependencies & Progress Tracker

### Task 0.1: Reconcile lockfile and pin cache-critical dependency ranges

**Files:**
- Modify: `pyproject.toml` (dependency pins)
- Modify: `uv.lock` (via `uv lock`)

- [ ] **Step 1: Record the installed versions**

Run:
```bash
python -c "import importlib.metadata as m; print('litellm', m.version('litellm')); print('langchain-community', m.version('langchain-community')); print('langchain-anthropic', m.version('langchain-anthropic'))"
```
Expected output (confirm; if different, use the actual installed values in Step 2):
```
litellm 1.83.7
langchain-community 0.4.1
langchain-anthropic 1.4.2
```

- [ ] **Step 2: Pin tested ranges in `pyproject.toml`**

Find the `dependencies` list in `pyproject.toml`. Ensure these three have a floor at the installed version and a major-version ceiling (edit existing entries; do not duplicate):
```toml
"litellm>=1.83.7,<2",
"langchain-community>=0.4.1,<0.5",
"langchain-anthropic>=1.4.2,<2",
```

- [ ] **Step 3: Regenerate the lock and verify it resolves**

Run:
```bash
uv lock
```
Expected: completes without error; `uv.lock` now shows `litellm` at 1.83.7 (not the stale 0.3.15-era pin).

- [ ] **Step 4: Verify the environment still imports**

Run:
```bash
python -c "from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): pin tested ranges for litellm/langchain-community (caching path)"
```

### Task 0.2: Create the progress tracker

**Files:**
- Create: `docs/superpowers/plans/2026-06-06-prompt-caching-progress.md`

- [ ] **Step 1: Create the tracker file with this exact content**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "docs(caching): add implementation progress tracker"
```

- [ ] **Step 3: Tag the pre-restructure commit (for the P6 old-vs-new eval)**

Before any P3 prompt restructuring lands, tag the current state so the P6 eval can
recover the OLD prompts:
```bash
git tag pre-cache-p3
```
Record in the tracker: "OLD-prompt recovery for P6 = `git tag pre-cache-p3`."

---

## Phase P1 — Recon & GO/NO-GO (measurement, not code)

> This phase produces a **recorded artifact** that decides which sites/paths get
> `cache_control` in P4. It is investigation + a written finding, not TDD. Do not
> skip it — P4 depends on its output.

### Task 1.1: Classify all agent call sites into Pattern A/B/C/D

**Files:**
- Modify: `docs/superpowers/plans/2026-06-06-prompt-caching-progress.md` (append a "Site classification" table)

- [ ] **Step 1: Enumerate every agent LLM call site**

Run:
```bash
python -m pytest --collect-only -q 2>/dev/null | head -1  # sanity: env works
```
Then grep the agent tree for the call sites:
```bash
grep -rn "llm.invoke\|chain.invoke\|\.bind_tools\|ChatPromptTemplate.from_messages\|with_structured_output" tradingagents/agents/ | grep -v test
```

- [ ] **Step 2: Classify each site and record it**

For each site, open the file and determine its shape (see spec §4):
- **Pattern A** — `ChatPromptTemplate.from_messages([("system", ...), MessagesPlaceholder])`, invoked `prompt | llm.bind_tools()`.
- **Pattern B** — `list[dict]` with a leading `{"role": "system", ...}`.
- **Pattern C** — bare f-string passed to `llm.invoke(prompt)` (no system message).
- **Pattern D** — `list[dict]` with no system role (user-only).

Append a table to the progress tracker:
```markdown
## Site classification (P1)
| Site (file:line) | Pattern | Candidate? | Notes |
|---|---|---|---|
| analysts/market_analyst.py:51 | A | yes | |
| ... | | | |
```
Expected: ~9 Pattern A (analysts), ~3 Pattern B (trader/risk_manager/compliance_officer), ~14 Pattern C, ~1 Pattern D. Only A/B are candidates.

- [ ] **Step 3: Commit the classification**

```bash
git add docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "docs(caching): P1 site classification (A/B/C/D)"
```

### Task 1.2: Token-count each Pattern A/B stable prefix

**Files:**
- Create: `scripts/measure_cache_prefixes.py` (throwaway measurement script — keep, it's useful)
- Modify: `docs/superpowers/plans/2026-06-06-prompt-caching-progress.md` (append token counts)

- [ ] **Step 1: Write a measurement script**

Create `scripts/measure_cache_prefixes.py`:
```python
"""Estimate token counts for each Pattern A/B stable system prefix.

Uses litellm.token_counter (already a dependency) so no extra install.
Run: python scripts/measure_cache_prefixes.py
"""
import litellm

# Paste each candidate site's STABLE system text here as {name: text}.
# Pull the literal system strings from the agent files identified in Task 1.1.
PREFIXES: dict[str, str] = {
    # "market_analyst": "<paste stable system text>",
}

THRESHOLDS = {"sonnet (1024)": 1024, "opus (4096)": 4096}

for name, text in PREFIXES.items():
    n = litellm.token_counter(model="claude-sonnet-4-6", text=text)
    clears = [label for label, t in THRESHOLDS.items() if n >= t]
    print(f"{name:30s} {n:6d} tok  clears: {', '.join(clears) or 'NONE'}")
```

- [ ] **Step 2: Fill in the stable prefixes and run**

Paste each Pattern A/B site's stable system text into `PREFIXES`, then run:
```bash
python scripts/measure_cache_prefixes.py
```
Expected: a per-site token count and which thresholds it clears.

- [ ] **Step 3: Record results + the GO/NO-GO decision**

Append to the progress tracker:
```markdown
## Token counts (P1)
| Site | tokens | clears Sonnet (1024) | clears Opus (4096) |
|---|---|---|---|
| ... | | | |

### GO/NO-GO decision
- Sites caching on Sonnet: <list>
- Sites caching on Opus: <list>
- DECISION: implement P4 cache_control for [sites]; SKIP [sites] (sub-threshold).
```

- [ ] **Step 4: Commit**

```bash
git add scripts/measure_cache_prefixes.py docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "docs(caching): P1 token counts + GO/NO-GO decision"
```

### Task 1.3: Measure AI Manager cycle cadence (decides its TTL / whether to cache)

**Files:**
- Modify: `docs/superpowers/plans/2026-06-06-prompt-caching-progress.md`

- [ ] **Step 1: Find typical inter-cycle spacing**

Inspect the AI Manager evaluation cadence: read `backend/services/ai_manager_task.py` around the eval loop (`_sleep_cycle`, `evaluation_interval_s`, `safety_net_interval_s`) and check any logs/DB for real inter-cycle gaps per account.

- [ ] **Step 2: Token-count the AI Manager system prompt**

Run:
```bash
python -c "import litellm; from backend.services.ai_manager.prompts import build_system_prompt; print('NOTE: call with representative account config'); "
```
Then in a short script or REPL, build a representative system prompt and `litellm.token_counter(model='claude-sonnet-4-6', text=<it>)`.

- [ ] **Step 3: Record the decision**

Append to the tracker:
```markdown
## AI Manager caching decision (P1)
- System prompt tokens: <n> (clears 1024? <yes/no>)
- Median inter-cycle spacing: <minutes>
- 1-hr TTL breakeven (reads/write >= 2)? <yes/no>
- DECISION: [cache with 5-min TTL | cache with 1-hr TTL | DO NOT cache this path]
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "docs(caching): P1 AI Manager cadence + caching decision"
```

---

## Phase P2 — Parameter fixes (unblocks Anthropic testing on current Opus)

> Both fixes prevent HTTP 400 on Opus 4.7/4.8. Independent of caching but ordered
> first because the cache path is untestable while these 400. Reviewable/revertable
> on their own.

### Task 2.1: Add a sampling-param helper and apply it in the AI Manager httpx payloads

**Files:**
- Modify: `backend/services/ai_manager_llm_provider.py` (4 payload sites + new helper)
- Test: `tests/backend/test_ai_manager_cache.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_ai_manager_cache.py`:
```python
"""Tests for AI Manager sampling-param gating and cache_control."""


class TestSamplingParams:
    def test_omits_temperature_for_opus_4_7(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        params = _sampling_params("claude-opus-4-7")
        assert "temperature" not in params
        assert "top_p" not in params

    def test_omits_temperature_for_opus_4_8(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert "temperature" not in _sampling_params("claude-opus-4-8")

    def test_keeps_temperature_for_sonnet(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        params = _sampling_params("claude-sonnet-4-6")
        assert params["temperature"] == 0.2

    def test_keeps_temperature_for_gpt(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert _sampling_params("gpt-5.4")["temperature"] == 0.2

    def test_always_sets_max_tokens(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert _sampling_params("claude-opus-4-8")["max_tokens"] == 1024
        assert _sampling_params("claude-sonnet-4-6")["max_tokens"] == 1024
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py::TestSamplingParams -v`
Expected: FAIL with `ImportError: cannot import name '_sampling_params'`.

- [ ] **Step 3: Implement the helper**

In `backend/services/ai_manager_llm_provider.py`, add near the top (after the imports, before `create_llm_callable`):
```python
# Models that reject sampling params (temperature/top_p/top_k removed on Opus 4.7+).
# Conservative: omit for these; keep for everything else.
_NO_SAMPLING_PARAM_SUBSTRINGS = ("opus-4-7", "opus-4-8")


def _sampling_params(model: str) -> dict:
    """Return the sampling/token params to merge into a payload for this model.

    Always includes max_tokens. Omits temperature (and other sampling params)
    for models that 400 on them (current Opus). Conservative default: include
    temperature unless the model is known to reject it.
    """
    params: dict = {"max_tokens": 1024}
    model_l = (model or "").lower()
    if not any(s in model_l for s in _NO_SAMPLING_PARAM_SUBSTRINGS):
        params["temperature"] = 0.2
    return params
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py::TestSamplingParams -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Apply the helper at all 4 payload sites**

> **VERIFIED LOCATIONS (corrected).** The 4 payloads are NOT all nested inside the two
> `create_*` functions. Two live in module-level helpers that `create_llm_callable`
> calls. Edit all four:
> - `call_openai` in `create_llm_callable_with_cleanup`: temp L250, max_tokens L251
> - `call_anthropic` in `create_llm_callable_with_cleanup`: temp L285, max_tokens L286
> - `call_openai` in `_create_openai_callable` (module-level): temp L321, max_tokens L322
> - `call_anthropic` in `_create_anthropic_callable` (module-level): temp L355, max_tokens L356

In `backend/services/ai_manager_llm_provider.py`, replace the hardcoded
`"temperature": 0.2, "max_tokens": 1024,` in **each** of the 4 payloads.

For the **anthropic** payloads, change:
```python
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
```
to:
```python
                    **_sampling_params(model),
                }
```

For the **openai** payloads, make the identical change (replace the two hardcoded
lines with `**_sampling_params(model),`).

- [ ] **Step 6: Run the AI Manager provider tests + nearby suite**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py tests/backend/ -k "ai_manager or llm" -q`
Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add backend/services/ai_manager_llm_provider.py tests/backend/test_ai_manager_cache.py
git commit -m "fix(ai-manager): gate sampling params so current Opus models don't 400"
```

### Task 2.2: Fix the litellm `effort→thinking` mapping for current Opus

**Files:**
- Modify: `tradingagents/llm_clients/litellm_client.py` (the `effort` block, ~lines 184-189)
- Test: `tests/test_litellm_client.py` (add a test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_litellm_client.py`:
```python
class TestEffortThinkingMapping:
    def _model_kwargs(self, model, effort):
        from unittest.mock import patch, MagicMock
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        with patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM") as mock_cls:
            mock_cls.return_value = MagicMock()
            LiteLLMClient(model, provider="anthropic", effort=effort).get_llm()
            return mock_cls.call_args[1].get("model_kwargs", {})

    def test_opus_4_8_uses_adaptive_not_budget_tokens(self):
        mk = self._model_kwargs("claude-opus-4-8", "high")
        thinking = mk.get("thinking")
        assert thinking is not None
        assert thinking.get("type") != "enabled"
        assert "budget_tokens" not in thinking

    def test_opus_4_7_uses_adaptive_not_budget_tokens(self):
        mk = self._model_kwargs("claude-opus-4-7", "high")
        thinking = mk.get("thinking")
        assert thinking is not None
        assert thinking.get("type") != "enabled"
        assert "budget_tokens" not in thinking

    def test_older_anthropic_keeps_budget_tokens(self):
        mk = self._model_kwargs("claude-sonnet-4-6", "high")
        thinking = mk.get("thinking")
        assert thinking == {"type": "enabled", "budget_tokens": 32000}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_litellm_client.py::TestEffortThinkingMapping -v`
Expected: FAIL on the two Opus tests — current code emits `{"type": "enabled", "budget_tokens": N}` for all models.

- [ ] **Step 3: Implement the fix**

In `tradingagents/llm_clients/litellm_client.py`, replace the `effort` block:
```python
        if self.kwargs.get("effort"):
            # Anthropic extended thinking — litellm uses 'thinking' param
            budget = {"high": 32000, "medium": 16000, "low": 4000}.get(
                self.kwargs["effort"], 16000
            )
            model_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
```
with:
```python
        if self.kwargs.get("effort"):
            # Anthropic thinking. Current Opus (4.7/4.8) removed budget_tokens and
            # require adaptive thinking; the legacy enabled+budget_tokens shape 400s.
            # Use adaptive for those models; keep the legacy budget shape for older
            # Anthropic models that still accept it.
            model_l = self.model.lower()
            if "opus-4-7" in model_l or "opus-4-8" in model_l:
                model_kwargs["thinking"] = {"type": "adaptive"}
            else:
                budget = {"high": 32000, "medium": 16000, "low": 4000}.get(
                    self.kwargs["effort"], 16000
                )
                model_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_litellm_client.py::TestEffortThinkingMapping -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full litellm client suite**

Run: `python -m pytest tests/test_litellm_client.py -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add tradingagents/llm_clients/litellm_client.py tests/test_litellm_client.py
git commit -m "fix(litellm): use adaptive thinking for Opus 4.7/4.8 (budget_tokens 400s)"
```

- [ ] **Step 7: Update the progress tracker** — set P2 to DONE.

---

## Phase P3 — Prompt-cache helper + Pattern-A hygiene refactor

> Provider-agnostic: this makes the system prefix byte-stable so automatic caching
> works on every provider, and sets up the `cache_control` breakpoint for P4.
>
> **DESIGN DECISION (resolved — unconditional restructure).** The prompt
> restructuring applies **unconditionally**; only the `cache_control` marker is gated
> (at the client, P4/P7). This avoids threading a flag through ~24 agent nodes (the
> agent state from `propagation.py:create_initial_state` doesn't carry one).
> Consequences:
> - With caching OFF, prompts are **still restructured** (role-moved) but carry **no
>   `cache_control`**. The OFF-path guarantee is "no `cache_control` emitted," NOT
>   "byte-identical to today's prompts."
> - The behavior-sensitive part is the **role-move**, which is live regardless of the
>   flag — so the **P6 behavioral-parity eval gates the restructure itself**, not just
>   caching. **P6 must pass before this lands in production** (the restructure ships
>   with the feature, dark only in the sense of no cache_control).
> - For the P6 old-vs-new comparison, the **pre-P3 prompt builder must be recoverable**
>   — capture it (git tag the pre-P3 commit, or keep a `_legacy_prompt()` helper) so
>   the eval can run both. This is the only reason to retain the old builder.

### Task 3.1: Create the prompt-cache helper (split + cache_control transform)

**Files:**
- Create: `tradingagents/agents/utils/prompt_cache.py`
- Test: `tests/test_prompt_cache_helper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompt_cache_helper.py`:
```python
"""Tests for the prompt-cache shaping helper."""
from langchain_core.messages import SystemMessage, HumanMessage


class TestApplyCacheControl:
    def test_rewrites_first_system_message_to_block(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content="STABLE"), HumanMessage(content="volatile")]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0].content, list)
        block = out[0].content[0]
        assert block["type"] == "text"
        assert block["text"] == "STABLE"
        assert block["cache_control"] == {"type": "ephemeral"}
        # human turn untouched
        assert out[1].content == "volatile"

    def test_handles_dict_role_system(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [{"role": "system", "content": "STABLE"}, {"role": "user", "content": "v"}]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_noop_when_no_system_message(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [HumanMessage(content="only human")]
        out = apply_cache_control_to_messages(msgs)
        assert out[0].content == "only human"  # unchanged

    def test_only_first_system_message_marked(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content="A"), SystemMessage(content="B")]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0].content, list)
        assert out[1].content == "B"  # second left as string

    def test_noop_when_content_already_blocks(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content=[{"type": "text", "text": "X"}])]
        out = apply_cache_control_to_messages(msgs)
        # already a list — leave as-is (don't double-wrap)
        assert out[0].content == [{"type": "text", "text": "X"}]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_prompt_cache_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: ... prompt_cache`.

- [ ] **Step 3: Implement the helper**

Create `tradingagents/agents/utils/prompt_cache.py`:
```python
"""Prompt-cache shaping helpers.

Two responsibilities:
  - apply_cache_control_to_messages: rewrite the first system message to block
    form with an Anthropic `cache_control` breakpoint (used by the litellm wrapper).
  - split_cacheable_prompt: build a Pattern-A prompt template whose system message
    holds only stable text and whose first human turn holds the volatile context.

Pure functions; no I/O. The cache_control block survives langchain-community's
message converter and litellm's Anthropic transform (verified against the
installed libraries).
"""
from typing import Any

from langchain_core.messages import SystemMessage

_EPHEMERAL = {"type": "ephemeral"}


def apply_cache_control_to_messages(messages: list[Any]) -> list[Any]:
    """Return messages with the FIRST system message rewritten to a single
    text block carrying cache_control. No-op if there is no string-content
    system message. Handles both BaseMessage and {"role": ...} dict shapes.
    """
    for i, m in enumerate(messages):
        # BaseMessage form
        if isinstance(m, SystemMessage) and isinstance(m.content, str):
            new = m.model_copy(update={"content": [
                {"type": "text", "text": m.content, "cache_control": _EPHEMERAL}]})
            return [*messages[:i], new, *messages[i + 1:]]
        # dict form
        if isinstance(m, dict) and m.get("role") == "system" and isinstance(m.get("content"), str):
            new = {**m, "content": [
                {"type": "text", "text": m["content"], "cache_control": _EPHEMERAL}]}
            return [*messages[:i], new, *messages[i + 1:]]
    return messages
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_prompt_cache_helper.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/utils/prompt_cache.py tests/test_prompt_cache_helper.py
git commit -m "feat(caching): add prompt-cache message-shaping helper"
```

### Task 3.2: Add the `split_cacheable_prompt` builder for Pattern-A sites

**Files:**
- Modify: `tradingagents/agents/utils/prompt_cache.py`
- Test: `tests/test_prompt_cache_helper.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_prompt_cache_helper.py`:
```python
class TestSplitCacheablePrompt:
    def test_stable_in_system_volatile_in_human(self):
        from tradingagents.agents.utils.prompt_cache import split_cacheable_prompt
        tmpl = split_cacheable_prompt(
            stable_system="You are an analyst. Tools: {tool_names}.",
            volatile_context="Date: {current_date}. {instrument_context}",
        )
        rendered = tmpl.format_messages(
            tool_names="t1", current_date="2026-06-06",
            instrument_context="BTCUSDT", messages=[],
        )
        # system holds stable only; no date/instrument
        assert "analyst" in rendered[0].content
        assert "2026-06-06" not in rendered[0].content
        # a human turn carries the volatile context
        assert any("2026-06-06" in getattr(m, "content", "") for m in rendered[1:])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_prompt_cache_helper.py::TestSplitCacheablePrompt -v`
Expected: FAIL with `ImportError: cannot import name 'split_cacheable_prompt'`.

- [ ] **Step 3: Implement the builder**

Add to `tradingagents/agents/utils/prompt_cache.py`:
```python
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


def split_cacheable_prompt(stable_system: str, volatile_context: str) -> ChatPromptTemplate:
    """Build a Pattern-A prompt: stable system message, then a human turn holding
    the volatile context, then the MessagesPlaceholder. Template variables in both
    strings are interpolated by langchain's normal .format/.partial machinery.
    """
    return ChatPromptTemplate.from_messages([
        ("system", stable_system),
        ("human", volatile_context),
        MessagesPlaceholder(variable_name="messages"),
    ])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_prompt_cache_helper.py::TestSplitCacheablePrompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/utils/prompt_cache.py tests/test_prompt_cache_helper.py
git commit -m "feat(caching): add split_cacheable_prompt Pattern-A builder"
```

### Task 3.3: Refactor `market_analyst` to the cacheable split (unconditional, behavior-preserving)

> This is the template for all Pattern-A analyst sites. Do ONE site first, prove the
> content-preservation test, then repeat the identical shape for the other 8 in 3.4.
> The restructure is **unconditional** (Recommended option); caching is gated later
> at the client. The content-preservation test is what guards behavior here; the
> deeper decision-parity check is P6.

**Files:**
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Test: `tests/test_market_analyst_prompt.py`

- [ ] **Step 1: Write the failing content-preservation test**

> **Harness note (VERIFIED):** `create_market_analyst` does `prompt | llm.bind_tools(tools)`,
> so `bind_tools(...)` MUST return a real LangChain `Runnable` or the `|` raises
> `TypeError: Expected a Runnable`. A plain object returning `self` does NOT work. Use
> `RunnableLambda` as the bound model so the pipe composes and we capture the REAL
> rendered messages. Also patch `get_language_instruction` to a non-empty sentinel so
> the content-preservation assertion on it is meaningful (it returns `""` for the
> default English).

Create `tests/test_market_analyst_prompt.py`:
```python
"""Content-preservation for the market_analyst prompt refactor."""
import re
from unittest.mock import MagicMock, patch
from langchain_core.runnables import RunnableLambda


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _msg_text(m) -> str:
    content = getattr(m, "content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _render_market_analyst():
    """Run the node with a RunnableLambda model that captures the real rendered
    messages. Returns the captured list[BaseMessage]."""
    captured = {}

    def fake_model(prompt_value):
        captured["messages"] = (prompt_value.to_messages()
                                if hasattr(prompt_value, "to_messages") else prompt_value)
        return MagicMock(tool_calls=[], content="ok")

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = RunnableLambda(fake_model)

    from tradingagents.agents.analysts.market_analyst import create_market_analyst
    with patch("tradingagents.agents.analysts.market_analyst.get_language_instruction",
               return_value=" RESPOND_IN_TESTLANG."), \
         patch("tradingagents.agents.analysts.market_analyst.build_instrument_context",
               return_value="Asset: BTCUSDT futures"):
        node = create_market_analyst(mock_llm)
        node({"trade_date": "2026-06-06", "company_of_interest": "BTCUSDT", "messages": []})
    return captured["messages"]


class TestMarketAnalystContentPreserved:
    def test_all_content_reaches_model(self):
        msgs = _render_market_analyst()
        joined = " ".join(_norm(_msg_text(m)) for m in msgs)
        for fragment in ["trading assistant", "2026-06-06", "BTCUSDT futures",
                         "Markdown table", "RESPOND_IN_TESTLANG"]:
            assert _norm(fragment) in joined, f"missing: {fragment}"

    def test_system_message_has_no_volatile_tokens(self):
        from langchain_core.messages import SystemMessage
        msgs = _render_market_analyst()
        sys_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
        assert sys_msgs, "expected a leading system message"
        # date + instrument hoisted out of the system message into the human turn
        assert "2026-06-06" not in _msg_text(sys_msgs[0])
        assert "BTCUSDT futures" not in _msg_text(sys_msgs[0])

    def test_system_prefix_byte_stable_across_date_and_symbol(self):
        """The whole point of caching: the system prefix must be byte-identical
        across different (date, symbol) pairs, or no cache hit ever fires."""
        from langchain_core.messages import SystemMessage
        from unittest.mock import MagicMock, patch
        from langchain_core.runnables import RunnableLambda

        def _sys_for(date, symbol, instrument):
            captured = {}
            def fake_model(pv):
                captured["m"] = pv.to_messages() if hasattr(pv, "to_messages") else pv
                return MagicMock(tool_calls=[], content="ok")
            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = RunnableLambda(fake_model)
            from tradingagents.agents.analysts.market_analyst import create_market_analyst
            with patch("tradingagents.agents.analysts.market_analyst.get_language_instruction", return_value=""), \
                 patch("tradingagents.agents.analysts.market_analyst.build_instrument_context", return_value=instrument):
                create_market_analyst(mock_llm)({"trade_date": date, "company_of_interest": symbol, "messages": []})
            sys = [m for m in captured["m"] if isinstance(m, SystemMessage)][0]
            return _msg_text(sys)

        a = _sys_for("2026-06-06", "BTCUSDT", "Asset: BTC")
        b = _sys_for("2025-01-02", "ETHUSDT", "Asset: ETH")
        assert a == b, "system prefix differs across runs → caching will never hit"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_market_analyst_prompt.py -v`
Expected: FAIL on `test_system_message_has_no_volatile_tokens` — today the date is in the system message.

- [ ] **Step 3: Refactor `market_analyst.py` to the cacheable split**

In `tradingagents/agents/analysts/market_analyst.py`, replace the `prompt = ChatPromptTemplate.from_messages([...])` block + its `.partial(...)` calls with the split builder (the `system_message` variable construction above it is unchanged):
```python
        from tradingagents.agents.utils.prompt_cache import split_cacheable_prompt

        # STABLE system (no date/instrument) — byte-identical across coins/dates.
        stable_system = (
            "You are a helpful AI assistant, collaborating with other assistants."
            " Use the provided tools to progress towards answering the question."
            " If you are unable to fully answer, that's OK; another assistant with different tools"
            " will help where you left off. Execute what you can to make progress."
            " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
            " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
            " You have access to the following tools: {tool_names}.\n{system_message}"
        )
        # VOLATILE context moved into the first human turn.
        volatile_context = (
            "For your reference, the current date is {current_date}. {instrument_context}"
        )

        prompt = split_cacheable_prompt(stable_system, volatile_context)
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
```
If `ChatPromptTemplate`/`MessagesPlaceholder` imports become unused, leave them — other code in the file may use them; only remove if the linter flags them.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_market_analyst_prompt.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing analyst tests for regressions**

Run: `python -m pytest tests/ -k "market_analyst or analyst" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/analysts/market_analyst.py tests/test_market_analyst_prompt.py
git commit -m "refactor(caching): cacheable prompt split for market_analyst"
```

### Task 3.4: Apply the identical split to the remaining Pattern-A sites P1 cleared

> Only sites the P1 GO/NO-GO cleared (tokens ≥ threshold for the target model). For
> each: `news_analyst`, `social_media_analyst`, `fundamentals_analyst`, and the 5
> crypto analyst nodes (`crypto_analysts.py:112/177/224/277/326`) — repeat the
> Task-3.3 shape: extract the stable system (drop the `current date is {current_date}.
> {instrument_context}` tail), move that tail to `volatile_context`.

- [ ] **Step 1: For each cleared site, write a content-preservation test** mirroring
  `tests/test_market_analyst_prompt.py` (new file per analyst, or parametrized). Assert
  every fragment (system intro, date, instrument, any `get_language_instruction()`
  output) reaches the model, and the system message has no volatile tokens.

- [ ] **Step 2: Run each test, confirm it fails** on the no-volatile-token assertion.

- [ ] **Step 3: Apply the Task-3.3 split** to the site.

- [ ] **Step 4: Run the test, confirm it passes.**

- [ ] **Step 5: Run `python -m pytest tests/ -k analyst -q`** — no regressions.

- [ ] **Step 6: Commit per site** (`refactor(caching): cacheable prompt split for <site>`).

- [ ] **Step 7: Update the progress tracker** — list which sites were refactored and which were skipped (sub-threshold per P1).

### Task 3.5: Verify/handle Pattern B sites (trader, risk_manager, compliance_officer)

> **VERIFIED (trader):** `trader.py` builds `direction_messages = [{"role":"system",
> "content": _DIRECTION_SYSTEM}, {"role":"user", "content": _DIRECTION_USER.format(...)}]`.
> The system constant `_DIRECTION_SYSTEM` is **already stable** (no date/instrument —
> those are in the `_DIRECTION_USER` turn). So Pattern B sites where the system
> constant is already volatile-free need **NO restructuring** — the P4 client transform
> handles the `{"role":"system"}` dict form automatically. This task is **verification +
> the dict-handling test**, not a refactor, unless a site embeds volatile content in
> its system constant.

**Files:**
- Inspect: `tradingagents/agents/trader/trader.py`, `tradingagents/agents/risk/risk_manager.py`, `tradingagents/agents/compliance/compliance_officer.py`
- Test: `tests/test_pattern_b_sites.py`

- [ ] **Step 1: Inspect each Pattern B system constant for volatile content**

For each site, read the system constant passed as `{"role": "system", "content": ...}`.
Classify:
- **Already stable** (volatile content only in the user turn) → no refactor; relies on
  P4 dict-handling. (Trader's `_DIRECTION_SYSTEM` / `_LEVELS_SYSTEM` are this case.)
- **Embeds volatile content** (e.g. `{instrument_context}` inside the system string) →
  hoist it into the user turn (mirror the §4 split), OR explicitly flag the site
  non-caching in the progress tracker if hoisting would reorder stable text.

- [ ] **Step 2: Write a test proving the P4 transform marks a dict-form system message**

Create `tests/test_pattern_b_sites.py`:
```python
"""Pattern B: dict-form {"role":"system"} messages get cache_control via the transform."""
from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages


class TestPatternBDictSystem:
    def test_dict_system_marked(self):
        msgs = [{"role": "system", "content": "STABLE TRADER SYSTEM"},
                {"role": "user", "content": "volatile per-trade data"}]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert out[1]["content"] == "volatile per-trade data"  # user turn untouched
```
(This exercises the dict branch already implemented in Task 3.1; it confirms Pattern B
is covered by the shared helper without a per-site refactor.)

- [ ] **Step 3: Run the test, confirm it passes** (the helper from 3.1 already handles dicts).

Run: `python -m pytest tests/test_pattern_b_sites.py -v`
Expected: PASS.

- [ ] **Step 3b: Add a routing-regression test (the override MUST fire on structured output)**

> Pattern B routes through `with_structured_output(...).invoke`. This was verified to
> re-enter `NormalizedChatLiteLLM.invoke` (RunnableBinding delegates to `.invoke`). Lock
> that in with a test so a future langchain upgrade that bypasses `.invoke` fails CI —
> otherwise Pattern B caching would silently stop with no error.

Add to `tests/test_pattern_b_sites.py`:
```python
class TestStructuredOutputRoutesThroughOverride:
    def test_with_structured_output_invoke_hits_override(self):
        from unittest.mock import patch
        from pydantic import BaseModel
        from langchain_core.messages import SystemMessage, HumanMessage
        from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM

        class Out(BaseModel):
            action: str

        llm = NormalizedChatLiteLLM(model="anthropic/claude-sonnet-4-6", api_key="dummy")
        fired = {"hit": False}
        real_invoke = NormalizedChatLiteLLM.invoke

        def spy(self, input, config=None, **kwargs):
            fired["hit"] = True
            # short-circuit: don't actually call the network
            from unittest.mock import MagicMock
            return MagicMock(content='{"action":"Hold"}', tool_calls=[], usage_metadata=None)

        with patch.object(NormalizedChatLiteLLM, "invoke", spy):
            structured = llm.with_structured_output(Out, method="function_calling")
            try:
                structured.invoke([SystemMessage(content="S"), HumanMessage(content="u")])
            except Exception:
                pass  # parsing may fail on the mock; we only care that .invoke fired
        assert fired["hit"], "structured-output path bypassed NormalizedChatLiteLLM.invoke"
```

Run: `python -m pytest tests/test_pattern_b_sites.py::TestStructuredOutputRoutesThroughOverride -v`
Expected: PASS. (If it FAILS, the structured-output path no longer routes through our
override — Pattern B caching is broken and the mechanism needs revisiting before P4.)

- [ ] **Step 4: Record the per-site Pattern B finding** in the progress tracker
  (which sites are already-stable vs need hoisting vs flagged non-caching).

- [ ] **Step 5: Commit**

```bash
git add tests/test_pattern_b_sites.py docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "test(caching): verify Pattern B dict-system sites covered by cache_control transform"
```

> **NOTE on `invoke_structured_or_freetext`:** Pattern B sites call the model via
> `bind_structured(...)` / `invoke_structured_or_freetext(...)` (`structured.py`), which
> route through `with_structured_output(...).invoke` → a `RunnableBinding` whose
> `.bound` is `NormalizedChatLiteLLM` → our `invoke` override fires. The transform
> therefore applies on these paths too. The structured **free-text fallback**
> (`invoke_structured_or_freetext` calling `plain_llm.invoke`) also passes through the
> same wrapper, so caching applies whenever the message list has a leading system
> dict. Verify this routing holds during implementation (it relies on langchain's
> RunnableBinding delegating to `.invoke`, confirmed in prior analysis).

---

## Phase P4 — `cache_control` injection (the heart)

> **Resolved (unconditional restructure, see P3):** the flag reaches the client via
> config (Task 4.2), NOT via agent state. P3 restructures prompts unconditionally;
> P4 gates only the `cache_control` marker.

### Task 4.1: Add the `cache_control` transform to `NormalizedChatLiteLLM.invoke`

**Files:**
- Modify: `tradingagents/llm_clients/litellm_client.py` (`NormalizedChatLiteLLM`)
- Test: `tests/test_litellm_cache_injection.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/test_litellm_cache_injection.py`:
```python
"""Tests for cache_control injection in NormalizedChatLiteLLM."""
from unittest.mock import patch
from langchain_core.messages import SystemMessage, HumanMessage


def _make(model_name, cache_enabled):
    from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM
    llm = NormalizedChatLiteLLM(model=model_name, api_key="dummy")
    llm._cache_enabled = cache_enabled
    return llm


class TestCacheInjection:
    def _capture_input(self, llm, messages):
        captured = {}
        def fake_super_invoke(input, config=None, **kwargs):
            captured["input"] = input
            from unittest.mock import MagicMock
            return MagicMock(content="ok", usage_metadata=None)
        with patch("tradingagents.llm_clients.litellm_client.llm_rate_limited_invoke",
                   side_effect=lambda fn, inp, cfg, **kw: fake_super_invoke(inp, cfg, **kw)):
            llm.invoke(messages)
        return captured["input"]

    def test_marks_system_for_anthropic_when_enabled(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert isinstance(out[0].content, list)
        assert out[0].content[0]["cache_control"] == {"type": "ephemeral"}

    def test_no_mark_when_disabled(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=False)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert out[0].content == "STABLE"  # untouched

    def test_no_mark_for_non_anthropic(self):
        llm = _make("gpt-5.4", cache_enabled=True)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert out[0].content == "STABLE"  # openai → no cache_control

    def test_handles_chatpromptvalue_shape(self):
        from langchain_core.prompt_values import ChatPromptValue
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        pv = ChatPromptValue(messages=[SystemMessage(content="STABLE"), HumanMessage(content="v")])
        out = self._capture_input(llm, pv)
        assert isinstance(out[0].content, list)  # to_messages() unwrapped + marked

    def test_handles_bare_string_noop(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        out = self._capture_input(llm, "just a string, no system message")
        assert out == "just a string, no system message"  # no-op, no crash

    def test_handles_list_of_tuples_noop_or_marks(self):
        # list[tuple] like [("system","X"),("human","y")] has no SystemMessage object
        # nor a role-dict, so the transform is a safe no-op (does not crash).
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        msgs = [("system", "STABLE"), ("human", "v")]
        out = self._capture_input(llm, msgs)
        assert out == msgs  # unchanged — tuple form not matched, no error
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_litellm_cache_injection.py -v`
Expected: FAIL — `NormalizedChatLiteLLM` has no `_cache_enabled` handling in `invoke`.

- [ ] **Step 3: Implement the transform**

In `tradingagents/llm_clients/litellm_client.py`, modify `NormalizedChatLiteLLM`. **Do
NOT declare `_cache_enabled` as a class-level Pydantic field** (annotating it on a
Pydantic model conflicts with private-attribute handling). Instead read it with
`getattr(self, "_cache_enabled", False)` and have the factory set it on the instance
(verified: setting `llm._cache_enabled = True` on the constructed instance works).
Rewrite `invoke`:
```python
class NormalizedChatLiteLLM(ChatLiteLLM):
    # ... existing docstring + _client_params unchanged; do NOT add a class field ...

    def invoke(self, input, config=None, **kwargs):
        # self.model holds the litellm-prefixed string (verified: "anthropic/claude-…")
        if getattr(self, "_cache_enabled", False) and str(self.model).startswith("anthropic/"):
            input = self._inject_cache_control(input)
        return normalize_content(llm_rate_limited_invoke(super().invoke, input, config, **kwargs))

    def _inject_cache_control(self, input):
        """Rewrite the first system message to a cache_control block.

        Handles ChatPromptValue / list[BaseMessage] / list[dict]. Other shapes
        pass through unchanged (no-op)."""
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        if hasattr(input, "to_messages"):
            return apply_cache_control_to_messages(input.to_messages())
        if isinstance(input, list):
            return apply_cache_control_to_messages(input)
        return input
```
Verified facts (do not re-litigate): `self.model` returns the prefixed string
(e.g. `anthropic/claude-sonnet-4-6`); `self._cache_enabled` is settable on the
instance; block-form `cache_control` survives to Anthropic's `system` param (Task 4.3).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_litellm_cache_injection.py::TestCacheInjection -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the litellm client suite**

Run: `python -m pytest tests/test_litellm_client.py tests/test_litellm_cache_injection.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/llm_clients/litellm_client.py tests/test_litellm_cache_injection.py
git commit -m "feat(caching): inject cache_control on system msg for anthropic/* in litellm wrapper"
```

### Task 4.2: Thread `prompt_cache_enabled` from config → client

**Files:**
- Modify: `tradingagents/llm_clients/litellm_client.py` (`LiteLLMClient.get_llm`)
- Modify: `tradingagents/llm_clients/factory.py` (accept + forward the flag)
- Modify: `tradingagents/graph/trading_graph.py` (pass it from config)
- Test: `tests/test_litellm_cache_injection.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_litellm_cache_injection.py`:
```python
class TestCacheFlagWiring:
    def test_get_llm_sets_cache_enabled_from_kwarg(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        llm = LiteLLMClient("claude-sonnet-4-6", provider="anthropic",
                            prompt_cache_enabled=True).get_llm()
        assert llm._cache_enabled is True

    def test_get_llm_defaults_cache_disabled(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        llm = LiteLLMClient("claude-sonnet-4-6", provider="anthropic").get_llm()
        assert llm._cache_enabled is False

    def test_factory_forwards_flag(self):
        from tradingagents.llm_clients.factory import create_llm_client
        client = create_llm_client("anthropic", "claude-sonnet-4-6",
                                   prompt_cache_enabled=True)
        llm = client.get_llm()
        assert llm._cache_enabled is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_litellm_cache_injection.py::TestCacheFlagWiring -v`
Expected: FAIL — `prompt_cache_enabled` not consumed yet.

- [ ] **Step 3: Consume the flag in `LiteLLMClient.get_llm`**

In `tradingagents/llm_clients/litellm_client.py`, at the end of `get_llm` (before `return NormalizedChatLiteLLM(**llm_kwargs)`), pop the flag from `self.kwargs` and set it on the instance:
```python
        instance = NormalizedChatLiteLLM(**llm_kwargs)
        instance._cache_enabled = bool(self.kwargs.get("prompt_cache_enabled", False))
        return instance
```
Also ensure `prompt_cache_enabled` is **not** forwarded into `llm_kwargs` (it isn't in the `_PASSTHROUGH`/`for key in (...)` loop, so it's already excluded — verify it's not added elsewhere).

- [ ] **Step 4: Forward the flag through the factory**

In `tradingagents/llm_clients/factory.py`, `prompt_cache_enabled` arrives via `**kwargs` and is passed straight into `LiteLLMClient(model, base_url, provider=provider_lower, **kwargs)` — confirm `**kwargs` flows (it does). No code change needed unless the factory filters kwargs; if it does, add `prompt_cache_enabled` to the allowed set.

- [ ] **Step 5: Pass the flag from `trading_graph.py`**

In `tradingagents/graph/trading_graph.py`, add the flag at the `create_llm_client(...)`
calls:
- **L179 (deep)** and **L186 (quick)**: add `prompt_cache_enabled=self.config.get("prompt_cache_enabled", False),` alongside `**llm_kwargs`.
- **L421 (agent override) — IMPORTANT:** this call passes `**safe_kwargs`, and
  `safe_kwargs` (built ~L415-419) deliberately strips provider-specific keys, carrying
  only `callbacks`/`api_key`. So adding it to `llm_kwargs` won't reach this call —
  add it explicitly:
  ```python
              prompt_cache_enabled=self.config.get("prompt_cache_enabled", False),
  ```
  as a direct kwarg on the L421 `create_llm_client(...)` call (not via `safe_kwargs`).

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_litellm_cache_injection.py::TestCacheFlagWiring -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the graph + client suites**

Run: `python -m pytest tests/test_litellm_client.py tests/test_litellm_cache_injection.py tests/test_trading_graph.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tradingagents/llm_clients/litellm_client.py tradingagents/llm_clients/factory.py tradingagents/graph/trading_graph.py tests/test_litellm_cache_injection.py
git commit -m "feat(caching): thread prompt_cache_enabled from config to litellm client"
```

### Task 4.3: Real-binding wire test — `cache_control` reaches Anthropic's `system` param

> The unit tests above mock transport. This test runs the REAL
> langchain-community → litellm Anthropic transform (no mock) so a future library
> upgrade that drops the breakpoint fails CI. (Spec §8.3.)

**Files:**
- Test: `tests/test_litellm_cache_injection.py`

- [ ] **Step 1: Write the real-binding test**

Add to `tests/test_litellm_cache_injection.py`:
```python
class TestRealBindingPayload:
    def test_cache_control_reaches_anthropic_system_param(self):
        # Drive the ACTUAL litellm Anthropic transform (no transport mock) and
        # assert the final request carries cache_control on the system param.
        import json
        from litellm.llms.anthropic.chat.transformation import AnthropicConfig
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        from langchain_community.chat_models.litellm import _convert_message_to_dict
        from langchain_core.messages import SystemMessage, HumanMessage

        msgs = apply_cache_control_to_messages(
            [SystemMessage(content="STABLE " * 300), HumanMessage(content="date 2026-06-06")])
        dicts = [_convert_message_to_dict(m) for m in msgs]
        out = AnthropicConfig().transform_request(
            model="claude-sonnet-4-6", messages=dicts,
            optional_params={}, litellm_params={}, headers={})
        payload = json.dumps(out)
        assert "cache_control" in payload
        # exactly one breakpoint, on the system param
        assert payload.count("cache_control") == 1
        assert out.get("system") and out["system"][0]["cache_control"] == {"type": "ephemeral"}
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_litellm_cache_injection.py::TestRealBindingPayload -v`
Expected: PASS. (If the litellm import path differs in a future version, update the import — that's exactly the breakage this test is meant to surface.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_litellm_cache_injection.py
git commit -m "test(caching): real-binding assertion that cache_control reaches Anthropic system param"
```

- [ ] **Step 4: Offline engagement check (§8.7b) — confirm a real cache HIT**

> CI (Step 1-3) proves the payload *structure* would cache. This step proves caching
> actually *engages* against the live API — run ONCE, offline, recorded; not in CI.

Write `scripts/verify_cache_engagement.py` that, with real `ANTHROPIC_API_KEY` and a
cacheable prefix (≥1024 tok), sends the **same** cacheable request twice via the real
`NormalizedChatLiteLLM` (`_cache_enabled=True`, `anthropic/claude-sonnet-4-6`) and
prints `usage_metadata['input_token_details']` for both. Expected: 2nd call shows
`cache_read > 0`. Record the output in the progress tracker as the engagement evidence.
```bash
python scripts/verify_cache_engagement.py   # needs ANTHROPIC_API_KEY; small spend
```
Commit the script + recorded result:
```bash
git add scripts/verify_cache_engagement.py docs/superpowers/plans/2026-06-06-prompt-caching-progress.md
git commit -m "test(caching): offline cache-engagement verification (real cache_read>0)"
```

### Task 4.4: AI Manager Anthropic branch — `cache_control` on the system block (if P1 cleared it)

> Skip this task if P1 decided the AI Manager prefix is sub-threshold / cadence
> doesn't pay off. Otherwise apply to both `call_anthropic` payloads.

**Files:**
- Modify: `backend/services/ai_manager_llm_provider.py` (2 `call_anthropic` payloads)
- Test: `tests/backend/test_ai_manager_cache.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/backend/test_ai_manager_cache.py`:
```python
class TestAnthropicCacheControl:
    def test_system_is_cache_control_block(self):
        from backend.services.ai_manager_llm_provider import _anthropic_system_param
        out = _anthropic_system_param("SYS", cache_enabled=True)
        assert out == [{"type": "text", "text": "SYS",
                        "cache_control": {"type": "ephemeral"}}]

    def test_plain_string_when_disabled(self):
        from backend.services.ai_manager_llm_provider import _anthropic_system_param
        assert _anthropic_system_param("SYS", cache_enabled=False) == "SYS"

    def test_one_hour_ttl_emitted(self):
        from backend.services.ai_manager_llm_provider import _anthropic_system_param
        out = _anthropic_system_param("SYS", cache_enabled=True, ttl="1h")
        assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py::TestAnthropicCacheControl -v`
Expected: FAIL — `_anthropic_system_param` undefined.

- [ ] **Step 3: Implement the helper + apply it**

In `backend/services/ai_manager_llm_provider.py`, add the helper (with optional `ttl`
so P1's 5-min-vs-1-hour decision can be honored — §6a):
```python
def _anthropic_system_param(system_prompt: str, cache_enabled: bool, ttl: str = "5m"):
    """Return the `system` field: a cache_control block when enabled, else the
    plain string. ttl is "5m" (default) or "1h" per the P1 cadence decision."""
    if cache_enabled:
        cc = {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": "1h"}
        return [{"type": "text", "text": system_prompt, "cache_control": cc}]
    return system_prompt
```
Then thread a `cache_enabled` flag into `create_llm_callable_with_cleanup` /
`create_llm_callable` (add a `cache_enabled: bool = False` parameter, default False;
optionally `cache_ttl: str = "5m"`), and in each `call_anthropic` payload replace
`"system": system_prompt,` with
`"system": _anthropic_system_param(system_prompt, cache_enabled, cache_ttl),`. Wire the
flag from the AI Manager config resolution
(`ai_account_manager_service._create_llm_from_scan_configs` → pass
`cache_enabled=<resolved prompt_cache_enabled>`), and include it in
`_extract_llm_identity` so a toggle change rebuilds the callable.

- [ ] **Step 4: Run the test, confirm it passes.**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_manager_llm_provider.py backend/services/ai_account_manager_service.py tests/backend/test_ai_manager_cache.py
git commit -m "feat(caching): cache_control on AI Manager Anthropic system block (flag-gated)"
```

- [ ] **Step 6: Update the progress tracker** — P4 done; note whether AI Manager caching was implemented or skipped per P1.

---

## Phase P5 — Cache-metric logging

> One chokepoint: every wrapper funnels through `llm_rate_limited_invoke`
> (`base_client.py:59`). Read langchain's normalized `usage_metadata` (same path for
> Anthropic / OpenAI-Responses / Gemini). Distinguish `None` (not reported) from `0`.

### Task 5.1: Add a cache-metric log helper and call it from the invoke chokepoint

**Files:**
- Modify: `tradingagents/llm_clients/base_client.py` (`extract_cache_metrics` helper)
- Modify: `tradingagents/llm_clients/litellm_client.py` (log call in `NormalizedChatLiteLLM.invoke`)
- Test: `tests/test_cache_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cache_metrics.py`:
```python
"""Tests for cache-metric extraction/logging."""
from unittest.mock import MagicMock


class TestExtractCacheMetrics:
    def test_reads_usage_metadata_cache_read(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = {"input_tokens": 10,
                               "input_token_details": {"cache_read": 1840, "cache_creation": 0}}
        m = extract_cache_metrics(resp)
        assert m["cache_read"] == 1840
        assert m["cache_creation"] == 0

    def test_absent_details_is_none_not_zero(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = {"input_tokens": 10}  # no input_token_details
        m = extract_cache_metrics(resp)
        assert m["cache_read"] is None  # not reported, NOT a real zero

    def test_no_usage_metadata_returns_none_metrics(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = None
        m = extract_cache_metrics(resp)
        assert m["cache_read"] is None
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python -m pytest tests/test_cache_metrics.py -v`
Expected: FAIL — `extract_cache_metrics` undefined.

- [ ] **Step 3: Implement the extractor + log call**

In `tradingagents/llm_clients/base_client.py`, add:
```python
def extract_cache_metrics(response) -> dict:
    """Pull normalized cache token counts from a langchain response.

    langchain maps Anthropic / OpenAI-Responses / Gemini all to
    usage_metadata['input_token_details']['cache_read' | 'cache_creation'].
    Returns None for a field the provider did not report (distinct from 0).
    """
    um = getattr(response, "usage_metadata", None) or {}
    details = um.get("input_token_details") or {}
    return {
        "input_tokens": um.get("input_tokens"),
        "cache_read": details.get("cache_read"),
        "cache_creation": details.get("cache_creation"),
    }
```
Then log the metrics. **Use the per-wrapper approach (simpler, avoids threading a
kwarg through `llm_rate_limited_invoke` and the pop/get bug):** add the metric read +
log to each `Normalized*.invoke` override, where `self.model` is in scope. The shared
`extract_cache_metrics` helper does the field extraction; each wrapper logs with its
own model label.

In `NormalizedChatLiteLLM.invoke` (and analogously the other wrappers if desired),
wrap the result:
```python
    def invoke(self, input, config=None, **kwargs):
        if getattr(self, "_cache_enabled", False) and str(self.model).startswith("anthropic/"):
            input = self._inject_cache_control(input)
        result = normalize_content(llm_rate_limited_invoke(super().invoke, input, config, **kwargs))
        try:
            from tradingagents.llm_clients.base_client import extract_cache_metrics
            m = extract_cache_metrics(result)
            if m["cache_read"] is not None or m["cache_creation"] is not None:
                logger.info("LLM cache | model=%s input=%s cache_read=%s cache_creation=%s",
                            self.model, m["input_tokens"], m["cache_read"], m["cache_creation"])
        except Exception:
            pass  # never let metric logging break a call
        return result
```
(Add `import logging; logger = logging.getLogger(__name__)` at the top of
`litellm_client.py` if not already present — it is.) `llm_rate_limited_invoke` itself is
**left unchanged**, so the other wrappers (`NormalizedChatAnthropic`,
`NormalizedChatOpenAI`, `NormalizedChatGoogleGenerativeAI`) keep working untouched; add
the same try/log block to them only if you want their cache metrics too (recommended for
the OpenAI/Google graph paths — same 3-line block, using `self.model_name`/`self.model`
as appropriate per class).
> `extract_cache_metrics` stays a `base_client.py` function (Step 3 above); only the
> per-wrapper `invoke` overrides gain the log call. **Files for this task therefore
> include `tradingagents/llm_clients/litellm_client.py`** (and optionally the other
> wrapper files), not just `base_client.py`.

- [ ] **Step 4: Run the test, confirm it passes.**

Run: `python -m pytest tests/test_cache_metrics.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the base-client / litellm suites for regressions.**

Run: `python -m pytest tests/test_litellm_client.py tests/test_llm_clients.py tests/test_cache_metrics.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/llm_clients/base_client.py tradingagents/llm_clients/litellm_client.py tests/test_cache_metrics.py
git commit -m "feat(caching): log normalized cache metrics from the invoke chokepoint"
```

### Task 5.2: AI Manager — populate `_input_tokens` + cache metrics from `usage`

**Files:**
- Modify: `backend/services/ai_manager_llm_provider.py` (read `usage` in both branches)
- Test: `tests/backend/test_ai_manager_cache.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/backend/test_ai_manager_cache.py`:
```python
class TestAIManagerUsageExtraction:
    def test_anthropic_usage_cache_fields(self):
        from backend.services.ai_manager_llm_provider import _extract_cache_usage
        data = {"usage": {"input_tokens": 12,
                          "cache_read_input_tokens": 1840,
                          "cache_creation_input_tokens": 0}}
        m = _extract_cache_usage(data, provider="anthropic")
        assert m["cache_read"] == 1840

    def test_openai_usage_cache_fields(self):
        from backend.services.ai_manager_llm_provider import _extract_cache_usage
        data = {"usage": {"prompt_tokens": 12,
                          "prompt_tokens_details": {"cached_tokens": 900}}}
        m = _extract_cache_usage(data, provider="openai")
        assert m["cache_read"] == 900
```

- [ ] **Step 2: Run the test, confirm it fails.**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py::TestAIManagerUsageExtraction -v`
Expected: FAIL — `_extract_cache_usage` undefined.

- [ ] **Step 3: Implement + log**

In `backend/services/ai_manager_llm_provider.py`, add:
```python
def _extract_cache_usage(data: dict, provider: str) -> dict:
    """Read cache token counts from a raw provider response `usage` object."""
    usage = (data or {}).get("usage") or {}
    if provider == "anthropic":
        return {"cache_read": usage.get("cache_read_input_tokens"),
                "cache_creation": usage.get("cache_creation_input_tokens")}
    details = usage.get("prompt_tokens_details") or {}
    return {"cache_read": details.get("cached_tokens"), "cache_creation": None}
```
After `data = resp.json()` in each branch (before returning the extracted text), log
the cache metrics. **Reconcile with existing infra (spec §7 — do NOT build a second
stack):** `ai_manager_task.py` already logs `result.get("_input_tokens", 0)` (currently
always 0 because nothing populates it). Where the AI Manager graph node assembles its
result, **populate `_input_tokens` (and add cache read/creation) from the parsed
`usage`** so the existing logger surfaces them, rather than adding an independent
logging path. A lightweight `logger.info` here is acceptable for the immediate signal,
but the durable record must flow through the existing `_input_tokens` field:
```python
                _m = _extract_cache_usage(data, "anthropic")  # or "openai"
                if _m["cache_read"] is not None:
                    logger.info("AI Manager LLM cache | provider=%s model=%s cache_read=%s",
                                "anthropic", model, _m["cache_read"])
```
> Trace where `action_generation_node` (`ai_manager_graph.py`) builds its return dict
> and set `_input_tokens` / cache fields there from the `usage` the callable saw. If the
> callable doesn't currently surface `usage` to the node, thread it through (the
> callable returns text today — extend its contract or stash the last-usage on the
> callable). Record in the tracker how `_input_tokens` is now populated.

- [ ] **Step 4: Run the test, confirm it passes.**

Run: `python -m pytest tests/backend/test_ai_manager_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_manager_llm_provider.py tests/backend/test_ai_manager_cache.py
git commit -m "feat(caching): extract + log AI Manager cache usage from provider responses"
```

- [ ] **Step 6: Update the progress tracker** — P5 done.

---

## Phase P6 — Behavioral-parity eval GATE (must pass before default ON)

> Offline, spend-capped, NOT in CI. Compares structured decisions old-vs-new prompt.
> See spec §8.6. This phase produces a recorded pass/fail artifact, not shipped code.

### Task 6.1: Build the eval harness

**Files:**
- Create: `scripts/cache_parity_eval.py`
- Create: `docs/superpowers/plans/cache-parity-eval-results.md` (the recorded artifact)

- [ ] **Step 1: Assemble fixtures**

Pick **N=30–50** representative `(symbol, trade_date, market-state)` fixtures spanning
bull / bear / chop. Store them in the script as a list. Use real configured model(s).

- [ ] **Step 2: Write the harness**

> **Old-prompt recovery (concrete, not hand-waved):** P6 compares old-vs-new prompts,
> so the pre-P3 prompt must be runnable at eval time. Pick ONE concrete mechanism and
> record it in the tracker:
> - **(Recommended) Git-ref capture:** P0 tags the pre-P3 commit (`git tag pre-cache-p3`).
>   The eval runs the NEW prompt from `HEAD` and the OLD prompt by checking out the
>   agent files at `pre-cache-p3` in a throwaway worktree, or by reading the old prompt
>   string from that ref. No production code carries dead branches.
> - **Alternative:** during P3, keep the old prompt string as a module constant
>   `_LEGACY_SYSTEM_PROMPT` (commented "for P6 eval only; delete after eval passes") so
>   the harness can build both without git gymnastics.

Create `scripts/cache_parity_eval.py` that, for each fixture:
1. Runs the relevant agent(s) with the **OLD** prompt structure (via the recovery
   mechanism above) K≈5 times → record decision labels (BUY/HOLD/SELL) and any numeric
   scores → compute the **noise floor** (intrinsic disagreement).
2. Runs the **NEW** prompt structure once per fixture → record decisions.
3. Compares: new-vs-old **label agreement ≥ (1 − noise_floor)** over N fixtures, **and**
   McNemar's test p > 0.05 (no systematic drift). Score deltas within f(measured variance).
Print a summary and write it to `cache-parity-eval-results.md`.

> Note: this requires live API keys and real spend. Cap it (small N, cheap model for
> the harness shakeout, then the real configured model for the recorded run). Do not
> run in CI.

- [ ] **Step 3: Run the eval and record the verdict**

Run: `python scripts/cache_parity_eval.py`
Record the full output (noise floor, agreement %, McNemar p) in
`docs/superpowers/plans/cache-parity-eval-results.md` with an explicit
**PASS** / **FAIL** and the date.

- [ ] **Step 4: Commit the harness + results**

```bash
git add scripts/cache_parity_eval.py docs/superpowers/plans/cache-parity-eval-results.md
git commit -m "test(caching): behavioral-parity eval harness + recorded results"
```

- [ ] **Step 5: Update the progress tracker** — P6 PASS/FAIL. **If FAIL: stop. Do not
  enable the default in P7.** Investigate the drift; the role-move may need revisiting.

---

## Phase P7 — Global ops flag (default OFF)

### Task 7.1: Add the config default + env override

> Do this EARLY if convenient — the P3/P4 tasks read `config.get("prompt_cache_enabled")`.
> It is placed in P7 because *enabling* it (default→True) is the gated action; adding
> the key (default False) is harmless and can land anytime.

**Files:**
- Modify: `tradingagents/default_config.py`
- Test: `tests/test_default_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_default_config.py`:
```python
class TestPromptCacheFlag:
    def test_defaults_off(self, monkeypatch):
        monkeypatch.delenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", raising=False)
        import importlib
        import tradingagents.default_config as dc
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["prompt_cache_enabled"] is False

    def test_env_override_on(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", "true")
        import importlib
        import tradingagents.default_config as dc
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["prompt_cache_enabled"] is True
```

- [ ] **Step 2: Run the test, confirm it fails.**

Run: `python -m pytest tests/test_default_config.py -v`
Expected: FAIL — key missing.

- [ ] **Step 3: Add the config key**

In `tradingagents/default_config.py`, inside `DEFAULT_CONFIG`, add (near the LLM settings):
```python
    # Prompt caching: OFF until the behavioral-parity eval (P6) passes.
    "prompt_cache_enabled": os.getenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", "").lower()
        in ("1", "true", "yes"),
```

- [ ] **Step 4: Run the test, confirm it passes.**

Run: `python -m pytest tests/test_default_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/default_config.py tests/test_default_config.py
git commit -m "feat(caching): add prompt_cache_enabled config flag (default OFF, env override)"
```

- [ ] **Step 6: Update the progress tracker** — P7 done. **Flipping the default to ON
  is a SEPARATE PR, made only after P6 records PASS.**

---

## Phase P8 — Per-run UI toggle

> Depends on P7. Default follows the global flag. Mirrors the existing
> `checkpoint_enabled` wiring (already present in all 3 forms — use it as the template).

### Task 8.1: Backend schema — add `prompt_cache_enabled` to the request models

**Files:**
- Modify: `backend/schemas/__init__.py` (`AnalysisRequest` ~line 110, `ScanRequest` ~line 475)
- Test: `tests/backend/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/backend/test_schemas.py`:
```python
class TestPromptCacheField:
    def test_analysis_request_accepts_flag(self):
        from backend.schemas import AnalysisRequest
        r = AnalysisRequest(ticker="BTC", analysis_date="2026-06-06",
                            prompt_cache_enabled=True)
        assert r.prompt_cache_enabled is True

    def test_scan_request_accepts_flag(self):
        from backend.schemas import ScanRequest
        # ScanRequest requires analysis_date; everything else has defaults.
        r = ScanRequest(analysis_date="2026-06-06", prompt_cache_enabled=False)
        assert r.prompt_cache_enabled is False

    def test_defaults_none(self):
        from backend.schemas import AnalysisRequest
        r = AnalysisRequest(ticker="BTC", analysis_date="2026-06-06")
        assert r.prompt_cache_enabled is None
```
(Fill any other required fields on `ScanRequest` per its definition.)

- [ ] **Step 2: Run the test, confirm it fails.**

Run: `python -m pytest tests/backend/test_schemas.py::TestPromptCacheField -v`
Expected: FAIL — field unknown.

- [ ] **Step 3: Add the field to both models**

In `backend/schemas/__init__.py`, add to `AnalysisRequest` (near `checkpoint_enabled`)
and to `ScanRequest`:
```python
    prompt_cache_enabled: Optional[bool] = None
```
**Do NOT add it to `AutoTradeConfig`** (it has `extra="forbid"` and would reject it;
wrong layer).

- [ ] **Step 4: Run the test, confirm it passes.**

Run: `python -m pytest tests/backend/test_schemas.py::TestPromptCacheField -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/__init__.py tests/backend/test_schemas.py
git commit -m "feat(caching): add prompt_cache_enabled to AnalysisRequest + ScanRequest"
```

### Task 8.2: Backend — relay the flag into config at both read sites

**Files:**
- Modify: `backend/services/analysis_service.py` (`_build_config` at **L285**; the
  `checkpoint_enabled` relay it contains is at **L319-320** — mirror that)
- Modify: `backend/services/scanner_service.py` (`_run_single` at **L879**; the
  `checkpoint_enabled` relay line is **L903**)
- Test: `tests/backend/test_analysis_service.py` (or nearest existing)

- [ ] **Step 1: Write the failing test** asserting that when a request carries
  `prompt_cache_enabled=True`, the resolved config dict passed to the graph has
  `config["prompt_cache_enabled"] is True`, and that `None` falls back to the
  default. Use the existing `_build_config` test patterns in that file.

- [ ] **Step 2: Run it, confirm it fails.**

- [ ] **Step 3: Implement**

In `analysis_service._build_config` (L285), mirror the existing `checkpoint_enabled`
relay (L319-320) exactly — `request` is a `Dict[str, Any]`, so use `.get(...)`:
```python
        if request.get("prompt_cache_enabled") is not None:
            config["prompt_cache_enabled"] = request["prompt_cache_enabled"]
        else:
            config["prompt_cache_enabled"] = DEFAULT_CONFIG["prompt_cache_enabled"]
```
In `scanner_service._run_single` (L879), next to the `checkpoint_enabled` relay (L903
`"checkpoint_enabled": config.get("checkpoint_enabled"),`), add:
```python
            "prompt_cache_enabled": config.get("prompt_cache_enabled"),
```

- [ ] **Step 4: Run it, confirm it passes; run `python -m pytest tests/backend/ -k "analysis or scanner" -q`.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/analysis_service.py backend/services/scanner_service.py tests/backend/
git commit -m "feat(caching): relay prompt_cache_enabled from request into graph config"
```

### Task 8.3: Frontend — add the toggle to all three forms + API types

**Files:**
- Modify: `frontend/src/api/client.ts` (`StartAnalysisRequest` ~line 194, scan request type ~line 290)
- Modify: `frontend/src/components/analysis/ConfigForm.tsx` (mirror `checkpoint_enabled`: RHF schema, payload ~line 434, UI control ~line 1086)
- Modify: `frontend/src/components/scanner/ScannerPage.tsx` (state + payload ~line 503)
- Modify: `frontend/src/components/scanner/ScheduledScansPage.tsx` (state + payload ~line 1022)

- [ ] **Step 1: Add the field to the TS request interfaces**

In `frontend/src/api/client.ts`, add to `StartAnalysisRequest` and the scan request interface:
```typescript
  prompt_cache_enabled?: boolean;
```

- [ ] **Step 2: ConfigForm — add the control (copy the `checkpoint_enabled` pattern)**

Find every place `checkpoint_enabled` appears in `ConfigForm.tsx` and add a sibling
`prompt_cache_enabled` (RHF default `false`, a labelled checkbox/switch in the Engine
section near the provider selector, and include it in the submit payload ~line 434).

- [ ] **Step 3: ScannerPage + ScheduledScansPage — add state + payload**

In each, add a `promptCacheEnabled` state (default `false`) and include
`prompt_cache_enabled: promptCacheEnabled` in the submit payload (mirror the
`checkpoint_enabled` / model-state lines).

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/analysis/ConfigForm.tsx frontend/src/components/scanner/ScannerPage.tsx frontend/src/components/scanner/ScheduledScansPage.tsx
git commit -m "feat(caching): per-run prompt caching toggle in the 3 LLM-settings forms"
```

- [ ] **Step 7: Update the progress tracker** — P8 done. Feature complete (still
  default OFF until the P6-gated enable PR).

---

## Final verification

- [ ] Run the full backend suite: `python -m pytest tests/ -q` — all pass.
- [ ] Frontend type-check + build: `cd frontend && npx tsc --noEmit && npm run build`.
- [ ] Confirm OFF-path: with `prompt_cache_enabled` unset/False, grep a real run's
  logs — **no `cache_control` in outgoing payloads** and no `LLM cache` lines with
  `cache_read>0`. (Note: prompts are still restructured when OFF — the OFF guarantee
  is "no cache_control," not "byte-identical to pre-P3 prompts." The restructure's
  behavior safety comes from the P6 eval, which must have passed.)
- [ ] Confirm the progress tracker shows all phases DONE and records the P1 GO/NO-GO
  and P6 PASS/FAIL artifacts.
- [ ] Update `CLAUDE.md` "Recent Changes" with a one-line summary.

## Known lower-priority follow-ups (track, don't block)

These are minor and can be handled during their phase or as fast-follows — noted so
they aren't lost:
- **`max_completion_tokens` (§8.4):** reasoning models (OpenAI o-series/GPT-5) expect
  `max_completion_tokens` not `max_tokens`. `_sampling_params` (Task 2.1) currently
  always emits `max_tokens`. If the AI Manager is pointed at a reasoning model, extend
  `_sampling_params` to emit `max_completion_tokens` for those model families. litellm's
  `drop_params` handles the graph path; the raw-httpx path does not.
- **Identity-hash test (Task 4.4):** the plan threads `cache_enabled` into
  `_extract_llm_identity` in prose — add an explicit test that two identities differ
  when only `cache_enabled` differs, so a toggle change rebuilds the callable.
- **Scheduled-scan `scan_config` relay (Task 8.x):** the scheduled form nests the flag
  in the freeform `scan_config` dict. Add a backend test that a scheduled scan with
  `scan_config={"prompt_cache_enabled": true, ...}` resolves to `config["prompt_cache_enabled"] is True`.
- **Sustained-`cache_read==0` alert (§10):** P5 logs metrics; a real alert on a
  sustained zero-hit rate (vs manual grep) is future ops work, not in this scope.
- **Gemini "inconclusive" caveat (§7):** Gemini may report `cache_read=0` even when
  caching fired (known langchain issue). Don't treat Gemini `cache_read==0` as proof
  of invalidation — note it in the logging code comment.
