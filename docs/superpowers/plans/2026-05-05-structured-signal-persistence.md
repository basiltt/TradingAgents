# Structured Signal Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate regex-based signal extraction in the scanner by saving PM and Trader Pydantic objects as structured JSON sections at graph completion time, giving the scanner a zero-parsing, contract-stable read path.

**Architecture:** `invoke_structured_or_freetext` is changed to return `(str, BaseModel | None)`. Agent nodes unpack the tuple, store the typed object in graph state, and `analysis_service._execute_graph` persists the JSON to `report_sections` as `_pm_signal` / `_trader_signal`. The scanner reads those keys first and falls back to regex only when they are absent (legacy runs).

**Tech Stack:** Python 3.11+, Pydantic v2, LangGraph, SQLite (via existing `AnalysisDB`), pytest

---

## File Map

| File | Change |
|------|--------|
| `tradingagents/agents/utils/structured.py` | Return `(str, BaseModel\|None)` instead of `str` |
| `tradingagents/agents/managers/portfolio_manager.py` | Unpack tuple; return `_pm_signal_data` |
| `tradingagents/agents/trader/trader.py` | Unpack tuple; return `_trader_signal_data` |
| `tradingagents/agents/managers/research_manager.py` | Unpack tuple; discard typed object |
| `tradingagents/agents/utils/agent_states.py` | Add `_pm_signal_data`, `_trader_signal_data` optional fields |
| `backend/services/analysis_service.py` | Persist `_pm_signal` / `_trader_signal` after stream ends |
| `backend/services/scanner_service.py` | Add `_rating_to_direction`, `_extract_signal_from_structured`; update `_collect_result` |
| `tests/test_structured_helpers.py` | New — unit tests for `invoke_structured_or_freetext` new return shape |
| `tests/test_scanner_signal_structured.py` | New — unit tests for new scanner extraction path |
| `tests/test_memory_log.py` | Update PM test to unpack new tuple return |

---

## Task 1: Change `invoke_structured_or_freetext` to return `(str, BaseModel | None)`

**Files:**
- Modify: `tradingagents/agents/utils/structured.py`
- Test: `tests/test_structured_helpers.py` (new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_structured_helpers.py`:

```python
"""Tests for invoke_structured_or_freetext return shape change."""
from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_or_freetext


class _Schema(BaseModel):
    value: str


def _render(obj: _Schema) -> str:
    return f"rendered:{obj.value}"


def test_structured_path_returns_tuple_with_object():
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = _Schema(value="hello")
    text, obj = invoke_structured_or_freetext(structured, llm, "prompt", _render, "Agent")
    assert text == "rendered:hello"
    assert isinstance(obj, _Schema)
    assert obj.value == "hello"


def test_freetext_fallback_returns_tuple_with_none():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="free text response")
    text, obj = invoke_structured_or_freetext(None, llm, "prompt", _render, "Agent")
    assert text == "free text response"
    assert obj is None


def test_structured_exception_falls_back_to_freetext():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="fallback text")
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("bad json")
    text, obj = invoke_structured_or_freetext(structured, llm, "prompt", _render, "Agent")
    assert text == "fallback text"
    assert obj is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_structured_helpers.py -v
```

Expected: 3 failures — `invoke_structured_or_freetext` currently returns `str`, not tuple.

- [ ] **Step 3: Update `invoke_structured_or_freetext`**

In `tradingagents/agents/utils/structured.py`, change the function signature and returns:

```python
from typing import Optional, Tuple
from pydantic import BaseModel

