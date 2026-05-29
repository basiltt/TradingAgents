"""Tests for SignalPerformanceMaterializer and its pure helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.signal_performance_service import (
    SignalPerformanceMaterializer,
    _score_to_tier,
    compute_random_expected_pnl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> dict:
    """Return a minimal valid closed-trade dict."""
    base = {
        "id": "trade-uuid-1",
        "account_id": "acc-1",
        "symbol": "BTCUSDT",
        "signal_direction": "buy",
        "entry_price": 50000.0,
        "exit_price": 51000.0,
        "opened_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        "closed_at": datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
        "net_pnl": 50.0,
        "fees": 2.0,
        "close_reason": "take_profit",
        "take_profit_pct": 3.0,
        "stop_loss_pct": 1.5,
        "scan_result_id": 42,
    }
    base.update(overrides)
    return base


def _make_db(scan_row=None, regime_row=None) -> AsyncMock:
    """Return a mock db object whose pool.fetchrow returns scan then regime."""
    mock_db = AsyncMock()
    mock_db.pool = AsyncMock()

    # asyncpg rows are mapping-like; MagicMock supports __getitem__
    def _row(data: dict | None) -> MagicMock | None:
        if data is None:
            return None
        row = MagicMock()
        row.__getitem__ = lambda self, key: data[key]
        row.__contains__ = lambda self, key: key in data
        return row

    mock_db.pool.fetchrow = AsyncMock(
        side_effect=[_row(scan_row), _row(regime_row)]
    )
    mock_db.pool.execute = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

class TestComputeRandomExpectedPnl:
    def test_zero_when_tp_zero(self):
        assert compute_random_expected_pnl(0, 1) == 0.0

    def test_zero_when_sl_zero(self):
        assert compute_random_expected_pnl(2, 0) == 0.0

    def test_zero_when_both_zero(self):
        assert compute_random_expected_pnl(0, 0) == 0.0

    def test_symmetric_is_zero(self):
        # P(win)=0.5, E = 0.5*1 - 0.5*1 = 0
        result = compute_random_expected_pnl(1, 1)
        assert math.isclose(result, 0.0, abs_tol=1e-9)

    def test_formula_tp2_sl1(self):
        # P(win) = 1/3, E = 1/3*2 - 2/3*1 = 2/3 - 2/3 = 0
        result = compute_random_expected_pnl(2, 1)
        assert math.isclose(result, 0.0, abs_tol=1e-9)

    def test_formula_tp3_sl1(self):
        # P(win) = 1/4, E = 1/4*3 - 3/4*1 = 0.75 - 0.75 = 0
        result = compute_random_expected_pnl(3, 1)
        assert math.isclose(result, 0.0, abs_tol=1e-9)

    def test_negative_tp_returns_zero(self):
        assert compute_random_expected_pnl(-1, 2) == 0.0

    def test_asymmetric_positive(self):
        # tp=1, sl=3 → P(win)=3/4, E = 3/4*1 - 1/4*3 = 0.75 - 0.75 = 0
        result = compute_random_expected_pnl(1, 3)
        assert math.isclose(result, 0.0, abs_tol=1e-9)


class TestScoreToTier:
    @pytest.mark.parametrize("score,expected", [
        (7, "high"),
        (8, "high"),
        (10, "high"),
        (-7, "high"),   # absolute value is used
        (4, "moderate"),
        (5, "moderate"),
        (6, "moderate"),
        (1, "low"),
        (2, "low"),
        (3, "low"),
        (0, "low"),
    ])
    def test_tiers(self, score, expected):
        assert _score_to_tier(score) == expected


# ---------------------------------------------------------------------------
# Materializer skip tests
# ---------------------------------------------------------------------------

class TestSkipCases:
    @pytest.mark.asyncio
    async def test_skips_trade_without_scan_result_id(self):
        trade = _make_trade(scan_result_id=None)
        db = _make_db()
        svc = SignalPerformanceMaterializer(db)
        result = await svc.materialize(trade)
        assert result is None
        db.pool.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_trade_with_zero_scan_result_id(self):
        # 0 is falsy — treat as missing
        trade = _make_trade(scan_result_id=0)
        db = _make_db()
        svc = SignalPerformanceMaterializer(db)
        result = await svc.materialize(trade)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_trade_without_exit_price(self):
        trade = _make_trade(exit_price=None)
        db = _make_db()
        svc = SignalPerformanceMaterializer(db)
        result = await svc.materialize(trade)
        assert result is None
        db.pool.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_scan_result_not_in_db(self):
        trade = _make_trade()
        db = _make_db(scan_row=None, regime_row=None)
        # fetchrow returns None for the scan_result lookup
        db.pool.fetchrow = AsyncMock(return_value=None)
        svc = SignalPerformanceMaterializer(db)
        result = await svc.materialize(trade)
        assert result is None
        db.pool.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Full materialisation test
# ---------------------------------------------------------------------------

class TestMaterializeValidTrade:
    @pytest.mark.asyncio
    async def test_materializes_valid_trade(self):
        trade = _make_trade(
            entry_price=50000.0,
            exit_price=51500.0,
            net_pnl=75.0,
            fees=3.0,
            take_profit_pct=3.0,
            stop_loss_pct=1.5,
        )
        scan_data = {
            "id": 42,
            "score": 8,
            "confidence": "high",
            "signal_source": "momentum_scanner",
        }
        regime_data = {
            "regime": "bull",
            "regime_confidence": 0.9,
        }
        db = _make_db(scan_row=scan_data, regime_row=regime_data)
        svc = SignalPerformanceMaterializer(db)
        row = await svc.materialize(trade)

        assert row is not None
        assert row["is_win"] is True
        assert row["confidence_score"] == 8
        assert row["score_tier"] == "high"
        assert row["signal_source"] == "momentum_scanner"
        assert row["regime_at_entry"] == "bull"
        assert math.isclose(row["hold_duration_minutes"], 30.0, abs_tol=1e-6)
        # bnh for buy: (51500-50000)/50000*100 = 3.0
        assert math.isclose(row["benchmark_bnh_pnl_pct"], 3.0, abs_tol=1e-6)
        # random expected with tp=3, sl=1.5: p_win=1.5/4.5=1/3, E=1/3*3-2/3*1.5=0
        assert math.isclose(row["benchmark_random_expected_pnl"], 0.0, abs_tol=1e-9)
        db.pool.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_materializes_sell_trade_bnh(self):
        trade = _make_trade(
            signal_direction="sell",
            entry_price=50000.0,
            exit_price=48000.0,
            net_pnl=100.0,
        )
        scan_data = {"id": 99, "score": -7, "confidence": "high", "signal_source": "rsi"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        svc = SignalPerformanceMaterializer(db)
        row = await svc.materialize(trade)

        assert row is not None
        # sell bnh: (50000-48000)/50000*100 = 4.0
        assert math.isclose(row["benchmark_bnh_pnl_pct"], 4.0, abs_tol=1e-6)
        assert row["confidence_score"] == 7  # abs(-7)

    @pytest.mark.asyncio
    async def test_materializes_with_iso_string_datetimes(self):
        trade = _make_trade(
            opened_at="2024-06-01T08:00:00",
            closed_at="2024-06-01T09:15:00",
        )
        scan_data = {"id": 1, "score": 5, "confidence": "moderate", "signal_source": "x"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        svc = SignalPerformanceMaterializer(db)
        row = await svc.materialize(trade)

        assert row is not None
        assert math.isclose(row["hold_duration_minutes"], 75.0, abs_tol=1e-6)

    @pytest.mark.asyncio
    async def test_no_regime_row_sets_none(self):
        trade = _make_trade()
        scan_data = {"id": 1, "score": 6, "confidence": "moderate", "signal_source": "x"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        svc = SignalPerformanceMaterializer(db)
        row = await svc.materialize(trade)

        assert row["regime_at_entry"] is None
        assert row["regime_confidence"] is None

    @pytest.mark.asyncio
    async def test_is_win_false_when_net_pnl_negative(self):
        trade = _make_trade(net_pnl=-20.0)
        scan_data = {"id": 1, "score": 5, "confidence": "moderate", "signal_source": "x"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        svc = SignalPerformanceMaterializer(db)
        row = await svc.materialize(trade)

        assert row["is_win"] is False


# ---------------------------------------------------------------------------
# Decay detector hook tests
# ---------------------------------------------------------------------------

class TestDecayDetectorHook:
    @pytest.mark.asyncio
    async def test_decay_check_called_on_success(self):
        trade = _make_trade()
        scan_data = {"id": 1, "score": 8, "confidence": "high", "signal_source": "x"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        decay = AsyncMock()
        svc = SignalPerformanceMaterializer(db, decay_detector=decay)
        row = await svc.materialize(trade)

        decay.check.assert_awaited_once_with(row)

    @pytest.mark.asyncio
    async def test_decay_exception_does_not_propagate(self):
        trade = _make_trade()
        scan_data = {"id": 1, "score": 8, "confidence": "high", "signal_source": "x"}
        db = _make_db(scan_row=scan_data, regime_row=None)
        decay = AsyncMock()
        decay.check.side_effect = RuntimeError("boom")
        svc = SignalPerformanceMaterializer(db, decay_detector=decay)
        # Should not raise
        row = await svc.materialize(trade)
        assert row is not None
