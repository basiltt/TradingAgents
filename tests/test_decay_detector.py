"""Tests for backend/services/decay_detector.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.decay_detector import DecayDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(fetch_return=None, fetchrow_return=None):
    """Build a mock db with a pool that returns controlled values."""
    db = MagicMock()
    db.pool.fetch = AsyncMock(return_value=fetch_return or [])
    db.pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    db.pool.execute = AsyncMock(return_value=None)
    return db


def _row(is_win: bool, confidence_score: int = 5, realized_pnl_pct: float = 1.0, benchmark_bnh_pnl_pct: float = 0.5):
    return {
        "is_win": is_win,
        "confidence_score": confidence_score,
        "regime_at_entry": "neutral",
        "realized_pnl_pct": realized_pnl_pct,
        "benchmark_bnh_pnl_pct": benchmark_bnh_pnl_pct,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detects_losing_streak_warning():
    """5 consecutive losses at start of results fires a losing_streak warning."""
    rows = [_row(False)] * 5 + [_row(True)] * 25
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    streak_alerts = [a for a in alerts if a["alert_type"] == "losing_streak"]
    assert len(streak_alerts) == 1
    assert streak_alerts[0]["severity"] == "warning"
    assert streak_alerts[0]["metric_value"] == 5.0


@pytest.mark.asyncio
async def test_no_streak_alert_below_threshold():
    """3 consecutive losses then a win → no losing_streak alert."""
    rows = [_row(False)] * 3 + [_row(True)] * 27
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    streak_alerts = [a for a in alerts if a["alert_type"] == "losing_streak"]
    assert streak_alerts == []


@pytest.mark.asyncio
async def test_deduplicates_alerts():
    """An existing unacknowledged alert prevents a new one from being inserted."""
    rows = [_row(False)] * 5 + [_row(True)] * 25
    # fetchrow returns a row → duplicate exists
    existing_row = MagicMock()
    existing_row.__getitem__ = lambda self, k: 42  # id = 42
    db = _make_db(fetch_return=rows, fetchrow_return=existing_row)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    # No alert should be returned and execute should never have been called
    streak_alerts = [a for a in alerts if a["alert_type"] == "losing_streak"]
    assert streak_alerts == []
    db.pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_detects_win_rate_critical():
    """20 trades with <30% wins fires critical win_rate_drop, NOT warning."""
    # 5 wins out of 20 = 25% win rate → critical
    rows = [_row(True)] * 5 + [_row(False)] * 15
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    wr_alerts = [a for a in alerts if a["alert_type"] == "win_rate_drop"]
    assert len(wr_alerts) == 1
    assert wr_alerts[0]["severity"] == "critical"
    # Must not also fire a warning
    warnings = [a for a in wr_alerts if a["severity"] == "warning"]
    assert warnings == []


@pytest.mark.asyncio
async def test_detects_negative_alpha():
    """Cumulative PnL below cumulative BnH benchmark fires negative_alpha warning."""
    # Each trade: PnL = 0.5%, BnH = 1.0%  → negative alpha (need >= 20 trades)
    rows = [_row(True, realized_pnl_pct=0.5, benchmark_bnh_pnl_pct=1.0)] * 20
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    alpha_alerts = [a for a in alerts if a["alert_type"] == "negative_alpha"]
    assert len(alpha_alerts) == 1
    assert alpha_alerts[0]["severity"] == "warning"
    assert alpha_alerts[0]["metric_value"] < 0  # PnL - BnH is negative


@pytest.mark.asyncio
async def test_detects_losing_streak_critical():
    """8 consecutive losses fires a losing_streak critical alert."""
    rows = [_row(False)] * 8 + [_row(True)] * 22
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    streak_alerts = [a for a in alerts if a["alert_type"] == "losing_streak"]
    assert len(streak_alerts) == 1
    assert streak_alerts[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_detects_confidence_miscalibration():
    """High-confidence trades with <50% win rate fires confidence_miscalibration warning."""
    # 10 trades with confidence_score >= 7, only 4 wins (40%)
    rows = (
        [_row(True, confidence_score=8)] * 4
        + [_row(False, confidence_score=8)] * 6
    )
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    cm_alerts = [a for a in alerts if a["alert_type"] == "confidence_miscalibration"]
    assert len(cm_alerts) == 1
    assert cm_alerts[0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_no_alert_on_empty_rows():
    """No rows → no alerts fired."""
    db = _make_db(fetch_return=[], fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    assert alerts == []
    db.pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_win_rate_drop_warning_not_critical():
    """Win rate between 30% and 40% fires warning, not critical."""
    # 7 wins out of 20 = 35% → warning only
    rows = [_row(True)] * 7 + [_row(False)] * 13
    db = _make_db(fetch_return=rows, fetchrow_return=None)
    detector = DecayDetector(db)

    alerts = await detector.check({})

    wr_alerts = [a for a in alerts if a["alert_type"] == "win_rate_drop"]
    assert len(wr_alerts) == 1
    assert wr_alerts[0]["severity"] == "warning"
