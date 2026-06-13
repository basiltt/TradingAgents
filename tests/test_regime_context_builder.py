"""Phase 1 — pure regime-context builder (spec FR-1, AC-2/AC-6).

TDD: these tests are written BEFORE the module exists (RED).
The module under test must import ONLY stdlib (no backend.*, no market_data).
"""
import ast
import os

import pytest

from tradingagents.agents.utils import regime_context as rc


# ── T1.1 EMA parity with the original (import original INSIDE test only) ──
def test_ema_parity_with_market_data():
    from backend.services.market_data import ema as orig_ema
    closes = [100, 101, 102, 99, 98, 103, 105, 104, 106, 107, 108, 110, 109, 111, 112]
    assert rc._ema(closes, 14) == pytest.approx(orig_ema(closes, 14))


def test_ema_distance_parity():
    from backend.services.market_data import ema as orig_ema
    closes = [100, 101, 102, 99, 98, 103, 105, 104, 106, 107, 108, 110, 109, 111, 112]
    e = orig_ema(closes, 14)
    expected = (closes[-1] - e) / e * 100.0
    assert rc._ema_distance_pct(closes, 14) == pytest.approx(expected)


# ── T1.2 btc_scalars_from_closes ──
def test_scalars_rising():
    closes = [100 + i for i in range(20)]  # strictly rising
    trend, move = rc.btc_scalars_from_closes(closes, period=14)
    assert trend is not None and trend > 0
    assert move == pytest.approx((closes[-1] - closes[0]) / closes[0] * 100.0)


def test_scalars_falling():
    closes = [200 - i for i in range(20)]
    trend, move = rc.btc_scalars_from_closes(closes, period=14)
    assert trend is not None and trend < 0
    assert move < 0


def test_scalars_short_series_returns_none_trend():
    closes = [100, 101, 102]  # shorter than period
    trend, move = rc.btc_scalars_from_closes(closes, period=14)
    assert trend is None


def test_scalars_zero_first_close_move_none():
    closes = [0.0] + [1.0] * 20
    trend, move = rc.btc_scalars_from_closes(closes, period=14)
    assert move is None  # guard div-by-zero


# ── closes_from_kline_csv (Bybit CSV parsing, newest-first -> sorted asc) ──
def test_csv_parser_sorts_oldest_to_newest():
    # Bybit returns newest-first; parser must sort ascending by timestamp.
    csv = "timestamp,open,high,low,close,volume\n"
    csv += "3000,1,1,1,300,9\n2000,1,1,1,200,9\n1000,1,1,1,100,9"
    closes = rc.closes_from_kline_csv(csv)
    assert closes == [100.0, 200.0, 300.0]  # oldest -> newest


def test_csv_parser_skips_warning_banner_and_header():
    csv = "[WARNING: Data truncated]\ntimestamp,open,high,low,close,volume\n1000,1,1,1,100,9"
    assert rc.closes_from_kline_csv(csv) == [100.0]


def test_csv_parser_empty_and_malformed():
    assert rc.closes_from_kline_csv("") == []
    assert rc.closes_from_kline_csv("garbage\nno,commas") == []
    # a malformed row is skipped, valid rows kept
    csv = "timestamp,open,high,low,close,volume\nbad,row\n1000,1,1,1,100,9"
    assert rc.closes_from_kline_csv(csv) == [100.0]


def test_csv_parser_rejects_nan_inf():
    csv = "timestamp,open,high,low,close,volume\n1000,1,1,1,nan,9\n2000,1,1,1,inf,9\n3000,1,1,1,100,9"
    assert rc.closes_from_kline_csv(csv) == [100.0]  # nan/inf rows dropped


# ── T1.3 direction mapping ──
def test_direction_rising():
    out = rc.build_regime_context_block(1.5, 3.0, None)
    assert "rising" in out.lower() and "long" in out.lower()


def test_direction_falling():
    out = rc.build_regime_context_block(-1.5, -3.0, None)
    assert "falling" in out.lower() and "short" in out.lower()


def test_direction_flat():
    out = rc.build_regime_context_block(0.3, 0.3, None)
    assert "flat" in out.lower()


# ── T1.4 skew line ──
def test_skew_line_present_when_sample_sufficient():
    skew = {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    out = rc.build_regime_context_block(0.3, 0.3, skew)
    assert "89" in out and "SHORT" in out.upper()


def test_skew_line_absent_below_min_sample():
    skew = {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 19, "window": 200}
    out = rc.build_regime_context_block(0.3, 0.3, skew)
    assert "89" not in out


def test_skew_line_absent_zero_sample():
    skew = {"short_pct": 0.0, "long_pct": 0.0, "sample_n": 0, "window": 200}
    out = rc.build_regime_context_block(0.3, 0.3, skew)
    assert "book" not in out.lower()


# ── T1.5 conflict warning ──
def test_conflict_warning_rising_plus_short_book():
    skew = {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    out = rc.build_regime_context_block(1.5, 3.0, skew)
    # Assert on the explicit WARNING line, NOT "squeeze" (the base rising line
    # also contains "squeeze", which would make this a tautology).
    assert "WARNING:" in out and "short-heavy" in out.lower()


def test_no_conflict_warning_when_flat():
    skew = {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    out = rc.build_regime_context_block(0.3, 0.3, skew)
    assert "WARNING:" not in out


def test_no_squeeze_warning_when_falling_with_short_book():
    skew = {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    out = rc.build_regime_context_block(-1.5, -3.0, skew)
    assert "WARNING:" not in out


# ── T1.6 empty / formatting ──
def test_empty_inputs_return_empty_string():
    assert rc.build_regime_context_block(None, None, None) == ""


def test_nonempty_block_ends_with_double_newline():
    out = rc.build_regime_context_block(1.5, 3.0, None)
    assert out.endswith("\n\n")


# ── T1.7 import-guard via AST (AC-6) ──
def test_module_imports_only_stdlib():
    src_path = rc.__file__
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    forbidden = ("backend", "scan_context", "market_data", "safety_monitors", "kill_switch")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not any(f in n.name for f in forbidden), f"forbidden import {n.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(f in mod for f in forbidden), f"forbidden import-from {mod}"
