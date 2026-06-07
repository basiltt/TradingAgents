"""Shape utilities — projection, keyset pagination, equity downsampling (core).

Pure, deterministic, trading-free. Reused by every read tool so the agent-facing
output contract (compact summary by default, opaque keyset cursors, bounded
equity series) is implemented ONCE. No clock, no randomness — safe under the
core import-linter contract and trivially testable.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Iterable, Optional

# A sort key is an identifier-like token (column name). Reject anything with path
# or injection characters so a forged cursor can't smuggle a traversal/expression.
_SORT_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")


class CursorError(Exception):
    """Raised when a pagination cursor is malformed or fails validation."""


def project(
    row: dict[str, Any], *, summary_fields: Iterable[str], detail: bool
) -> dict[str, Any]:
    """Return the full row when detail=True, else only the summary fields present.

    Missing summary fields are omitted (never raise) so a tool can list a
    superset of fields without crashing on sparse rows.
    """
    if detail:
        return dict(row)
    return {k: row[k] for k in summary_fields if k in row}


def encode_cursor(sort_key: str, last_id: str) -> str:
    """Opaque, URL-safe base64 cursor over (sort_key, last_id)."""
    raw = json.dumps({"k": sort_key, "i": last_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(token: str) -> tuple[str, str]:
    """Decode + VALIDATE an opaque cursor. Raises CursorError on any problem.

    Validates the sort key against an identifier allow-list so a tampered cursor
    cannot inject a path or expression where the caller interpolates the key.
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        obj = json.loads(raw)
        sort_key = obj["k"]
        last_id = obj["i"]
    except Exception as exc:  # noqa: BLE001 — any decode failure is a bad cursor
        raise CursorError("malformed cursor") from exc
    if not isinstance(sort_key, str) or not _SORT_KEY_RE.match(sort_key):
        raise CursorError("invalid cursor sort key")
    if not isinstance(last_id, str) or len(last_id) > 128:
        raise CursorError("invalid cursor id")
    return sort_key, last_id


def paginate(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    sort_key: str,
    id_key: str = "id",
) -> tuple[list[dict[str, Any]], Optional[str], bool]:
    """Cap a result set to `limit` rows and emit a next-cursor when truncated.

    Returns (page, next_cursor, truncated). The cursor encodes the sort key and
    the last returned row's id, for the caller to resume from. Pure: it does not
    re-query; it shapes an already-fetched (limit+1-friendly) list.
    """
    if limit < 1:
        limit = 1
    truncated = len(rows) > limit
    page = rows[:limit]
    next_cursor: Optional[str] = None
    if truncated and page:
        last = page[-1]
        last_id = str(last.get(id_key, ""))
        if last_id:
            next_cursor = encode_cursor(sort_key, last_id)
    return page, next_cursor, truncated


def lttb_downsample(
    series: list[tuple[float, float]], *, threshold: int = 1000
) -> list[tuple[float, float]]:
    """Largest-Triangle-Three-Buckets downsampling of an (x, y) series.

    Reduces a long equity/drawdown curve to at most `threshold` points while
    preserving visual shape (peaks/troughs) and the exact endpoints. Returns the
    series unchanged when it already fits. Deterministic.
    """
    n = len(series)
    if threshold >= n or threshold < 3:
        return list(series)

    sampled: list[tuple[float, float]] = [series[0]]
    # bucket size for the n-2 interior points across threshold-2 buckets
    every = (n - 2) / (threshold - 2)
    a = 0  # index of the last selected point
    for i in range(threshold - 2):
        # next bucket's average point (for the triangle's third vertex)
        avg_start = int((i + 1) * every) + 1
        avg_end = int((i + 2) * every) + 1
        avg_end = min(avg_end, n)
        avg_x = avg_y = 0.0
        avg_count = max(avg_end - avg_start, 1)
        for j in range(avg_start, avg_start + avg_count):
            jj = min(j, n - 1)
            avg_x += series[jj][0]
            avg_y += series[jj][1]
        avg_x /= avg_count
        avg_y /= avg_count

        # current bucket range to pick the point with the largest triangle area
        range_start = int(i * every) + 1
        range_end = int((i + 1) * every) + 1
        ax, ay = series[a]
        max_area = -1.0
        chosen = range_start
        for j in range(range_start, min(range_end, n)):
            bx, by = series[j]
            area = abs((ax - avg_x) * (by - ay) - (ax - bx) * (avg_y - ay)) * 0.5
            if area > max_area:
                max_area = area
                chosen = j
        sampled.append(series[chosen])
        a = chosen

    sampled.append(series[-1])
    return sampled