def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> Tuple[str, Optional[BaseModel]]:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    Returns (rendered_text, typed_object_or_none).
    The typed object is None on the free-text fallback path.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result), result
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content, None
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_structured_helpers.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add tradingagents/agents/utils/structured.py tests/test_structured_helpers.py
git commit -m "feat: invoke_structured_or_freetext returns (str, BaseModel|None) tuple"
```

---

## Task 2: Update callers of `invoke_structured_or_freetext` to unpack the tuple

**Files:**
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Modify: `tradingagents/agents/trader/trader.py`
- Modify: `tradingagents/agents/managers/research_manager.py`
- Modify: `tests/test_memory_log.py` (fix broken assertion)

- [ ] **Step 1: Confirm existing tests now fail due to tuple unpacking**

```
pytest tests/test_memory_log.py::TestPortfolioManagerInjection::test_pm_falls_back_to_freetext_when_structured_unavailable -v
```

Expected: FAIL — `result["final_trade_decision"]` is now a tuple `("...", None)` instead of a string.

- [ ] **Step 2: Update `portfolio_manager.py`**

In `tradingagents/agents/managers/portfolio_manager.py`, change the invocation line and the return:

```python
        final_trade_decision, decision_obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "_pm_signal_data": decision_obj,
        }
```

- [ ] **Step 3: Update `trader.py`**

In `tradingagents/agents/trader/trader.py`, change the invocation and return:

```python
        trader_plan, proposal_obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "_trader_signal_data": proposal_obj,
            "sender": name,
        }
```

- [ ] **Step 4: Update `research_manager.py`**

In `tradingagents/agents/managers/research_manager.py`, find the `invoke_structured_or_freetext` call and discard the typed object:

```python
        investment_plan, _ = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )
```

Everything else in the research_manager node stays the same.

- [ ] **Step 5: Fix the broken test in `tests/test_memory_log.py`**

Find `test_pm_falls_back_to_freetext_when_structured_unavailable` and update it:

```python
    def test_pm_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = "**Rating**: Sell\n\nExit ahead of guidance."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        pm_node = create_portfolio_manager(llm)
        result = pm_node(_make_pm_state())
        assert result["final_trade_decision"] == plain_response
        assert result["_pm_signal_data"] is None   # free-text path yields no object
```

- [ ] **Step 6: Run the full test suite to verify nothing broken**

```
pytest tests/ -q
```

Expected: all tests pass (same count as before).

- [ ] **Step 7: Commit**

```
git add tradingagents/agents/managers/portfolio_manager.py tradingagents/agents/trader/trader.py tradingagents/agents/managers/research_manager.py tests/test_memory_log.py
git commit -m "feat: agent nodes unpack structured output tuple and forward typed objects in state"
```

---

## Task 3: Add `_pm_signal_data` and `_trader_signal_data` to `AgentState`

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`

These fields carry the typed Pydantic objects through the LangGraph state so `_execute_graph` can read them from the final chunk. They are internal — never logged or rendered.

- [ ] **Step 1: Add fields to `AgentState`**

In `tradingagents/agents/utils/agent_states.py`, add two optional fields to the `AgentState` class after the existing `past_context` field:

```python
from typing import Annotated, Any, Optional
# (Any is needed for the typed objects — importing PortfolioDecision here
#  would create a circular import since schemas imports agent_utils)

class AgentState(MessagesState):
    # ... existing fields unchanged ...
    past_context: Annotated[str, "Memory log context injected at run start"]

    # Internal signal carriers — set by PM and Trader nodes, read by analysis_service.
    # Never written to logs, memory, or rendered markdown.
    _pm_signal_data: Annotated[Optional[Any], "PortfolioDecision object or None"]
    _trader_signal_data: Annotated[Optional[Any], "TraderProposal object or None"]
```

- [ ] **Step 2: Run the full test suite to confirm nothing broken**

