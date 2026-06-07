"""Token-budget estimator tests — P2 (context-budget awareness).

The operator UI must show how many model-context tokens each tool/group costs
so the user can enable only what fits the model's context window. The estimate
is a pure, deterministic function of the tool's MCP definition (name +
description + input JSON Schema) — the text the model actually receives.
"""
from __future__ import annotations

from pydantic import BaseModel

from backend.mcp.core.budget import (
    estimate_group_tokens,
    estimate_tool_tokens,
    estimate_total_tokens,
)
from backend.mcp.core.registry import SafetyClass, ToolGroup, ToolSpec


class _BigIn(BaseModel):
    symbol: str
    interval: str
    start: str
    end: str
    leverage: float
    take_profit_pct: float
    stop_loss_pct: float


class _SmallIn(BaseModel):
    pass


class _Out(BaseModel):
    ok: bool


def _spec(name: str, group: ToolGroup, schema: type[BaseModel], desc: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        group=group,
        handler=lambda **_: None,
        input_schema=schema,
        output_schema=_Out,
        safety_class=SafetyClass.READ_ONLY,
        mutating=False,
        exchange_facing=False,
        description=desc,
    )


def test_estimate_is_positive_and_deterministic():
    spec = _spec("scans_list", ToolGroup.SCANS, _SmallIn, "List recent scans.")
    a = estimate_tool_tokens(spec)
    b = estimate_tool_tokens(spec)
    assert a == b  # deterministic — no randomness, no clock
    assert a > 0


def test_richer_schema_costs_more_tokens():
    small = _spec("a_one", ToolGroup.SCANS, _SmallIn, "x")
    big = _spec("b_two", ToolGroup.BACKTEST, _BigIn,
                "Run a full backtest over a historical scan with many tunable knobs.")
    assert estimate_tool_tokens(big) > estimate_tool_tokens(small)


def test_longer_description_costs_more():
    short = _spec("c_one", ToolGroup.SCANS, _SmallIn, "List scans.")
    long = _spec("c_two", ToolGroup.SCANS, _SmallIn,
                 "List scans. " + ("detail " * 200))
    assert estimate_tool_tokens(long) > estimate_tool_tokens(short)


def test_total_is_sum_of_parts():
    specs = [
        _spec("d_one", ToolGroup.SCANS, _SmallIn, "one"),
        _spec("d_two", ToolGroup.BACKTEST, _BigIn, "two"),
    ]
    assert estimate_total_tokens(specs) == sum(estimate_tool_tokens(s) for s in specs)


def test_group_rollup_partitions_by_group():
    specs = [
        _spec("e_one", ToolGroup.SCANS, _SmallIn, "one"),
        _spec("e_two", ToolGroup.SCANS, _SmallIn, "two"),
        _spec("e_three", ToolGroup.BACKTEST, _BigIn, "three"),
    ]
    rollup = estimate_group_tokens(specs)
    assert rollup[ToolGroup.SCANS.value] == (
        estimate_tool_tokens(specs[0]) + estimate_tool_tokens(specs[1])
    )
    assert rollup[ToolGroup.BACKTEST.value] == estimate_tool_tokens(specs[2])


def test_empty_total_is_zero():
    assert estimate_total_tokens([]) == 0
    assert estimate_group_tokens([]) == {}
