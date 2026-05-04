# Structured Signal Persistence — Design Spec

**Date:** 2026-05-05  
**Status:** Approved  
**Scope:** New runs only (existing completed runs retain the regex fallback path)

---

## Problem

The scanner's signal extraction pipeline is broken by a contract mismatch between layers:

1. The PM and Trader agents produce typed Pydantic objects (`PortfolioDecision`, `TraderProposal`).
2. `invoke_structured_or_freetext` renders them to markdown strings and discards the typed objects.
3. The scanner reconstructs the signal from that markdown using regex — a lossy, fragile reversal.
4. The PM's rendered format (`**Rating**: Buy`) does not match the scanner's regex (`Final Decision: APPROVE`), so `pm_signal` is always `None` for structured-output runs, causing nearly every completed signal to be suppressed.

**Root cause:** The graph/scanner boundary has no contract. Signal data crosses it as unstructured markdown, and the reconstruction is not stable across schema changes.

---

## Solution Overview

Intercept the typed Pydantic objects before they are rendered and save them as a separate `_pm_signal` / `_trader_signal` JSON section in the DB alongside the existing markdown sections. The scanner reads structured JSON directly — no parsing, no regex, no format coupling.

```
Agent Layer
  portfolio_manager_node
    PortfolioDecision  ──► render_pm_decision() ──► "portfolio_manager" section (MD, unchanged)
                       ──► .model_dump()        ──► "_pm_signal" section (JSON, NEW)
  trader_node
    TraderProposal     ──► render_trader_proposal() ──► "trader" section (MD, unchanged)
                       ──► .model_dump()            ──► "_trader_signal" section (JSON, NEW)

Persistence Layer
  report_sections table
    section="_pm_signal"     content='{"rating":"Buy","confidence":7,...}'
    section="_trader_signal"  content='{"action":"Buy","confidence":8,...}'

Scanner Layer
  _collect_result()
    reads reports["_pm_signal"] → _extract_signal_from_structured() → signal dict
    falls back to existing regex path when "_pm_signal" absent (old runs)
```

---

## Layer 1 — Agent Layer

### `tradingagents/agents/utils/structured.py`

Change `invoke_structured_or_freetext` to return `tuple[str, BaseModel | None]`:

```python
def invoke_structured_or_freetext(
    structured_llm, plain_llm, prompt, render, agent_name
) -> tuple[str, BaseModel | None]:
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result), result          # (markdown, typed object)
        except Exception as exc:
            logger.warning(...)
    response = plain_llm.invoke(prompt)
    return response.content, None                  # (freetext, no typed object)
```

All three callers (Trader, Portfolio Manager, Research Manager) must be updated to unpack the tuple. Only Trader and PM pass their typed object downstream; Research Manager discards it (its output is prose context for the Trader, not a signal).

### `tradingagents/agents/managers/portfolio_manager.py`

```python
text, decision_obj = invoke_structured_or_freetext(...)
return {
    "final_trade_decision": text,
    "_pm_signal_data": decision_obj,   # None on free-text fallback
    ...
}
```

### `tradingagents/agents/trader/trader.py`

```python
text, proposal_obj = invoke_structured_or_freetext(...)
return {
    "trader_investment_plan": text,
    "_trader_signal_data": proposal_obj,
    ...
}
```

### `tradingagents/agents/utils/agent_states.py`

Add two optional fields to `AgentState`:

```python
_pm_signal_data: Annotated[Optional[Any], "Structured PM decision object (internal, not logged)"]
_trader_signal_data: Annotated[Optional[Any], "Structured trader proposal object (internal, not logged)"]
```

These fields are internal pipeline carriers only. They must not appear in:
- `_log_state()` output JSON
- memory log storage
- any rendered markdown reports

### Research Manager caller

`invoke_structured_or_freetext` is also called in the Research Manager. Update it to unpack the tuple but discard the typed object — its output is prose context only, not a signal:

```python
text, _ = invoke_structured_or_freetext(...)
```

---

## Layer 2 — Backend Service Layer

### `backend/services/analysis_service._execute_graph`

After the graph stream loop ends, check the last chunk for signal data and persist it:

```python
if last_chunk:
    pm_obj = last_chunk.get("_pm_signal_data")
    trader_obj = last_chunk.get("_trader_signal_data")

    if pm_obj is not None:
        try:
            pm_json = pm_obj.model_dump_json()
        except Exception:
            pm_json = json.dumps(pm_obj) if isinstance(pm_obj, dict) else None
        if pm_json:
            self._db.save_report_section(run_id, "_pm_signal", pm_json)

    if trader_obj is not None:
        try:
            trader_json = trader_obj.model_dump_json()
        except Exception:
            trader_json = json.dumps(trader_obj) if isinstance(trader_obj, dict) else None
        if trader_json:
            self._db.save_report_section(run_id, "_trader_signal", trader_json)
```

This keeps signal persistence in the backend layer. The graph core does not import or reference anything from `backend/`.

---

## Layer 3 — Scanner Layer

### `backend/services/scanner_service.py`

#### New function: `_extract_signal_from_structured`