```
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```
git add tradingagents/agents/utils/agent_states.py
git commit -m "feat: add _pm_signal_data and _trader_signal_data internal fields to AgentState"
```

---

## Task 4: Persist structured signal JSON from `analysis_service._execute_graph`

**Files:**
- Modify: `backend/services/analysis_service.py`

After the graph stream loop, read `_pm_signal_data` / `_trader_signal_data` from the last chunk and write them as `_pm_signal` / `_trader_signal` report sections.

- [ ] **Step 1: Write failing test**

In `tests/backend/test_analysis_service.py`, add:

```python
def test_execute_graph_persists_pm_signal_json(tmp_path):
    """When the last graph chunk contains _pm_signal_data, it is saved to report_sections."""
    from unittest.mock import MagicMock, patch
    from pydantic import BaseModel

    class FakePMDecision(BaseModel):
        rating: str = "Buy"
        confidence: int = 8

    fake_chunk = {"_pm_signal_data": FakePMDecision(), "_trader_signal_data": None}

    db = MagicMock()
    service = _make_analysis_service(db=db)

    with patch.object(service, "_execute_graph", return_value=fake_chunk):
        # Trigger the persistence logic directly (not via async run)
        service._persist_signal_sections("run-123", fake_chunk)

    calls = [str(c) for c in db.save_report_section.call_args_list]
    assert any("_pm_signal" in c for c in calls)
    saved_json = db.save_report_section.call_args_list[0][0][2]
    import json
    data = json.loads(saved_json)
    assert data["rating"] == "Buy"
    assert data["confidence"] == 8
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/backend/test_analysis_service.py::test_execute_graph_persists_pm_signal_json -v
```

Expected: FAIL — `_persist_signal_sections` does not exist yet.

- [ ] **Step 3: Add `_persist_signal_sections` helper and call it in `_execute_graph`**

In `backend/services/analysis_service.py`, add this method to `AnalysisService`:

```python
    def _persist_signal_sections(self, run_id: str, last_chunk: Optional[dict]) -> None:
        """Save _pm_signal and _trader_signal JSON sections from the final graph chunk."""
        if not last_chunk:
            return
        for key, section_name in (
            ("_pm_signal_data", "_pm_signal"),
            ("_trader_signal_data", "_trader_signal"),
        ):
            obj = last_chunk.get(key)
            if obj is None:
                continue
            try:
                if hasattr(obj, "model_dump_json"):
                    json_str = obj.model_dump_json()
                elif isinstance(obj, dict):
                    json_str = _json.dumps(obj)
                else:
                    continue
                self._db.save_report_section(run_id, section_name, json_str)
            except Exception:
                logger.warning(
                    "Failed to persist %s for run %s", section_name, run_id, exc_info=True
                )
```

Then in `_execute_graph`, after the stream loop, before returning `last_chunk`, add:

```python
        self._persist_signal_sections(run_id, last_chunk)
        return last_chunk
```

Note: `_execute_graph` runs in a thread (`asyncio.to_thread`), so `self._db.save_report_section` (a sync call) is safe here without `to_thread`.

- [ ] **Step 4: Run test to confirm it passes**

```
pytest tests/backend/test_analysis_service.py::test_execute_graph_persists_pm_signal_json -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add backend/services/analysis_service.py tests/backend/test_analysis_service.py
git commit -m "feat: persist _pm_signal and _trader_signal JSON sections after graph stream"
```

---

## Task 5: Add structured signal extraction functions to `scanner_service.py`

**Files:**
- Modify: `backend/services/scanner_service.py`
- Test: `tests/test_scanner_signal_structured.py` (new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scanner_signal_structured.py`:

