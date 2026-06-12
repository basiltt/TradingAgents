"""ComboGenerator — TASK-P4-01.

Pure. Generates the parameter-sweep combination list (grid or seeded random)
from a search space + fixed base config. Each combo is canonical (sorted keys,
normalized numerics) with a stable config_hash. Refuses empty / oversized spaces
pre-flight.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import random
from typing import Any

MAX_SWEEP_COMBOS = 5000


class ComboGenerationError(ValueError):
    """Raised for an empty, invalid, or oversized search space."""


def _normalize(value: Any) -> Any:
    """Normalize numerics so 10 and 10.0 hash identically; pass through others."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # represent integers as int, floats via repr-stable rounding
        if float(value).is_integer():
            return int(value)
        return float(value)
    return value


def _canonical(config: dict[str, Any]) -> dict[str, Any]:
    return {k: _normalize(v) for k, v in sorted(config.items())}


def config_hash(config: dict[str, Any]) -> str:
    """Stable SHA-256 over the canonical config."""
    canon = _canonical(config)
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _grid_count(space: dict[str, list[Any]]) -> int:
    n = 1
    for values in space.values():
        n *= max(1, len(values))
    return n


def generate_combos(
    space: dict[str, list[Any]],
    *,
    strategy: str = "grid",
    base: dict[str, Any] | None = None,
    n: int = 100,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Generate the deduped, canonical combo list. Raises ComboGenerationError
    for empty/oversized spaces."""
    base = base or {}
    if not space or any(not vals for vals in space.values()):
        raise ComboGenerationError("search space is empty")

    # Reject deny-listed fields (e.g. Cool Off Time tiers) from the swept space. These
    # are risk config that apply/sanitize strips from any proposal, so sweeping them would
    # crown a winner whose edge came from a dimension that won't be applied — misleading
    # uplift, or an empty diff at apply time. Hold them constant in `base` instead.
    from backend.mcp.tools.optimizer.apply import COOLOFF_DENY_FIELDS
    denied = sorted(set(space.keys()) & COOLOFF_DENY_FIELDS)
    if denied:
        raise ComboGenerationError(
            f"cannot sweep non-optimizable cool-off fields: {', '.join(denied)} — "
            f"hold them fixed in the base config instead"
        )

    keys = sorted(space.keys())

    if strategy == "grid":
        total = _grid_count(space)
        if total > MAX_SWEEP_COMBOS:
            raise ComboGenerationError(
                f"grid would produce {total} combos (> cap {MAX_SWEEP_COMBOS}); "
                f"narrow the ranges or use random search"
            )
        combos: list[dict[str, Any]] = []
        seen: set[str] = set()
        for values in itertools.product(*(space[k] for k in keys)):
            cfg = dict(base)
            cfg.update(dict(zip(keys, values, strict=True)))
            cfg = _canonical(cfg)
            h = config_hash(cfg)
            if h in seen:
                continue
            seen.add(h)
            combos.append(cfg)
        return combos

    if strategy == "random":
        if n > MAX_SWEEP_COMBOS:
            raise ComboGenerationError(f"n={n} exceeds cap {MAX_SWEEP_COMBOS}")
        space_size = _grid_count(space)
        target = min(n, space_size)
        rng = random.Random(seed)
        combos = []
        seen = set()
        attempts = 0
        max_attempts = target * 50 + 100
        while len(combos) < target and attempts < max_attempts:
            attempts += 1
            cfg = dict(base)
            cfg.update({k: rng.choice(space[k]) for k in keys})
            cfg = _canonical(cfg)
            h = config_hash(cfg)
            if h in seen:
                continue
            seen.add(h)
            combos.append(cfg)
        # deterministic order for a given seed
        combos.sort(key=config_hash)
        return combos

    raise ComboGenerationError(f"unknown strategy {strategy!r}")
