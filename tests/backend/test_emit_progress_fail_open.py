"""Tests for AutoTradeExecutor._emit_progress fail-open + None-safety (P1R1)."""
from unittest.mock import MagicMock

from backend.services.auto_trade_service import AutoTradeExecutor


def _executor(progress=None, scan_id=None):
    return AutoTradeExecutor(MagicMock(), progress=progress, scan_id=scan_id)


def test_emit_progress_none_sink_is_noop():
    ex = _executor(progress=None, scan_id="s")
    # No sink -> no-op, no exception.
    assert ex._emit_progress("execute_batch", trades_executed=1) is None


def test_emit_progress_none_scan_id_is_noop():
    sink = MagicMock()
    ex = _executor(progress=sink, scan_id=None)
    ex._emit_progress("execute_batch")
    sink.emit.assert_not_called()


def test_emit_progress_forwards_fields():
    sink = MagicMock()
    ex = _executor(progress=sink, scan_id="scan-1")
    ex._emit_progress("fill_immediate", "lbl", symbol="BTCUSDT", side="buy")
    sink.emit.assert_called_once_with("scan-1", "fill_immediate", "lbl", symbol="BTCUSDT", side="buy")


def test_emit_progress_is_fail_open_on_raising_sink():
    """THE money-critical guarantee: a raising progress sink must NEVER raise into
    the executor (it would otherwise abort real-order placement)."""
    sink = MagicMock()
    sink.emit.side_effect = RuntimeError("boom")
    ex = _executor(progress=sink, scan_id="scan-1")
    # Must swallow the error and return None — placement continues.
    assert ex._emit_progress("execute_batch", trades_executed=1) is None