```python
"""Unit tests for the structured signal extraction path in scanner_service."""
import pytest


def _extract(pm_data, trader_data=None):
    from backend.services.scanner_service import _extract_signal_from_structured
    return _extract_signal_from_structured(pm_data, trader_data or {})


def _direction(rating):
    from backend.services.scanner_service import _rating_to_direction
    return _rating_to_direction(rating)


class TestRatingToDirection:
    def test_buy(self):       assert _direction("Buy") == "buy"
    def test_overweight(self): assert _direction("Overweight") == "buy"
    def test_hold(self):      assert _direction("Hold") == "hold"
    def test_underweight(self): assert _direction("Underweight") == "sell"
    def test_sell(self):      assert _direction("Sell") == "sell"
    def test_unknown_defaults_to_hold(self): assert _direction("Unknown") == "hold"
    def test_case_insensitive(self): assert _direction("BUY") == "buy"


class TestExtractSignalFromStructured:
    def test_buy_high_confidence(self):
        result = _extract({"rating": "Buy", "confidence": 8})
        assert result["direction"] == "buy"
        assert result["confidence"] == "high"
        assert result["score"] == 8

    def test_sell_moderate_confidence(self):
        result = _extract({"rating": "Sell", "confidence": 5})
        assert result["direction"] == "sell"
        assert result["confidence"] == "moderate"
        assert result["score"] == -5

    def test_overweight_uses_buy(self):
        result = _extract({"rating": "Overweight", "confidence": 7})
        assert result["direction"] == "buy"
        assert result["score"] == 7

    def test_underweight_uses_sell(self):
        result = _extract({"rating": "Underweight", "confidence": 4})
        assert result["direction"] == "sell"
        assert result["score"] == -4

    def test_hold_always_zero(self):
        result = _extract({"rating": "Hold", "confidence": 9})
        assert result["direction"] == "hold"
        assert result["score"] == 0
        assert result["confidence"] == "none"

    def test_none_confidence_defaults_to_5(self):
        result = _extract({"rating": "Buy", "confidence": None})
        assert result["score"] == 5
        assert result["confidence"] == "moderate"

    def test_missing_confidence_falls_back_to_trader(self):
        result = _extract({"rating": "Buy"}, {"confidence": 9})
        assert result["score"] == 9
        assert result["confidence"] == "high"

    def test_confidence_clamped_at_10(self):
        result = _extract({"rating": "Buy", "confidence": 99})
        assert result["score"] == 10

    def test_confidence_clamped_at_1(self):
        result = _extract({"rating": "Sell", "confidence": -5})
        assert result["score"] == -1

    def test_low_confidence_label(self):
        result = _extract({"rating": "Buy", "confidence": 2})
        assert result["confidence"] == "low"
        assert result["score"] == 2

    def test_empty_pm_data_defaults_hold(self):
        result = _extract({})
        assert result["direction"] == "hold"
        assert result["score"] == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_scanner_signal_structured.py -v
```

Expected: failures — `_extract_signal_from_structured` and `_rating_to_direction` don't exist yet.

- [ ] **Step 3: Add `_rating_to_direction` and `_extract_signal_from_structured` to `scanner_service.py`**

Add these two functions immediately before `_parse_signal_from_reports` in `backend/services/scanner_service.py`:

```python
def _rating_to_direction(rating: str) -> str:
    """Map 5-tier PortfolioRating string to 3-tier scanner direction."""
    r = rating.lower().strip()
    if r in ("buy", "overweight"):
        return "buy"
    if r in ("sell", "underweight"):
        return "sell"
    return "hold"


def _extract_signal_from_structured(
    pm_data: Dict[str, Any],
    trader_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a validated signal dict from pre-parsed structured agent output.

    pm_data: dict from PortfolioDecision.model_dump() — keys: rating, confidence, ...
    trader_data: dict from TraderProposal.model_dump() — keys: action, confidence, ...
    """
    rating = str(pm_data.get("rating") or "Hold")
    direction = _rating_to_direction(rating)

    if direction == "hold":
        return {"direction": "hold", "confidence": "none", "score": 0}

    # PM confidence is authoritative; fall back to trader's if absent
    conf_score = pm_data.get("confidence") or trader_data.get("confidence")
    if conf_score is None:
        conf_score = 5  # neutral default when direction is known but conviction isn't
    conf_score = max(1, min(10, int(conf_score)))

    if conf_score >= 7:
        confidence = "high"
    elif conf_score >= 4:
        confidence = "moderate"
    else:
        confidence = "low"

    sign = 1 if direction == "buy" else -1
    score = sign * conf_score

    return {"direction": direction, "confidence": confidence, "score": score}
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_scanner_signal_structured.py -v
```

