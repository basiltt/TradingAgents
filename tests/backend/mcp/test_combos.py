"""ComboGenerator tests — TASK-P4-01 (deterministic, deduped, capped)."""
from __future__ import annotations

import pytest

from backend.mcp.tools.optimizer.combos import (
    MAX_SWEEP_COMBOS,
    ComboGenerationError,
    config_hash,
    generate_combos,
)


def test_grid_count_equals_product():
    space = {"leverage": [5, 10], "take_profit_pct": [100.0, 150.0, 200.0]}
    combos = generate_combos(space, strategy="grid", base={"capital_pct": 5.0})
    assert len(combos) == 2 * 3
    # base fields carried into every combo
    assert all(c["capital_pct"] == 5.0 for c in combos)


def test_rejects_cooloff_fields_in_sweep_space():
    """Cool Off Time tiers are deny-from-sweep (risk pacing, stripped at apply time).
    Sweeping one would crown a winner whose edge came from a dimension that won't be
    applied → misleading uplift / empty diff. generate_combos must reject it up front."""
    with pytest.raises(ComboGenerationError, match="cool-off"):
        generate_combos({"leverage": [5, 10], "cooloff_on_failure_enabled": [True, False]}, strategy="grid")
    with pytest.raises(ComboGenerationError, match="cool-off"):
        generate_combos({"cooloff_on_success_minutes": [30, 60]}, strategy="grid")
    # Holding a cool-off field FIXED in base is fine (not swept).
    combos = generate_combos(
        {"leverage": [5, 10]}, strategy="grid",
        base={"cooloff_on_failure_enabled": True, "cooloff_on_failure_minutes": 60},
    )
    assert len(combos) == 2
    assert all(c["cooloff_on_failure_enabled"] is True for c in combos)


def test_grid_no_duplicates_and_deterministic():
    space = {"leverage": [5, 10, 20], "min_score": [0, 1]}
    a = generate_combos(space, strategy="grid")
    b = generate_combos(space, strategy="grid")
    hashes_a = [config_hash(c) for c in a]
    assert len(hashes_a) == len(set(hashes_a))  # zero dupes
    assert hashes_a == [config_hash(c) for c in b]  # deterministic order


def test_random_distinct_and_seed_reproducible():
    space = {"leverage": list(range(1, 21)), "take_profit_pct": [50.0, 100.0, 150.0, 200.0]}
    a = generate_combos(space, strategy="random", n=10, seed=42)
    b = generate_combos(space, strategy="random", n=10, seed=42)
    assert len(a) == 10
    assert {config_hash(c) for c in a} == {config_hash(c) for c in b}
    # distinct combos
    assert len({config_hash(c) for c in a}) == 10


def test_empty_space_rejected():
    with pytest.raises(ComboGenerationError):
        generate_combos({}, strategy="grid")


def test_combinatorial_explosion_rejected():
    # 6 params x 10 values = 1e6 > cap
    space = {f"p{i}": list(range(10)) for i in range(6)}
    with pytest.raises(ComboGenerationError):
        generate_combos(space, strategy="grid")


def test_single_point_space_yields_one():
    combos = generate_combos({"leverage": [10]}, strategy="grid")
    assert len(combos) == 1


def test_config_hash_canonical_order_independent():
    h1 = config_hash({"a": 1, "b": 2.0})
    h2 = config_hash({"b": 2.0, "a": 1})
    assert h1 == h2
    assert len(h1) == 64
