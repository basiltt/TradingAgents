"""Sweep window date coercion — shared by sweep_run and optimize_config.

The optimizer tools accept the backtest window as ISO-8601 STRINGS (the agent
sends JSON, which has no datetime type). `BacktestService.load_inputs` binds
those values straight into asyncpg `timestamptz` query params, and asyncpg
rejects a `str` for a `timestamptz` bind:

    invalid input for query argument $2: '2026-06-04T18:30:00Z'
    (expected datetime, got str)

So the strings MUST be coerced to tz-aware `datetime`s before `load_inputs`.
This mirrors how `backtest_run` works for free: its input schema declares the
fields as `datetime`, so Pydantic coerces them. The async optimizer tools keep
the fields as `str` (the window is optional / paired with `scan_source`), so
they coerce explicitly here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_window_dt(value: Any, *, field: str) -> datetime:
    """Coerce an ISO-8601 string (or passthrough datetime) to a tz-aware UTC datetime.

    Accepts a trailing 'Z' (mapped to +00:00). A naive datetime/string is assumed
    UTC and stamped accordingly so every downstream comparison is tz-aware.

    Raises ValueError with the field name on anything unparseable so the tool can
    surface a clean validation error instead of a deep asyncpg bind failure.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} is empty")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not a valid ISO-8601 datetime: {value!r}") from exc
    else:
        raise ValueError(f"{field} must be an ISO-8601 string or datetime, got {type(value).__name__}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