Expected: all 18 tests pass.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add backend/services/scanner_service.py tests/test_scanner_signal_structured.py
git commit -m "feat: add _rating_to_direction and _extract_signal_from_structured to scanner"
```

---

## Task 6: Wire structured path into `_collect_result` in `scanner_service.py`

**Files:**
- Modify: `backend/services/scanner_service.py`
- Test: `tests/test_scanner_signal_structured.py` (extend)

- [ ] **Step 1: Write failing integration tests for `_collect_result` structured path**

Add to `tests/test_scanner_signal_structured.py`:

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock


def _make_scanner(snapshot_reports):
    """Return a ScannerService with a mocked analysis service that yields the given reports."""
    from backend.services.scanner_service import ScannerService

    analysis = MagicMock()
    analysis.get_snapshot = AsyncMock(return_value={"reports": snapshot_reports})
    analysis.get_run = AsyncMock(return_value={"status": "completed"})
    scanner = ScannerService(analysis_service=analysis, db=None)
    scanner._scans["scan-1"] = {
        "status": "running", "completed": 0, "failed": 0, "results": [], "cancel": False
    }
    return scanner


class TestCollectResultStructuredPath:
    def test_uses_pm_signal_json_when_present(self):
        pm_json = json.dumps({"rating": "Buy", "confidence": 8})
        trader_json = json.dumps({"action": "Buy", "confidence": 7})
        scanner = _make_scanner({
            "_pm_signal": pm_json,
            "_trader_signal": trader_json,
            "portfolio_manager": "some markdown that would confuse the regex",
        })
        run = {"status": "completed"}
        asyncio.get_event_loop().run_until_complete(
            scanner._collect_result("scan-1", "BTCUSDT", "run-99", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert len(results) == 1
        r = results[0]
        assert r["direction"] == "buy"
        assert r["confidence"] == "high"
        assert r["score"] == 8
        assert r["signal_source"] == "structured"

    def test_falls_back_to_regex_when_no_pm_signal_key(self):
        scanner = _make_scanner({
            "portfolio_manager": "Final decision: APPROVE. We go long. Confidence: 7/10.",
        })
        run = {"status": "completed"}
        asyncio.get_event_loop().run_until_complete(
            scanner._collect_result("scan-1", "ETHUSDT", "run-100", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert len(results) == 1
        r = results[0]
        assert r["direction"] == "buy"
        assert r["signal_source"] == "regex_fallback"

    def test_failed_run_returns_hold_regardless(self):
        pm_json = json.dumps({"rating": "Buy", "confidence": 9})
        scanner = _make_scanner({"_pm_signal": pm_json})
        run = {"status": "failed"}
        asyncio.get_event_loop().run_until_complete(
            scanner._collect_result("scan-1", "SOLUSDT", "run-101", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert results[0]["direction"] == "hold"
        assert results[0]["score"] == 0
        assert results[0]["signal_source"] == "none"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
pytest tests/test_scanner_signal_structured.py::TestCollectResultStructuredPath -v
```

Expected: failures — `_collect_result` doesn't yet use the structured path.

- [ ] **Step 3: Update `_collect_result` in `scanner_service.py`**

Replace the signal resolution block inside `_collect_result` (currently the `if status == "completed" and reports:` block) with:

```python
        if status == "completed" and reports:
            pm_json = reports.get("_pm_signal")
            trader_json = reports.get("_trader_signal")

            if pm_json:
                try:
                    pm_data = _json.loads(pm_json)
                    trader_data = _json.loads(trader_json) if trader_json else {}
                    signal = _extract_signal_from_structured(pm_data, trader_data)
                    signal_source = "structured"
                except Exception:
                    logger.exception(
                        "Failed to parse structured signal JSON for %s/%s — falling back",
                        scan_id, run_id,
                    )
                    signal = _parse_signal_from_reports(reports)
                    signal_source = "regex_fallback"
            else:
                signal = _parse_signal_from_reports(reports)
                signal_source = "regex_fallback"
        else:
            signal = {"direction": "hold", "confidence": "none", "score": 0}
            signal_source = "none"
```

