"""Phase 2 — recent-signal skew query (spec FR-2.3/FR-2.6).

The DB round-trip needs a live pool, so we unit-test the PURE reduction helper
(_signal_skew_from_counts) that converts short/long counts into the skew dict.

NOTE: the SQL itself (ABS(score) >= min filter, score==0 exclusion, score-sign
classification, exclude_scan_id, ORDER BY completed_at DESC) is NOT covered here
because no local test DB is provisioned — it is validated manually against the
dev DB. The score-sign classification lives in get_recent_signal_skew().
"""
import os

import pytest

from backend.async_persistence import _signal_skew_from_counts


def test_skew_from_counts_basic():
    out = _signal_skew_from_counts(short=178, long=16, window=200)
    assert out["sample_n"] == 194
    assert out["short_pct"] == pytest.approx(178 / 194 * 100, abs=0.1)
    assert out["long_pct"] == pytest.approx(16 / 194 * 100, abs=0.1)
    assert out["window"] == 200


def test_skew_from_counts_empty():
    out = _signal_skew_from_counts(short=0, long=0, window=200)
    assert out["sample_n"] == 0
    assert out["short_pct"] == 0.0
    assert out["long_pct"] == 0.0


def test_skew_from_counts_all_short():
    out = _signal_skew_from_counts(short=50, long=0, window=200)
    assert out["short_pct"] == 100.0
    assert out["long_pct"] == 0.0