```python
def _extract_signal_from_structured(
    pm_data: dict,
    trader_data: dict,
) -> dict:
    """
    Build a signal dict from pre-parsed structured agent output.
    pm_data keys: rating (str), confidence (int|None), ...
    trader_data keys: action (str), confidence (int|None), ...
    """
    rating = (pm_data.get("rating") or "Hold").strip()
    direction = _rating_to_direction(rating)

    # PM confidence first; fall back to trader's
    conf_score = pm_data.get("confidence") or trader_data.get("confidence")

    if direction == "hold":
        return {"direction": "hold", "confidence": "none", "score": 0}

    if conf_score is None:
        conf_score = 5
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


def _rating_to_direction(rating: str) -> str:
    """Map 5-tier PortfolioRating to 3-tier scanner direction."""
    r = rating.lower()
    if r in ("buy", "overweight"):
        return "buy"
    if r in ("sell", "underweight"):
        return "sell"
    return "hold"
```

#### Updated `_collect_result`

```python
# Priority 1: structured JSON sections (new runs)
pm_json = reports.get("_pm_signal")
trader_json = reports.get("_trader_signal")

if pm_json:
    try:
        pm_data = json.loads(pm_json)
        trader_data = json.loads(trader_json) if trader_json else {}
        signal = _extract_signal_from_structured(pm_data, trader_data)
        signal_source = "structured"
    except Exception:
        logger.exception("Failed to parse structured signal JSON — falling back")
        signal = _parse_signal_from_reports(reports)   # regex fallback
        signal_source = "regex_fallback"
else:
    # Priority 2: regex fallback for old/free-text runs
    signal = _parse_signal_from_reports(reports)
    signal_source = "regex_fallback" if (reports.get("portfolio_manager") or reports.get("trader")) else "none"
```

The `signal_source` field (already in the DB schema) will show `"structured"` for new runs and `"regex_fallback"` for legacy runs — making it easy to monitor transition progress and eventual regex path deprecation.

---

## Rating → Direction Mapping

This mapping is the authoritative contract between the PM's 5-tier rating and the scanner's 3-tier signal:

| PortfolioRating | Direction |
|----------------|-----------|
| Buy            | buy       |
| Overweight     | buy       |
| Hold           | hold      |
| Underweight    | sell      |
| Sell           | sell      |

Rationale: Overweight and Underweight are partial-position signals. Mapping them to buy/sell respectively is the conservative-side interpretation — the scanner surfaces them as actionable rather than neutral, consistent with their intent.

---

## What Does NOT Change

- Markdown rendering pipeline — `render_pm_decision`, `render_trader_proposal` are unchanged.
- Report storage — `"portfolio_manager"`, `"trader"`, `"final_trade_decision"` sections are unchanged.
- Memory log — `store_decision` reads `final_trade_decision` (markdown), unchanged.
- CLI display — reads markdown sections, unchanged.
- `_log_state` file output — unchanged.
- The existing regex signal extraction path — kept as fallback, not removed.
- DB schema — `_pm_signal` / `_trader_signal` are stored as regular `report_sections` rows, no migration needed.

---

## Crypto Agent Consideration

`create_crypto_portfolio_manager` in `tradingagents/agents/crypto_analysts.py` is **free-text only** — it calls `llm.invoke` directly, not `invoke_structured_or_freetext`, and produces the old `approve/modify/reject` narrative format.

Two-part fix:

1. **Migrate it to structured output** — bind `PortfolioDecision` via `bind_structured` / `invoke_structured_or_freetext`, same as the stock PM. The prompt already asks for an approve/modify/reject decision; the Pydantic schema replaces that with the 5-tier `PortfolioRating`. This is the cleanest path and ensures the crypto scanner also benefits from the structured pipeline.

2. **If structured output for crypto is deferred** — the existing regex path (`_extract_pm_signal`) correctly handles the `Final Decision: APPROVE/REJECT/MODIFY` format that the free-text crypto PM emits. Since it produces no `_pm_signal` section, `_collect_result` will fall through to the regex fallback automatically — no special-casing needed. Signal quality for crypto runs will remain at its current level until the crypto PM is migrated.

The spec covers both cases. Migrating the crypto PM to structured output is recommended but can be done as a follow-on task.

---

## Testing Plan

1. **Unit tests** — `_rating_to_direction`, `_extract_signal_from_structured` with all 5 ratings, edge cases (None confidence, unknown rating string).
2. **Integration test** — mock a completed run with `_pm_signal` and `_trader_signal` sections in the snapshot; assert `_collect_result` produces the correct direction/confidence/score without calling the regex path.
3. **Regression test** — run the scanner against a snapshot with no `_pm_signal` key (old-run simulation); assert it falls back to the regex path and produces a valid signal.
4. **signal_source assertion** — verify `signal_source == "structured"` for new runs and `"regex_fallback"` or `"none"` for legacy runs.

---

## Migration / Rollout

- Old completed runs in the DB will never have `_pm_signal` sections → scanner falls back to regex path for them (unchanged behaviour).
- New runs after this change lands will always have `_pm_signal` → scanner uses structured path.
- No DB migration required.
- No feature flag required.