Also update the `result` dict construction to use the local `signal_source` variable instead of the existing inline expression:

```python
        result = {
            "ticker": ticker,
            "run_id": run_id,
            "status": status,
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "decision_summary": decision_text[:500] if decision_text else "",
            "signal_source": signal_source,
        }
```

- [ ] **Step 4: Run new tests to confirm they pass**

```
pytest tests/test_scanner_signal_structured.py -v
```

Expected: all tests pass (both new and existing).

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```
git add backend/services/scanner_service.py tests/test_scanner_signal_structured.py
git commit -m "feat: scanner reads _pm_signal JSON first, falls back to regex for legacy runs"
```

---

## Task 7: Verify end-to-end with a real scan run (manual smoke test)

This task has no automated test — it validates the full pipeline with a live model call.

- [ ] **Step 1: Start the backend**

```
cd backend && python -m uvicorn main:app --reload
```

- [ ] **Step 2: Trigger a single-symbol scan via the API**

```
curl -X POST http://localhost:8000/scanner \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-05-05", "asset_type": "crypto", "interval": "D"}'
```

Note the `scan_id` from the response.

- [ ] **Step 3: Poll until the first result is completed**

```
curl http://localhost:8000/scanner/<scan_id>
```

- [ ] **Step 4: Confirm `signal_source == "structured"` in the result**

In the response JSON, check `results[0].signal_source`. It should be `"structured"` for any run that used a provider supporting `with_structured_output` (OpenAI, Anthropic, Google).

- [ ] **Step 5: Open the Analysis Report for that ticker**

Click "View" in the scanner UI. Confirm the report still renders correctly — the `portfolio_manager` markdown section should be unchanged.

- [ ] **Step 6: Commit any fixes found during smoke test**

```
git add <changed files>
git commit -m "fix: <description of smoke test fix>"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task covering it |
|-----------------|-----------------|
| `invoke_structured_or_freetext` returns `(str, BaseModel\|None)` | Task 1 |
| PM node returns `_pm_signal_data` | Task 2 |
| Trader node returns `_trader_signal_data` | Task 2 |
| Research Manager discards typed object | Task 2 |
| `AgentState` has new optional fields | Task 3 |
| `analysis_service` persists `_pm_signal` / `_trader_signal` sections | Task 4 |
| `_rating_to_direction` with 5-tier mapping | Task 5 |
| `_extract_signal_from_structured` with confidence fallback | Task 5 |
| `_collect_result` reads structured path first | Task 6 |
| Regex fallback when `_pm_signal` absent | Task 6 |
| `signal_source = "structured"` for new runs | Task 6 |
| `signal_source = "regex_fallback"` for legacy | Task 6 |
| Crypto PM: free-text path falls back naturally | No code change needed — covered by fallback |
| `_log_state` unchanged | Verified in Task 3 — new fields not written there |

All spec requirements covered.

### Type consistency check

- `invoke_structured_or_freetext` → `Tuple[str, Optional[BaseModel]]` — used consistently in Tasks 1, 2.
- `_pm_signal_data` field name used in Tasks 2, 3, 4 — consistent.
- `_trader_signal_data` field name used in Tasks 2, 3, 4 — consistent.
- `_pm_signal` section name (DB key) used in Tasks 4, 5, 6 — consistent.
- `_trader_signal` section name used in Tasks 4, 5, 6 — consistent.
- `_rating_to_direction` and `_extract_signal_from_structured` defined in Task 5, called in Task 6 — consistent.
