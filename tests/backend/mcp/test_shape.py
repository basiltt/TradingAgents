"""Shape utility tests — TASK-P1 §K (summary/detail, keyset cursor, LTTB).

These are pure, deterministic helpers reused by every read tool so projection,
pagination, and equity-downsampling are implemented ONCE (no per-tool re-impl).
"""
from __future__ import annotations

import pytest

from backend.mcp.core.shape import (
    CursorError,
    decode_cursor,
    encode_cursor,
    lttb_downsample,
    project,
    paginate,
)


# --- projection ---

def test_project_summary_keeps_only_listed_fields():
    row = {"id": "1", "symbol": "BTC", "leverage": 10, "notes": "x" * 999}
    out = project(row, summary_fields=("id", "symbol"), detail=False)
    assert out == {"id": "1", "symbol": "BTC"}


def test_project_detail_returns_all_fields():
    row = {"id": "1", "symbol": "BTC", "leverage": 10}
    out = project(row, summary_fields=("id",), detail=True)
    assert out == row


def test_project_missing_summary_field_is_skipped():
    row = {"id": "1"}
    out = project(row, summary_fields=("id", "symbol"), detail=False)
    assert out == {"id": "1"}  # symbol absent → simply omitted, no crash


# --- keyset cursor (opaque + validated) ---

def test_cursor_round_trips():
    token = encode_cursor("created_at", "abc-123")
    sort_key, last_id = decode_cursor(token)
    assert (sort_key, last_id) == ("created_at", "abc-123")


def test_cursor_is_opaque_not_plaintext():
    token = encode_cursor("created_at", "abc-123")
    assert "created_at" not in token and "abc-123" not in token


def test_decode_rejects_garbage():
    with pytest.raises(CursorError):
        decode_cursor("not-a-valid-cursor!!!")


def test_decode_rejects_traversal_payload():
    # even a well-encoded cursor whose fields are malicious must validate shape
    bad = encode_cursor("../../etc", "x")
    with pytest.raises(CursorError):
        decode_cursor(bad)  # sort_key with path chars is rejected


# --- pagination ---

def test_paginate_caps_and_emits_next_cursor():
    rows = [{"id": str(i), "created_at": f"t{i:03d}"} for i in range(10)]
    page, next_cursor, truncated = paginate(rows, limit=5, sort_key="created_at", id_key="id")
    assert len(page) == 5
    assert truncated is True
    assert next_cursor is not None
    sort_key, last_id = decode_cursor(next_cursor)
    assert last_id == "4"  # last row of the returned page


def test_paginate_no_next_when_under_limit():
    rows = [{"id": "0", "created_at": "t0"}]
    page, next_cursor, truncated = paginate(rows, limit=5, sort_key="created_at", id_key="id")
    assert len(page) == 1 and next_cursor is None and truncated is False


# --- LTTB equity downsample ---

def test_lttb_caps_point_count():
    series = [(float(i), float(i) * 2) for i in range(5000)]
    out = lttb_downsample(series, threshold=1000)
    assert len(out) <= 1000


def test_lttb_keeps_endpoints():
    series = [(float(i), float(i)) for i in range(100)]
    out = lttb_downsample(series, threshold=20)
    assert out[0] == series[0] and out[-1] == series[-1]


def test_lttb_short_series_unchanged():
    series = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    assert lttb_downsample(series, threshold=1000) == series
