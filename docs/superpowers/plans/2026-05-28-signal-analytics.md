# Signal Analytics & Performance Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a signal performance tracking system that materializes trade outcomes, detects signal decay, classifies market regimes, and provides a dedicated analytics dashboard.

**Architecture:** Event-driven materialization triggered on trade close, with a periodic regime classifier (15min), decay detector post-materialization, and a React dashboard reading from pre-computed data. Feedback loop injects real outcome data into analyst prompts.

**Tech Stack:** Python/FastAPI (asyncpg), PostgreSQL, Recharts, TanStack Router, Bybit API, LLM (configured model)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/services/signal_performance_service.py` | Materializes closed trade → signal_performance row |
| `backend/services/regime_classifier.py` | Periodic regime classification with indicators + LLM |
| `backend/services/decay_detector.py` | Checks rolling metrics, writes decay_alerts |
| `backend/services/signal_analytics_service.py` | Query layer for dashboard aggregations |
| `backend/routers/signal_analytics.py` | REST endpoints for signal analytics |
| `frontend/src/components/signal-analytics/SignalAnalyticsPage.tsx` | Main page component |
| `frontend/src/components/signal-analytics/KpiCards.tsx` | KPI summary cards |
| `frontend/src/components/signal-analytics/CalibrationChart.tsx` | Confidence calibration chart |
| `frontend/src/components/signal-analytics/RollingWinRateChart.tsx` | Rolling win rate line chart |
| `frontend/src/components/signal-analytics/BenchmarkChart.tsx` | Cumulative PnL vs benchmarks |
| `frontend/src/components/signal-analytics/RegimeBreakdownChart.tsx` | Regime performance bars |
| `frontend/src/components/signal-analytics/DecayAlertBanner.tsx` | Alert banner component |
| `frontend/src/components/signal-analytics/TradeTable.tsx` | Performance trades table |
| `tests/test_signal_performance_service.py` | Unit tests for materializer |
| `tests/test_regime_classifier.py` | Unit tests for regime classifier |
| `tests/test_decay_detector.py` | Unit tests for decay detection |
| `tests/test_signal_analytics_router.py` | Integration tests for API endpoints |

### Modified Files
| File | Change |
|------|--------|
| `backend/persistence.py` | Add migration (tables + scan_result_id column) |
| `backend/async_persistence.py` | Add migration + query methods for new tables |
| `backend/services/trade_service.py` | Hook materialization on trade close |
| `backend/services/auto_trade_service.py` | Pass scan_result_id when placing trades |
| `backend/services/accounts_service.py` | Accept scan_result_id in place_trade |
| `backend/scheduler.py` | Add regime classifier periodic task |
| `backend/main.py` | Wire new router + services |
| `frontend/src/routes/route-tree.tsx` | Add signal-analytics route |
| `tradingagents/graph/trading_graph.py` | Inject feedback context into create_initial_state |

---

## Task 1: Database Migration

**Files:**
- Modify: `backend/persistence.py` (add to `_MIGRATIONS` list)
- Modify: `backend/async_persistence.py` (add same migration)

- [ ] **Step 1: Add migration to persistence.py**

Find the last migration number in `_MIGRATIONS` list and add:

```python
(33, """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS scan_result_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_trades_scan_result_id ON trades(scan_result_id) WHERE scan_result_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS signal_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID NOT NULL UNIQUE REFERENCES trades(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    symbol VARCHAR(30) NOT NULL,
    direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
    confidence_score INTEGER,
    confidence_tier VARCHAR(10) CHECK (confidence_tier IN ('high', 'moderate', 'low')),
    signal_source VARCHAR(10),
    regime_at_entry VARCHAR(15) CHECK (regime_at_entry IS NULL OR regime_at_entry IN ('trending_up', 'trending_down', 'ranging', 'volatile')),
    regime_confidence NUMERIC(4,2),
    entry_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    hold_duration_minutes INTEGER,
    realized_pnl_pct NUMERIC(12,4),
    net_pnl NUMERIC(20,8),
    fees NUMERIC(20,8),
    close_reason VARCHAR(20),
    benchmark_bnh_pnl_pct NUMERIC(12,4),
    benchmark_random_expected_pnl NUMERIC(12,4),
    is_win BOOLEAN NOT NULL,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sp_account_closed ON signal_performance(account_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sp_symbol_closed ON signal_performance(symbol, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sp_confidence ON signal_performance(confidence_score);
CREATE INDEX IF NOT EXISTS idx_sp_regime ON signal_performance(regime_at_entry);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(30) NOT NULL,
    regime VARCHAR(15) NOT NULL CHECK (regime IN ('trending_up', 'trending_down', 'ranging', 'volatile')),
    adx NUMERIC(8,4),
    atr_pct NUMERIC(8,4),
    bb_width_pct NUMERIC(8,4),
    llm_confirmed BOOLEAN DEFAULT FALSE,
    llm_regime VARCHAR(15),
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rs_symbol_time ON regime_snapshots(symbol, classified_at DESC);

CREATE TABLE IF NOT EXISTS decay_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(30) NOT NULL,
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('warning', 'critical')),
    message TEXT NOT NULL,
    metric_value NUMERIC(12,4),
    threshold NUMERIC(12,4),
    window_trades INTEGER,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""),
```

- [ ] **Step 2: Add same migration to async_persistence.py**

Find the `_MIGRATIONS` list in `async_persistence.py` and add the identical migration tuple with the same version number.

- [ ] **Step 3: Verify migration applies**

Run:
```bash
cd backend && python -c "from persistence import Database; db = Database(); print('Migration applied')"
```

Expected: No errors, tables created.

- [ ] **Step 4: Commit**

```bash
git add backend/persistence.py backend/async_persistence.py
git commit -m "feat: add signal_performance, regime_snapshots, decay_alerts tables and scan_result_id column"
```

---

## Task 2: Wire scan_result_id Through Trade Placement

**Files:**
- Modify: `backend/services/auto_trade_service.py`
- Modify: `backend/services/accounts_service.py`

- [ ] **Step 1: Pass scan_result_id from auto_trade_service**

In `auto_trade_service.py`, find the `place_trade` call (around line 860). The `result` dict passed to the execution method contains scan result data. Add `scan_result_id` parameter:

```python
result_data = await self._accounts.place_trade(
    account_id=account_id,
    symbol=symbol,
    signal_direction=direction,
    trade_direction=cfg.get("direction", "straight"),
    leverage=cfg.get("leverage", 20),
    take_profit_pct=cfg.get("take_profit_pct", 150),
    stop_loss_pct=cfg.get("stop_loss_pct", 100),
    capital_pct=cfg.get("capital_pct", 5),
    base_capital=state.base_capital,
    source="scanner",
    scan_result_id=result.get("id"),
)
```

- [ ] **Step 2: Accept and store scan_result_id in accounts_service**

In `accounts_service.py`, find the `place_trade` method. Add `scan_result_id: int | None = None` parameter. Store it in the trade's metadata JSONB or as the direct column:

In the INSERT query for the trade, add `scan_result_id` to the column list and values.

- [ ] **Step 3: Verify the flow with a log statement**

Add a temporary `logger.info("scan_result_id=%s", scan_result_id)` in `place_trade`. Run a scan in test mode to confirm the ID propagates. Remove the log after verification.

- [ ] **Step 4: Commit**

```bash
git add backend/services/auto_trade_service.py backend/services/accounts_service.py
git commit -m "feat: propagate scan_result_id from scanner signal to trade record"
```

---

## Task 3: Signal Performance Materializer Service

**Files:**
- Create: `backend/services/signal_performance_service.py`
- Create: `tests/test_signal_performance_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_signal_performance_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.signal_performance_service import SignalPerformanceMaterializer


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.pool = AsyncMock()
    return db


@pytest.fixture
def service(mock_db):
    return SignalPerformanceMaterializer(db=mock_db)


@pytest.mark.asyncio
async def test_skips_trade_without_scan_result_id(service, mock_db):
    trade = {"id": "abc", "scan_result_id": None, "source": "manual"}
    result = await service.materialize(trade)
    assert result is None


@pytest.mark.asyncio
async def test_skips_trade_without_exit_price(service, mock_db):
    trade = {"id": "abc", "scan_result_id": 5, "source": "scanner", "exit_price": None, "status": "closed"}
    result = await service.materialize(trade)
    assert result is None


@pytest.mark.asyncio
async def test_computes_benchmark_random_expected():
    from backend.services.signal_performance_service import compute_random_expected_pnl
    # TP at 2%, SL at 1% → random win rate = 1/(1+2) = 33.3%, expected = 0.333*2 - 0.667*1 = 0%
    result = compute_random_expected_pnl(tp_pct=2.0, sl_pct=1.0)
    assert abs(result - 0.0) < 0.01


@pytest.mark.asyncio
async def test_computes_benchmark_random_expected_asymmetric():
    from backend.services.signal_performance_service import compute_random_expected_pnl
    # TP at 3%, SL at 1% → random win rate = 1/(1+3) = 25%, expected = 0.25*3 - 0.75*1 = 0%
    result = compute_random_expected_pnl(tp_pct=3.0, sl_pct=1.0)
    assert abs(result - 0.0) < 0.01


@pytest.mark.asyncio
async def test_materializes_valid_trade(service, mock_db):
    trade = {
        "id": "trade-1", "account_id": "acc-1", "scan_result_id": 10,
        "symbol": "BTCUSDT", "signal_direction": "buy", "source": "scanner",
        "entry_price": "50000.0", "exit_price": "51000.0",
        "opened_at": "2026-05-01T10:00:00+00:00", "closed_at": "2026-05-01T12:00:00+00:00",
        "realized_pnl_pct": "2.0", "net_pnl": "100.0", "fees": "5.0",
        "close_reason": "take_profit", "take_profit_pct": "2.0", "stop_loss_pct": "1.0",
    }
    # Mock scan_result lookup
    mock_db.pool.fetchrow = AsyncMock(side_effect=[
        {"id": 10, "score": 8, "confidence": "high", "signal_source": "trader"},  # scan_result
        {"regime": "trending_up", "regime_confidence": 0.85},  # regime snapshot
    ])
    mock_db.pool.execute = AsyncMock()

    result = await service.materialize(trade)
    assert result is not None
    assert result["is_win"] is True
    assert result["confidence_score"] == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_signal_performance_service.py -v`
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Implement the service**

```python
# backend/services/signal_performance_service.py
"""Materializes closed scanner trades into signal_performance rows."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def compute_random_expected_pnl(tp_pct: float, sl_pct: float) -> float:
    """Expected PnL of a random entry with given TP/SL distances.
    
    Assumes price hits TP or SL with probability inversely proportional to distance.
    P(win) = sl_distance / (tp_distance + sl_distance)
    """
    if tp_pct <= 0 or sl_pct <= 0:
        return 0.0
    p_win = sl_pct / (tp_pct + sl_pct)
    return p_win * tp_pct - (1 - p_win) * sl_pct


def _score_to_tier(score: int) -> str:
    if score >= 7:
        return "high"
    elif score >= 4:
        return "moderate"
    return "low"


class SignalPerformanceMaterializer:
    def __init__(self, db, bybit_client=None, decay_detector=None):
        self._db = db
        self._bybit = bybit_client
        self._decay = decay_detector

    async def materialize(self, trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        scan_result_id = trade.get("scan_result_id")
        if not scan_result_id:
            return None

        exit_price = trade.get("exit_price")
        if not exit_price:
            return None

        # Fetch scan_result
        scan_result = await self._db.pool.fetchrow(
            "SELECT id, score, confidence, signal_source FROM scan_results WHERE id = $1",
            scan_result_id,
        )
        if not scan_result:
            logger.warning("scan_result_not_found", extra={"scan_result_id": scan_result_id, "trade_id": trade["id"]})
            return None

        # Fetch regime at entry time
        regime_row = await self._db.pool.fetchrow(
            "SELECT regime, "
            "CASE WHEN llm_confirmed THEN 0.9 ELSE 0.5 END AS regime_confidence "
            "FROM regime_snapshots WHERE symbol = $1 AND classified_at <= $2 "
            "ORDER BY classified_at DESC LIMIT 1",
            trade["symbol"],
            trade.get("opened_at"),
        )

        # Compute hold duration
        opened_at = trade.get("opened_at")
        closed_at = trade.get("closed_at")
        hold_minutes = None
        if opened_at and closed_at:
            if isinstance(opened_at, str):
                opened_at = datetime.fromisoformat(opened_at)
            if isinstance(closed_at, str):
                closed_at = datetime.fromisoformat(closed_at)
            hold_minutes = int((closed_at - opened_at).total_seconds() / 60)

        # Compute benchmarks
        entry = float(trade["entry_price"])
        exit_p = float(exit_price)
        bnh_pnl_pct = ((exit_p - entry) / entry) * 100 if trade.get("signal_direction") == "buy" else ((entry - exit_p) / entry) * 100

        tp_pct = float(trade.get("take_profit_pct") or 0)
        sl_pct = float(trade.get("stop_loss_pct") or 0)
        random_expected = compute_random_expected_pnl(tp_pct, sl_pct)

        net_pnl = float(trade.get("net_pnl") or 0)
        confidence_score = abs(int(scan_result["score"])) if scan_result["score"] else None

        row = {
            "id": str(uuid.uuid4()),
            "trade_id": trade["id"],
            "account_id": trade["account_id"],
            "symbol": trade["symbol"],
            "direction": trade.get("signal_direction", "buy"),
            "confidence_score": confidence_score,
            "confidence_tier": _score_to_tier(confidence_score) if confidence_score else None,
            "signal_source": scan_result.get("signal_source"),
            "regime_at_entry": regime_row["regime"] if regime_row else None,
            "regime_confidence": float(regime_row["regime_confidence"]) if regime_row else None,
            "entry_price": entry,
            "exit_price": exit_p,
            "hold_duration_minutes": hold_minutes,
            "realized_pnl_pct": float(trade.get("realized_pnl_pct") or 0),
            "net_pnl": net_pnl,
            "fees": float(trade.get("fees") or 0),
            "close_reason": trade.get("close_reason"),
            "benchmark_bnh_pnl_pct": bnh_pnl_pct,
            "benchmark_random_expected_pnl": random_expected,
            "is_win": net_pnl > 0,
            "opened_at": trade.get("opened_at"),
            "closed_at": trade.get("closed_at"),
        }

        await self._db.pool.execute(
            """INSERT INTO signal_performance (
                id, trade_id, account_id, symbol, direction, confidence_score,
                confidence_tier, signal_source, regime_at_entry, regime_confidence,
                entry_price, exit_price, hold_duration_minutes, realized_pnl_pct,
                net_pnl, fees, close_reason, benchmark_bnh_pnl_pct,
                benchmark_random_expected_pnl, is_win, opened_at, closed_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
            ) ON CONFLICT (trade_id) DO NOTHING""",
            row["id"], row["trade_id"], row["account_id"], row["symbol"],
            row["direction"], row["confidence_score"], row["confidence_tier"],
            row["signal_source"], row["regime_at_entry"], row["regime_confidence"],
            row["entry_price"], row["exit_price"], row["hold_duration_minutes"],
            row["realized_pnl_pct"], row["net_pnl"], row["fees"],
            row["close_reason"], row["benchmark_bnh_pnl_pct"],
            row["benchmark_random_expected_pnl"], row["is_win"],
            row["opened_at"], row["closed_at"],
        )

        if self._decay:
            try:
                await self._decay.check(row)
            except Exception:
                logger.exception("decay_check_failed")

        return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_signal_performance_service.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/signal_performance_service.py tests/test_signal_performance_service.py
git commit -m "feat: add signal performance materializer service with tests"
```

---

## Task 4: Hook Materializer Into Trade Close Flow

**Files:**
- Modify: `backend/services/trade_service.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add materializer call after trade close**

In `trade_service.py`, add an import and attribute:

```python
from backend.services.signal_performance_service import SignalPerformanceMaterializer
```

In the `TradeService.__init__`, accept optional `signal_perf: SignalPerformanceMaterializer = None` and store it as `self._signal_perf`.

In `_close_full` method, after line 282 (`await self._broadcast_trade_event("trade.closed", closed)`), add:

```python
if self._signal_perf and closed.get("scan_result_id"):
    try:
        await self._signal_perf.materialize(closed)
    except Exception:
        logger.exception("signal_performance_materialize_failed", extra={"trade_id": trade_id})
```

- [ ] **Step 2: Wire the service in main.py**

In `main.py` where `TradeService` is instantiated, create the materializer and pass it:

```python
from backend.services.signal_performance_service import SignalPerformanceMaterializer
from backend.services.decay_detector import DecayDetector

decay_detector = DecayDetector(db=db)
signal_perf = SignalPerformanceMaterializer(db=db, decay_detector=decay_detector)
trade_service = TradeService(db=db, ..., signal_perf=signal_perf)
```

- [ ] **Step 3: Commit**

```bash
git add backend/services/trade_service.py backend/main.py
git commit -m "feat: hook signal performance materializer into trade close flow"
```

---

## Task 5: Decay Detector Service

**Files:**
- Create: `backend/services/decay_detector.py`
- Create: `tests/test_decay_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_decay_detector.py
import pytest
from unittest.mock import AsyncMock
from backend.services.decay_detector import DecayDetector


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.pool = AsyncMock()
    return db


@pytest.fixture
def detector(mock_db):
    return DecayDetector(db=mock_db)


@pytest.mark.asyncio
async def test_detects_losing_streak(detector, mock_db):
    # Last 5 trades are all losses
    mock_db.pool.fetch = AsyncMock(return_value=[
        {"is_win": False} for _ in range(5)
    ])
    mock_db.pool.fetchrow = AsyncMock(return_value=None)  # No existing alert
    mock_db.pool.execute = AsyncMock()

    new_row = {"is_win": False, "account_id": "acc1"}
    alerts = await detector.check(new_row)
    assert any(a["alert_type"] == "losing_streak" for a in alerts)


@pytest.mark.asyncio
async def test_no_alert_below_threshold(detector, mock_db):
    # 3 losses in a row — below 5 threshold
    mock_db.pool.fetch = AsyncMock(return_value=[
        {"is_win": False}, {"is_win": False}, {"is_win": False},
        {"is_win": True}, {"is_win": False},
    ])
    mock_db.pool.fetchrow = AsyncMock(return_value=None)
    mock_db.pool.execute = AsyncMock()

    alerts = await detector.check({"is_win": False, "account_id": "acc1"})
    assert not any(a["alert_type"] == "losing_streak" for a in alerts)


@pytest.mark.asyncio
async def test_deduplicates_alerts(detector, mock_db):
    mock_db.pool.fetch = AsyncMock(return_value=[
        {"is_win": False} for _ in range(6)
    ])
    # Existing unacknowledged alert of same type
    mock_db.pool.fetchrow = AsyncMock(return_value={"id": 1, "alert_type": "losing_streak"})
    mock_db.pool.execute = AsyncMock()

    alerts = await detector.check({"is_win": False, "account_id": "acc1"})
    assert not any(a["alert_type"] == "losing_streak" for a in alerts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_decay_detector.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the service**

```python
# backend/services/decay_detector.py
"""Detects signal quality decay and creates alerts."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_THRESHOLDS = {
    "win_rate_warning": 0.40,
    "win_rate_critical": 0.30,
    "win_rate_window": 20,
    "streak_warning": 5,
    "streak_critical": 8,
    "calibration_window": 30,
    "calibration_threshold": 0.50,
    "regime_window": 15,
    "regime_threshold": 0.35,
    "alpha_window": 30,
}


class DecayDetector:
    def __init__(self, db):
        self._db = db

    async def check(self, new_row: Dict[str, Any]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []

        recent = await self._db.pool.fetch(
            "SELECT is_win, confidence_score, regime_at_entry, "
            "realized_pnl_pct, benchmark_bnh_pnl_pct "
            "FROM signal_performance ORDER BY closed_at DESC LIMIT $1",
            _THRESHOLDS["alpha_window"],
        )

        if len(recent) >= _THRESHOLDS["win_rate_window"]:
            window = recent[:_THRESHOLDS["win_rate_window"]]
            win_rate = sum(1 for r in window if r["is_win"]) / len(window)
            if win_rate < _THRESHOLDS["win_rate_critical"]:
                await self._maybe_alert(alerts, "win_rate_drop", "critical",
                    f"Win rate dropped to {win_rate*100:.0f}% over last {len(window)} trades",
                    win_rate, _THRESHOLDS["win_rate_critical"], len(window))
            elif win_rate < _THRESHOLDS["win_rate_warning"]:
                await self._maybe_alert(alerts, "win_rate_drop", "warning",
                    f"Win rate dropped to {win_rate*100:.0f}% over last {len(window)} trades",
                    win_rate, _THRESHOLDS["win_rate_warning"], len(window))

        # Losing streak
        streak = 0
        for r in recent:
            if not r["is_win"]:
                streak += 1
            else:
                break
        if streak >= _THRESHOLDS["streak_critical"]:
            await self._maybe_alert(alerts, "losing_streak", "critical",
                f"{streak} consecutive losing trades", streak,
                _THRESHOLDS["streak_critical"], streak)
        elif streak >= _THRESHOLDS["streak_warning"]:
            await self._maybe_alert(alerts, "losing_streak", "warning",
                f"{streak} consecutive losing trades", streak,
                _THRESHOLDS["streak_warning"], streak)

        # Confidence miscalibration
        high_conf = [r for r in recent if r.get("confidence_score") and r["confidence_score"] >= 7]
        if len(high_conf) >= 10:
            window = high_conf[:_THRESHOLDS["calibration_window"]]
            hc_win_rate = sum(1 for r in window if r["is_win"]) / len(window)
            if hc_win_rate < _THRESHOLDS["calibration_threshold"]:
                await self._maybe_alert(alerts, "confidence_miscalibration", "warning",
                    f"High-confidence signals winning only {hc_win_rate*100:.0f}% "
                    f"(expected >50%) over last {len(window)} high-confidence trades",
                    hc_win_rate, _THRESHOLDS["calibration_threshold"], len(window))

        # Negative alpha
        if len(recent) >= _THRESHOLDS["alpha_window"]:
            window = recent[:_THRESHOLDS["alpha_window"]]
            cum_pnl = sum(float(r["realized_pnl_pct"] or 0) for r in window)
            cum_bnh = sum(float(r["benchmark_bnh_pnl_pct"] or 0) for r in window)
            if cum_pnl < cum_bnh:
                await self._maybe_alert(alerts, "negative_alpha", "warning",
                    f"System PnL ({cum_pnl:.1f}%) underperforming buy-and-hold ({cum_bnh:.1f}%) "
                    f"over last {len(window)} trades",
                    cum_pnl - cum_bnh, 0, len(window))

        return alerts

    async def _maybe_alert(
        self, alerts: list, alert_type: str, severity: str,
        message: str, metric_value: float, threshold: float, window_trades: int,
    ) -> None:
        existing = await self._db.pool.fetchrow(
            "SELECT id FROM decay_alerts WHERE alert_type = $1 AND acknowledged = FALSE",
            alert_type,
        )
        if existing:
            return

        await self._db.pool.execute(
            "INSERT INTO decay_alerts (alert_type, severity, message, metric_value, threshold, window_trades) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            alert_type, severity, message, metric_value, threshold, window_trades,
        )
        alert = {"alert_type": alert_type, "severity": severity, "message": message}
        alerts.append(alert)
        logger.warning("decay_alert_fired", extra=alert)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_decay_detector.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/decay_detector.py tests/test_decay_detector.py
git commit -m "feat: add decay detector service with rolling window alerts"
```

---

## Task 6: Regime Classifier Service

**Files:**
- Create: `backend/services/regime_classifier.py`
- Create: `tests/test_regime_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_regime_classifier.py
import pytest
from backend.services.regime_classifier import classify_from_indicators


def test_trending_up():
    result = classify_from_indicators(adx=30, price=100, ema20=95, atr_pct=1.0, atr_avg_30=0.8, bb_width=3.0, bb_width_median=3.5)
    assert result == "trending_up"


def test_trending_down():
    result = classify_from_indicators(adx=30, price=90, ema20=95, atr_pct=1.0, atr_avg_30=0.8, bb_width=3.0, bb_width_median=3.5)
    assert result == "trending_down"


def test_volatile():
    result = classify_from_indicators(adx=30, price=100, ema20=95, atr_pct=2.0, atr_avg_30=0.8, bb_width=3.0, bb_width_median=3.5)
    assert result == "volatile"


def test_ranging():
    result = classify_from_indicators(adx=15, price=100, ema20=99, atr_pct=0.5, atr_avg_30=0.8, bb_width=2.0, bb_width_median=3.5)
    assert result == "ranging"


def test_volatile_takes_priority():
    # ADX > 25 (trending) but ATR% > 1.5x avg (volatile) — volatile wins
    result = classify_from_indicators(adx=30, price=100, ema20=95, atr_pct=1.5, atr_avg_30=0.8, bb_width=3.0, bb_width_median=3.5)
    assert result == "volatile"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_regime_classifier.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the service**

```python
# backend/services/regime_classifier.py
"""Periodic market regime classification using indicators + LLM confirmation."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def classify_from_indicators(
    adx: float, price: float, ema20: float,
    atr_pct: float, atr_avg_30: float,
    bb_width: float, bb_width_median: float,
) -> str:
    """Classify market regime from indicators. Priority: volatile > trending > ranging."""
    if atr_pct > 1.5 * atr_avg_30:
        return "volatile"
    if adx > 25:
        return "trending_up" if price > ema20 else "trending_down"
    if adx < 20 and bb_width < bb_width_median:
        return "ranging"
    # Default: if ADX between 20-25 or BB width >= median
    if adx > 25:
        return "trending_up" if price > ema20 else "trending_down"
    return "ranging"


def compute_indicators(candles: List[Dict[str, float]]) -> Dict[str, float]:
    """Compute ADX(14), ATR%(14), EMA(20), BB width from OHLCV candles.
    
    candles: list of dicts with keys: open, high, low, close, volume
    Returns dict with: adx, atr_pct, ema20, price, bb_width, bb_width_median, atr_avg_30
    """
    if len(candles) < 30:
        return {}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    # EMA(20)
    ema20 = _ema(closes, 20)

    # ATR(14)
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr14 = sum(trs[-14:]) / 14
    current_price = closes[-1]
    atr_pct = (atr14 / current_price) * 100 if current_price else 0

    # ATR% 30-period average for volatility comparison
    atr_pcts = []
    for i in range(14, len(trs)):
        atr_i = sum(trs[i - 14:i]) / 14
        price_i = closes[i + 1]  # +1 because trs is offset by 1
        atr_pcts.append((atr_i / price_i) * 100 if price_i else 0)
    atr_avg_30 = sum(atr_pcts[-30:]) / len(atr_pcts[-30:]) if atr_pcts else atr_pct

    # Bollinger Band width (20, 2σ)
    sma20 = sum(closes[-20:]) / 20
    variance = sum((c - sma20) ** 2 for c in closes[-20:]) / 20
    std = variance ** 0.5
    bb_upper = sma20 + 2 * std
    bb_lower = sma20 - 2 * std
    bb_width = ((bb_upper - bb_lower) / sma20) * 100 if sma20 else 0

    # BB width median over available history
    bb_widths = []
    for i in range(20, len(closes)):
        window = closes[i - 20:i]
        sma = sum(window) / 20
        var = sum((c - sma) ** 2 for c in window) / 20
        s = var ** 0.5
        w = ((sma + 2 * s) - (sma - 2 * s)) / sma * 100 if sma else 0
        bb_widths.append(w)
    bb_widths.sort()
    bb_width_median = bb_widths[len(bb_widths) // 2] if bb_widths else bb_width

    # ADX(14) - simplified using smoothed +DI/-DI
    plus_dm = []
    minus_dm = []
    for i in range(1, len(candles)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)

    atr_series = trs  # Already computed
    if len(atr_series) < 14:
        adx = 20  # Default neutral
    else:
        smoothed_plus = sum(plus_dm[-14:]) / 14
        smoothed_minus = sum(minus_dm[-14:]) / 14
        smoothed_tr = sum(atr_series[-14:]) / 14
        plus_di = (smoothed_plus / smoothed_tr * 100) if smoothed_tr else 0
        minus_di = (smoothed_minus / smoothed_tr * 100) if smoothed_tr else 0
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) else 0
        adx = dx  # Simplified single-period ADX

    return {
        "adx": adx,
        "atr_pct": atr_pct,
        "atr_avg_30": atr_avg_30,
        "ema20": ema20,
        "price": current_price,
        "bb_width": bb_width,
        "bb_width_median": bb_width_median,
    }


def _ema(values: List[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


class RegimeClassifier:
    def __init__(self, db, llm_callable=None):
        self._db = db
        self._llm = llm_callable

    async def classify_symbol(self, symbol: str, candles: List[Dict[str, float]]) -> Dict[str, Any]:
        indicators = compute_indicators(candles)
        if not indicators:
            return {"regime": "ranging", "indicators": {}}

        indicator_regime = classify_from_indicators(
            adx=indicators["adx"],
            price=indicators["price"],
            ema20=indicators["ema20"],
            atr_pct=indicators["atr_pct"],
            atr_avg_30=indicators["atr_avg_30"],
            bb_width=indicators["bb_width"],
            bb_width_median=indicators["bb_width_median"],
        )

        llm_confirmed = False
        llm_regime = None
        final_regime = indicator_regime

        if self._llm:
            try:
                llm_result = await self._llm_confirm(symbol, indicators, indicator_regime, candles[-12:])
                llm_regime = llm_result.get("regime")
                llm_confidence = llm_result.get("confidence", 0)
                llm_confirmed = llm_regime == indicator_regime
                if llm_confidence > 0.7 and llm_regime:
                    final_regime = llm_regime
            except Exception:
                logger.exception("regime_llm_confirmation_failed", extra={"symbol": symbol})

        # Store snapshot
        await self._db.pool.execute(
            "INSERT INTO regime_snapshots (symbol, regime, adx, atr_pct, bb_width_pct, llm_confirmed, llm_regime) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            symbol, final_regime, indicators["adx"], indicators["atr_pct"],
            indicators["bb_width"], llm_confirmed, llm_regime,
        )

        return {
            "regime": final_regime,
            "indicators": indicators,
            "llm_confirmed": llm_confirmed,
            "llm_regime": llm_regime,
        }

    async def _llm_confirm(self, symbol: str, indicators: dict, indicator_regime: str, recent_candles: list) -> dict:
        candle_summary = ", ".join(
            f"O:{c['open']:.1f} H:{c['high']:.1f} L:{c['low']:.1f} C:{c['close']:.1f}"
            for c in recent_candles[-6:]
        )
        prompt = (
            f"Symbol: {symbol}\n"
            f"Indicators: ADX={indicators['adx']:.1f}, ATR%={indicators['atr_pct']:.2f}, "
            f"BB Width%={indicators['bb_width']:.2f}, Price={indicators['price']:.2f}, EMA20={indicators['ema20']:.2f}\n"
            f"Recent 6 candles (4h): {candle_summary}\n"
            f"Indicator-based classification: {indicator_regime}\n\n"
            f"Classify this market as exactly one of: trending_up, trending_down, ranging, volatile.\n"
            f"Respond with JSON: {{\"regime\": \"...\", \"confidence\": 0.0-1.0}}"
        )
        return await self._llm(prompt)

    async def run_all(self, symbols: List[str], fetch_candles_fn) -> List[Dict[str, Any]]:
        results = []
        for symbol in symbols:
            try:
                candles = await fetch_candles_fn(symbol, interval="240", limit=50)
                result = await self.classify_symbol(symbol, candles)
                result["symbol"] = symbol
                results.append(result)
            except Exception:
                logger.exception("regime_classify_failed", extra={"symbol": symbol})
        return results
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_regime_classifier.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/regime_classifier.py tests/test_regime_classifier.py
git commit -m "feat: add regime classifier with indicator-based classification and LLM confirmation"
```

---

## Task 7: Signal Analytics Query Service

**Files:**
- Create: `backend/services/signal_analytics_service.py`

- [ ] **Step 1: Implement the query service**

```python
# backend/services/signal_analytics_service.py
"""Query layer for signal analytics dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SignalAnalyticsService:
    def __init__(self, db):
        self._db = db

    async def get_summary(
        self, account_id: Optional[str] = None,
        start_date: Optional[datetime] = None, end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not start_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=90)
        if not end_date:
            end_date = datetime.now(timezone.utc)

        where = "WHERE closed_at >= $1 AND closed_at <= $2"
        params: list = [start_date, end_date]
        if account_id:
            where += " AND account_id = $3"
            params.append(account_id)

        row = await self._db.pool.fetchrow(
            f"SELECT COUNT(*) as total, "
            f"SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins, "
            f"AVG(realized_pnl_pct) as avg_pnl_pct, "
            f"SUM(net_pnl) as total_pnl, "
            f"AVG(hold_duration_minutes) as avg_hold_min "
            f"FROM signal_performance {where}",
            *params,
        )

        total = int(row["total"] or 0)
        wins = int(row["wins"] or 0)
        win_rate = wins / total if total > 0 else 0

        # Current streak
        recent = await self._db.pool.fetch(
            f"SELECT is_win FROM signal_performance {where} ORDER BY closed_at DESC LIMIT 50",
            *params,
        )
        streak = 0
        streak_type = None
        for r in recent:
            if streak_type is None:
                streak_type = "W" if r["is_win"] else "L"
                streak = 1
            elif (r["is_win"] and streak_type == "W") or (not r["is_win"] and streak_type == "L"):
                streak += 1
            else:
                break

        # Active alerts count
        alert_count = await self._db.pool.fetchval(
            "SELECT COUNT(*) FROM decay_alerts WHERE acknowledged = FALSE"
        )

        return {
            "total_trades": total,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(float(row["avg_pnl_pct"] or 0), 4),
            "total_pnl": round(float(row["total_pnl"] or 0), 2),
            "avg_hold_minutes": round(float(row["avg_hold_min"] or 0), 0),
            "current_streak": f"{streak}{streak_type}" if streak_type else "0",
            "active_alerts": int(alert_count or 0),
        }

    async def get_rolling_win_rate(
        self, account_id: Optional[str] = None, window: int = 20,
    ) -> List[Dict[str, Any]]:
        where = ""
        params: list = []
        if account_id:
            where = "WHERE account_id = $1"
            params.append(account_id)

        rows = await self._db.pool.fetch(
            f"SELECT closed_at, is_win, confidence_tier "
            f"FROM signal_performance {where} ORDER BY closed_at ASC",
            *params,
        )

        results = []
        for i in range(window - 1, len(rows)):
            window_rows = rows[i - window + 1:i + 1]
            win_count = sum(1 for r in window_rows if r["is_win"])
            results.append({
                "date": rows[i]["closed_at"].isoformat(),
                "win_rate": round(win_count / window, 4),
                "trade_number": i + 1,
            })
        return results

    async def get_calibration_curve(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where = ""
        params: list = []
        if account_id:
            where = "WHERE account_id = $1"
            params.append(account_id)

        rows = await self._db.pool.fetch(
            f"SELECT confidence_tier, COUNT(*) as total, "
            f"SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins "
            f"FROM signal_performance {where} "
            f"GROUP BY confidence_tier ORDER BY confidence_tier",
            *params,
        )

        return [
            {
                "tier": row["confidence_tier"] or "unknown",
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]), 4) if row["total"] else 0,
            }
            for row in rows
        ]

    async def get_benchmark_comparison(
        self, account_id: Optional[str] = None,
        start_date: Optional[datetime] = None, end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        if not start_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=90)
        if not end_date:
            end_date = datetime.now(timezone.utc)

        where = "WHERE closed_at >= $1 AND closed_at <= $2"
        params: list = [start_date, end_date]
        if account_id:
            where += " AND account_id = $3"
            params.append(account_id)

        rows = await self._db.pool.fetch(
            f"SELECT closed_at, realized_pnl_pct, benchmark_bnh_pnl_pct, benchmark_random_expected_pnl "
            f"FROM signal_performance {where} ORDER BY closed_at ASC",
            *params,
        )

        cum_pnl = 0.0
        cum_bnh = 0.0
        cum_random = 0.0
        results = []
        for i, row in enumerate(rows):
            cum_pnl += float(row["realized_pnl_pct"] or 0)
            cum_bnh += float(row["benchmark_bnh_pnl_pct"] or 0)
            cum_random += float(row["benchmark_random_expected_pnl"] or 0)
            results.append({
                "date": row["closed_at"].isoformat(),
                "trade_number": i + 1,
                "system_pnl": round(cum_pnl, 4),
                "buy_and_hold": round(cum_bnh, 4),
                "random_expected": round(cum_random, 4),
            })
        return results

    async def get_regime_breakdown(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where = ""
        params: list = []
        if account_id:
            where = "WHERE account_id = $1"
            params.append(account_id)

        rows = await self._db.pool.fetch(
            f"SELECT regime_at_entry, COUNT(*) as total, "
            f"SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins, "
            f"AVG(realized_pnl_pct) as avg_pnl_pct "
            f"FROM signal_performance {where} "
            f"GROUP BY regime_at_entry",
            *params,
        )

        return [
            {
                "regime": row["regime_at_entry"] or "unknown",
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]), 4) if row["total"] else 0,
                "avg_pnl_pct": round(float(row["avg_pnl_pct"] or 0), 4),
            }
            for row in rows
        ]

    async def get_current_regimes(self) -> List[Dict[str, Any]]:
        rows = await self._db.pool.fetch(
            "SELECT DISTINCT ON (symbol) symbol, regime, adx, atr_pct, bb_width_pct, "
            "llm_confirmed, llm_regime, classified_at "
            "FROM regime_snapshots ORDER BY symbol, classified_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_decay_alerts(self, acknowledged: bool = False) -> List[Dict[str, Any]]:
        rows = await self._db.pool.fetch(
            "SELECT * FROM decay_alerts WHERE acknowledged = $1 ORDER BY created_at DESC",
            acknowledged,
        )
        return [dict(r) for r in rows]

    async def acknowledge_alert(self, alert_id: int) -> bool:
        result = await self._db.pool.execute(
            "UPDATE decay_alerts SET acknowledged = TRUE WHERE id = $1", alert_id
        )
        return "UPDATE 1" in result

    async def get_performance_trades(
        self, account_id: Optional[str] = None, symbol: Optional[str] = None,
        confidence_tier: Optional[str] = None, regime: Optional[str] = None,
        is_win: Optional[bool] = None, limit: int = 50, offset: int = 0,
    ) -> Dict[str, Any]:
        conditions = []
        params: list = []
        idx = 1

        if account_id:
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
            idx += 1
        if symbol:
            conditions.append(f"symbol = ${idx}")
            params.append(symbol)
            idx += 1
        if confidence_tier:
            conditions.append(f"confidence_tier = ${idx}")
            params.append(confidence_tier)
            idx += 1
        if regime:
            conditions.append(f"regime_at_entry = ${idx}")
            params.append(regime)
            idx += 1
        if is_win is not None:
            conditions.append(f"is_win = ${idx}")
            params.append(is_win)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = await self._db.pool.fetchval(
            f"SELECT COUNT(*) FROM signal_performance {where}", *params
        )

        params.extend([limit, offset])
        rows = await self._db.pool.fetch(
            f"SELECT * FROM signal_performance {where} "
            f"ORDER BY closed_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
        )

        return {"total": int(total or 0), "trades": [dict(r) for r in rows]}
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/signal_analytics_service.py
git commit -m "feat: add signal analytics query service for dashboard data"
```

---

## Task 8: API Router

**Files:**
- Create: `backend/routers/signal_analytics.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Implement the router**

```python
# backend/routers/signal_analytics.py
"""Signal analytics REST endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/signal-analytics", tags=["signal-analytics"])

# Service will be injected via app state
_service = None


def set_service(svc):
    global _service
    _service = svc


def _svc():
    if not _service:
        raise HTTPException(503, "Signal analytics service not initialized")
    return _service


@router.get("/summary")
async def get_summary(
    account_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
):
    return await _svc().get_summary(account_id, start_date, end_date)


@router.get("/win-rate")
async def get_win_rate(
    account_id: Optional[str] = Query(None),
    window: int = Query(20, ge=5, le=100),
):
    return await _svc().get_rolling_win_rate(account_id, window)


@router.get("/calibration")
async def get_calibration(account_id: Optional[str] = Query(None)):
    return await _svc().get_calibration_curve(account_id)


@router.get("/benchmarks")
async def get_benchmarks(
    account_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
):
    return await _svc().get_benchmark_comparison(account_id, start_date, end_date)


@router.get("/regime")
async def get_regime_breakdown(account_id: Optional[str] = Query(None)):
    return await _svc().get_regime_breakdown(account_id)


@router.get("/regime/current")
async def get_current_regimes():
    return await _svc().get_current_regimes()


@router.get("/decay-alerts")
async def get_decay_alerts():
    return await _svc().get_decay_alerts(acknowledged=False)


@router.post("/decay-alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    success = await _svc().acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(404, "Alert not found")
    return {"status": "acknowledged"}


@router.get("/trades")
async def get_trades(
    account_id: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    confidence_tier: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    is_win: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await _svc().get_performance_trades(
        account_id=account_id, symbol=symbol,
        confidence_tier=confidence_tier, regime=regime,
        is_win=is_win, limit=limit, offset=offset,
    )
```

- [ ] **Step 2: Register router in main.py**

In `backend/main.py`, add:

```python
from backend.routers.signal_analytics import router as signal_analytics_router, set_service as set_signal_analytics_service
from backend.services.signal_analytics_service import SignalAnalyticsService

# After db is initialized:
signal_analytics_svc = SignalAnalyticsService(db=db)
set_signal_analytics_service(signal_analytics_svc)
app.include_router(signal_analytics_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/signal_analytics.py backend/main.py
git commit -m "feat: add signal analytics API router with all endpoints"
```

---

## Task 9: Register Regime Classifier in Scheduler

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add regime classifier loop to scheduler**

In `backend/scheduler.py`, in the `SnapshotScheduler` class:

Add a new parameter `regime_fn: Optional[Callable] = None` to `__init__` and store it. Add a `_regime_task` and a `_regime_loop` method:

```python
async def _regime_loop(self) -> None:
    """Classify market regimes every 15 minutes."""
    if not self._regime_fn:
        return
    try:
        await asyncio.sleep(30)  # Initial delay
    except asyncio.CancelledError:
        return
    while self._running:
        try:
            await self._regime_fn()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("regime_classifier_loop_failed")
        try:
            await asyncio.sleep(900)  # 15 minutes
        except asyncio.CancelledError:
            break
```

In `start()`, add: `self._regime_task = asyncio.create_task(self._regime_loop())`

In `shutdown()`, cancel `self._regime_task`.

- [ ] **Step 2: Wire in main.py**

Create the regime run function and pass to scheduler:

```python
from backend.services.regime_classifier import RegimeClassifier

regime_classifier = RegimeClassifier(db=db, llm_callable=llm_regime_confirm)

async def run_regime_classification():
    # Get symbols from active scheduled scans + open positions
    symbols = await get_active_symbols(db)
    await regime_classifier.run_all(symbols, fetch_candles_fn=fetch_bybit_candles)

scheduler = SnapshotScheduler(..., regime_fn=run_regime_classification)
```

- [ ] **Step 3: Commit**

```bash
git add backend/scheduler.py backend/main.py
git commit -m "feat: register regime classifier as 15-minute periodic task"
```

---

## Task 10: Feedback Loop — Inject Performance Context into Trading Graph

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`

- [ ] **Step 1: Add helper to format performance context**

Add a function near the top of `trading_graph.py`:

```python
def _format_performance_context(perf_rows: list, symbol: str, current_regime: str | None = None) -> str:
    """Format signal_performance rows into context string for LLM injection."""
    if not perf_rows:
        return ""

    lines = [f"Recent signal performance for {symbol}:"]
    for row in perf_rows[:5]:
        outcome = "WIN" if row["is_win"] else "LOSS"
        pnl = row["realized_pnl_pct"] or 0
        duration = row["hold_duration_minutes"] or 0
        regime = row.get("regime_at_entry") or "unknown"
        conf = row.get("confidence_score") or "?"
        direction = (row.get("direction") or "?").upper()
        reason = row.get("close_reason") or "unknown"
        lines.append(
            f"- {direction}, confidence {conf}, regime={regime} → {outcome} {pnl:+.1f}% "
            f"(held {duration}min, closed: {reason})"
        )

    total = len(perf_rows)
    wins = sum(1 for r in perf_rows if r["is_win"])
    win_rate = (wins / total * 100) if total else 0
    avg_hold = sum(r.get("hold_duration_minutes") or 0 for r in perf_rows) / total if total else 0
    lines.append(f"\nRolling stats for {symbol}: {wins}/{total} wins ({win_rate:.0f}%), avg hold {avg_hold:.0f}min")

    # Regime breakdown
    regime_stats: dict = {}
    for r in perf_rows:
        reg = r.get("regime_at_entry") or "unknown"
        regime_stats.setdefault(reg, {"wins": 0, "total": 0})
        regime_stats[reg]["total"] += 1
        if r["is_win"]:
            regime_stats[reg]["wins"] += 1

    if regime_stats:
        best = max(regime_stats.items(), key=lambda x: x[1]["wins"] / max(x[1]["total"], 1))
        worst = min(regime_stats.items(), key=lambda x: x[1]["wins"] / max(x[1]["total"], 1))
        best_wr = best[1]["wins"] / max(best[1]["total"], 1) * 100
        worst_wr = worst[1]["wins"] / max(worst[1]["total"], 1) * 100
        lines.append(f"Best regime: {best[0]} ({best_wr:.0f}%), Worst regime: {worst[0]} ({worst_wr:.0f}%)")

    if current_regime:
        regime_data = regime_stats.get(current_regime, {"wins": 0, "total": 0})
        if regime_data["total"] > 0:
            cr_wr = regime_data["wins"] / regime_data["total"] * 100
            lines.append(f"Performance in CURRENT regime ({current_regime}): {regime_data['wins']}/{regime_data['total']} ({cr_wr:.0f}%)")

    return "\n".join(lines)
```

- [ ] **Step 2: Inject context in create_initial_state**

In the `create_initial_state` method (or wherever the initial state dict is built for crypto analysis), query signal_performance and inject:

```python
# After existing past_context logic, add:
if self.config.get("asset_type") == "crypto":
    try:
        perf_rows = await db.pool.fetch(
            "SELECT * FROM signal_performance WHERE symbol = $1 ORDER BY closed_at DESC LIMIT 20",
            company_name,
        )
        if perf_rows:
            current_regime_row = await db.pool.fetchrow(
                "SELECT regime FROM regime_snapshots WHERE symbol = $1 ORDER BY classified_at DESC LIMIT 1",
                company_name,
            )
            current_regime = current_regime_row["regime"] if current_regime_row else None
            perf_context = _format_performance_context(list(perf_rows), company_name, current_regime)
            # Inject into state for trader and risk manager
            init_state["performance_context"] = perf_context
    except Exception:
        logger.debug("performance_context_fetch_failed", extra={"symbol": company_name})
```

Then in the trader agent and risk manager prompts, append `state.get("performance_context", "")` to their input context.

- [ ] **Step 3: Commit**

```bash
git add tradingagents/graph/trading_graph.py
git commit -m "feat: inject real signal performance feedback into trader and risk manager context"
```

---

## Task 11: Frontend — Signal Analytics Page

**Files:**
- Create: `frontend/src/components/signal-analytics/SignalAnalyticsPage.tsx`
- Create: `frontend/src/components/signal-analytics/KpiCards.tsx`
- Create: `frontend/src/components/signal-analytics/CalibrationChart.tsx`
- Create: `frontend/src/components/signal-analytics/RollingWinRateChart.tsx`
- Create: `frontend/src/components/signal-analytics/BenchmarkChart.tsx`
- Create: `frontend/src/components/signal-analytics/RegimeBreakdownChart.tsx`
- Create: `frontend/src/components/signal-analytics/DecayAlertBanner.tsx`
- Create: `frontend/src/components/signal-analytics/TradeTable.tsx`
- Modify: `frontend/src/routes/route-tree.tsx`

- [ ] **Step 1: Create KpiCards component**

```typescript
// frontend/src/components/signal-analytics/KpiCards.tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface SummaryData {
  total_trades: number;
  win_rate: number;
  avg_pnl_pct: number;
  total_pnl: number;
  current_streak: string;
  active_alerts: number;
}

export function KpiCards({ data }: { data: SummaryData | null }) {
  if (!data) return null;

  const cards = [
    { title: "Total Signals", value: data.total_trades.toString() },
    { title: "Win Rate", value: `${(data.win_rate * 100).toFixed(1)}%` },
    { title: "Avg PnL", value: `${data.avg_pnl_pct > 0 ? "+" : ""}${data.avg_pnl_pct.toFixed(2)}%` },
    { title: "Total PnL", value: `$${data.total_pnl.toFixed(2)}` },
    { title: "Streak", value: data.current_streak },
    { title: "Alerts", value: data.active_alerts.toString() },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {cards.map((c) => (
        <Card key={c.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{c.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{c.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create CalibrationChart component**

```typescript
// frontend/src/components/signal-analytics/CalibrationChart.tsx
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface CalibrationData {
  tier: string;
  total: number;
  wins: number;
  win_rate: number;
}

export function CalibrationChart({ data }: { data: CalibrationData[] }) {
  const chartData = data.map((d) => ({
    name: d.tier.charAt(0).toUpperCase() + d.tier.slice(1),
    winRate: d.win_rate * 100,
    trades: d.total,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Confidence Calibration</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
            <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
            <ReferenceLine y={50} stroke="#888" strokeDasharray="3 3" label="50%" />
            <Bar dataKey="winRate" fill="#3b82f6" name="Win Rate" />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Create RollingWinRateChart component**

```typescript
// frontend/src/components/signal-analytics/RollingWinRateChart.tsx
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface WinRatePoint {
  date: string;
  win_rate: number;
  trade_number: number;
}

export function RollingWinRateChart({ data }: { data: WinRatePoint[] }) {
  const chartData = data.map((d) => ({
    trade: d.trade_number,
    winRate: d.win_rate * 100,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rolling Win Rate (20-trade window)</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="trade" label={{ value: "Trade #", position: "bottom" }} />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
            <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
            <ReferenceLine y={50} stroke="#ef4444" strokeDasharray="3 3" label="50%" />
            <Line type="monotone" dataKey="winRate" stroke="#3b82f6" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Create BenchmarkChart component**

```typescript
// frontend/src/components/signal-analytics/BenchmarkChart.tsx
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface BenchmarkPoint {
  trade_number: number;
  system_pnl: number;
  buy_and_hold: number;
  random_expected: number;
}

export function BenchmarkChart({ data }: { data: BenchmarkPoint[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cumulative PnL vs Benchmarks</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="trade_number" label={{ value: "Trade #", position: "bottom" }} />
            <YAxis tickFormatter={(v) => `${v}%`} />
            <Tooltip formatter={(v: number) => `${v.toFixed(2)}%`} />
            <Legend />
            <Line type="monotone" dataKey="system_pnl" stroke="#3b82f6" name="System" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="buy_and_hold" stroke="#6b7280" name="Buy & Hold" strokeDasharray="5 5" dot={false} />
            <Line type="monotone" dataKey="random_expected" stroke="#ef4444" name="Random" strokeDasharray="3 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: Create RegimeBreakdownChart component**

```typescript
// frontend/src/components/signal-analytics/RegimeBreakdownChart.tsx
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RegimeData {
  regime: string;
  total: number;
  wins: number;
  win_rate: number;
  avg_pnl_pct: number;
}

export function RegimeBreakdownChart({ data }: { data: RegimeData[] }) {
  const chartData = data.map((d) => ({
    name: d.regime.replace("_", " "),
    winRate: d.win_rate * 100,
    avgPnl: d.avg_pnl_pct,
    trades: d.total,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Performance by Market Regime</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis yAxisId="left" tickFormatter={(v) => `${v}%`} />
            <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => `${v}%`} />
            <Tooltip />
            <Legend />
            <Bar yAxisId="left" dataKey="winRate" fill="#3b82f6" name="Win Rate %" />
            <Bar yAxisId="right" dataKey="avgPnl" fill="#10b981" name="Avg PnL %" />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: Create DecayAlertBanner component**

```typescript
// frontend/src/components/signal-analytics/DecayAlertBanner.tsx
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { AlertTriangle, XCircle } from "lucide-react";

interface DecayAlert {
  id: number;
  alert_type: string;
  severity: string;
  message: string;
  created_at: string;
}

export function DecayAlertBanner({
  alerts,
  onAcknowledge,
}: {
  alerts: DecayAlert[];
  onAcknowledge: (id: number) => void;
}) {
  if (!alerts.length) return null;

  return (
    <div className="space-y-2">
      {alerts.map((alert) => (
        <Alert
          key={alert.id}
          variant={alert.severity === "critical" ? "destructive" : "default"}
          className="flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            {alert.severity === "critical" ? (
              <XCircle className="h-4 w-4" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )}
            <AlertDescription>{alert.message}</AlertDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={() => onAcknowledge(alert.id)}>
            Dismiss
          </Button>
        </Alert>
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Create TradeTable component**

```typescript
// frontend/src/components/signal-analytics/TradeTable.tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TradeRow {
  id: string;
  closed_at: string;
  symbol: string;
  direction: string;
  confidence_score: number;
  confidence_tier: string;
  regime_at_entry: string;
  realized_pnl_pct: number;
  hold_duration_minutes: number;
  close_reason: string;
  benchmark_bnh_pnl_pct: number;
  is_win: boolean;
}

export function TradeTable({ trades }: { trades: TradeRow[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Signal Performance History</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="p-2">Date</th>
                <th className="p-2">Symbol</th>
                <th className="p-2">Dir</th>
                <th className="p-2">Conf</th>
                <th className="p-2">Regime</th>
                <th className="p-2">PnL%</th>
                <th className="p-2">Hold</th>
                <th className="p-2">Close</th>
                <th className="p-2">vs B&H</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b hover:bg-muted/50">
                  <td className="p-2">{new Date(t.closed_at).toLocaleDateString()}</td>
                  <td className="p-2 font-mono">{t.symbol}</td>
                  <td className="p-2">{t.direction?.toUpperCase()}</td>
                  <td className="p-2">{t.confidence_score ?? "-"}</td>
                  <td className="p-2">{t.regime_at_entry ?? "-"}</td>
                  <td className={`p-2 font-mono ${t.is_win ? "text-green-500" : "text-red-500"}`}>
                    {t.realized_pnl_pct > 0 ? "+" : ""}{t.realized_pnl_pct?.toFixed(2)}%
                  </td>
                  <td className="p-2">{t.hold_duration_minutes}m</td>
                  <td className="p-2">{t.close_reason}</td>
                  <td className="p-2 font-mono">
                    {(t.realized_pnl_pct - t.benchmark_bnh_pnl_pct) > 0 ? "+" : ""}
                    {(t.realized_pnl_pct - (t.benchmark_bnh_pnl_pct || 0)).toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 8: Create main SignalAnalyticsPage**

```typescript
// frontend/src/components/signal-analytics/SignalAnalyticsPage.tsx
import { useEffect, useState } from "react";
import { KpiCards } from "./KpiCards";
import { CalibrationChart } from "./CalibrationChart";
import { RollingWinRateChart } from "./RollingWinRateChart";
import { BenchmarkChart } from "./BenchmarkChart";
import { RegimeBreakdownChart } from "./RegimeBreakdownChart";
import { DecayAlertBanner } from "./DecayAlertBanner";
import { TradeTable } from "./TradeTable";

const API_BASE = import.meta.env.VITE_API_URL || "";

async function fetchJson(path: string) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export function SignalAnalyticsPage() {
  const [summary, setSummary] = useState(null);
  const [winRate, setWinRate] = useState([]);
  const [calibration, setCalibration] = useState([]);
  const [benchmarks, setBenchmarks] = useState([]);
  const [regimes, setRegimes] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchJson("/signal-analytics/summary"),
      fetchJson("/signal-analytics/win-rate"),
      fetchJson("/signal-analytics/calibration"),
      fetchJson("/signal-analytics/benchmarks"),
      fetchJson("/signal-analytics/regime"),
      fetchJson("/signal-analytics/decay-alerts"),
      fetchJson("/signal-analytics/trades?limit=50"),
    ])
      .then(([sum, wr, cal, bench, reg, al, tr]) => {
        setSummary(sum);
        setWinRate(wr);
        setCalibration(cal);
        setBenchmarks(bench);
        setRegimes(reg);
        setAlerts(al);
        setTrades(tr.trades || []);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleAcknowledge = async (id: number) => {
    await fetch(`${API_BASE}/signal-analytics/decay-alerts/${id}/acknowledge`, { method: "POST" });
    setAlerts((prev) => prev.filter((a: any) => a.id !== id));
  };

  if (loading) return <div className="p-6">Loading signal analytics...</div>;

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Signal Analytics</h1>
      <DecayAlertBanner alerts={alerts} onAcknowledge={handleAcknowledge} />
      <KpiCards data={summary} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CalibrationChart data={calibration} />
        <RollingWinRateChart data={winRate} />
      </div>
      <BenchmarkChart data={benchmarks} />
      <RegimeBreakdownChart data={regimes} />
      <TradeTable trades={trades} />
    </div>
  );
}
```

- [ ] **Step 9: Add route to route-tree.tsx**

In `frontend/src/routes/route-tree.tsx`, add lazy import:

```typescript
const SignalAnalyticsPage = lazy(() =>
  import("@/components/signal-analytics/SignalAnalyticsPage").then((module) => ({
    default: module.SignalAnalyticsPage,
  })),
);
```

Add route wrapper function:

```typescript
function SignalAnalyticsPageComponent() {
  return (
    <RouteSuspense>
      <SignalAnalyticsPage />
    </RouteSuspense>
  );
}
```

Create route:

```typescript
const signalAnalyticsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signal-analytics",
  component: SignalAnalyticsPageComponent,
});
```

Add to `routeTree.addChildren([..., signalAnalyticsRoute])`.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/signal-analytics/ frontend/src/routes/route-tree.tsx
git commit -m "feat: add signal analytics dashboard page with charts and trade table"
```

---

## Task 12: Integration Test for API Endpoints

**Files:**
- Create: `tests/test_signal_analytics_router.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_signal_analytics_router.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_service():
    svc = AsyncMock()
    svc.get_summary.return_value = {
        "total_trades": 50, "win_rate": 0.52, "avg_pnl_pct": 0.3,
        "total_pnl": 150.0, "current_streak": "3W", "active_alerts": 1,
    }
    svc.get_rolling_win_rate.return_value = [
        {"date": "2026-05-01T00:00:00Z", "win_rate": 0.55, "trade_number": 20}
    ]
    svc.get_calibration_curve.return_value = [
        {"tier": "high", "total": 20, "wins": 12, "win_rate": 0.6}
    ]
    svc.get_benchmark_comparison.return_value = [
        {"trade_number": 1, "system_pnl": 1.5, "buy_and_hold": 0.8, "random_expected": 0.0}
    ]
    svc.get_regime_breakdown.return_value = [
        {"regime": "trending_up", "total": 15, "wins": 10, "win_rate": 0.67, "avg_pnl_pct": 1.2}
    ]
    svc.get_current_regimes.return_value = []
    svc.get_decay_alerts.return_value = []
    svc.acknowledge_alert.return_value = True
    svc.get_performance_trades.return_value = {"total": 0, "trades": []}
    return svc


@pytest.mark.asyncio
async def test_summary_endpoint(mock_service):
    from backend.routers.signal_analytics import router, set_service
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    set_service(mock_service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/signal-analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 50
        assert data["win_rate"] == 0.52


@pytest.mark.asyncio
async def test_acknowledge_alert(mock_service):
    from backend.routers.signal_analytics import router, set_service
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    set_service(mock_service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/signal-analytics/decay-alerts/1/acknowledge")
        assert resp.status_code == 200
        mock_service.acknowledge_alert.assert_called_once_with(1)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_signal_analytics_router.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_signal_analytics_router.py
git commit -m "test: add integration tests for signal analytics API endpoints"
```

---

## Task 13: Regime Context Injection into Analyst Prompts

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`

- [ ] **Step 1: Inject regime context for analysts**

In the `create_initial_state` method, after the performance context injection (from Task 10), add regime injection for analysts:

```python
# Inject current regime context for analyst agents
if self.config.get("asset_type") == "crypto":
    try:
        regime_row = await db.pool.fetchrow(
            "SELECT regime, adx, atr_pct, bb_width_pct, llm_confirmed, llm_regime "
            "FROM regime_snapshots WHERE symbol = $1 ORDER BY classified_at DESC LIMIT 1",
            company_name,
        )
        if regime_row:
            regime_context = (
                f"Current market regime for {company_name}: {regime_row['regime']}\n"
                f"Indicators: ADX={float(regime_row['adx']):.1f} (trend strength), "
                f"ATR%={float(regime_row['atr_pct']):.2f} (volatility), "
                f"BB Width={float(regime_row['bb_width_pct']):.2f}%\n"
                f"LLM confirmed: {'yes' if regime_row['llm_confirmed'] else 'no'} "
                f"(LLM classified as: {regime_row['llm_regime'] or 'N/A'})\n\n"
                f"Adjust analysis: trend-following signals carry more weight in trending regimes, "
                f"mean-reversion signals in ranging regimes. In volatile regimes, widen expected "
                f"ranges and lower confidence unless conviction is very high."
            )
            init_state["regime_context"] = regime_context
    except Exception:
        logger.debug("regime_context_fetch_failed", extra={"symbol": company_name})
```

Then ensure the analyst prompts include `state.get("regime_context", "")` in their input context.

- [ ] **Step 2: Commit**

```bash
git add tradingagents/graph/trading_graph.py
git commit -m "feat: inject regime context into analyst agent prompts for regime-aware analysis"
```

---

## Summary

| Task | Description | Key Deliverable |
|------|-------------|-----------------|
| 1 | Database migration | 3 new tables + scan_result_id column |
| 2 | Wire scan_result_id | Link trades to their originating scan results |
| 3 | Materializer service | Compute + store signal performance on trade close |
| 4 | Hook into close flow | Trigger materialization automatically |
| 5 | Decay detector | Rolling window alerts for quality degradation |
| 6 | Regime classifier | Periodic indicator + LLM regime classification |
| 7 | Analytics query service | Aggregation queries for dashboard |
| 8 | API router | REST endpoints for frontend |
| 9 | Scheduler registration | Regime classifier runs every 15min |
| 10 | Feedback loop | Inject real performance data into trader/risk prompts |
| 11 | Frontend page | Full dashboard with charts and table |
| 12 | Integration tests | API endpoint validation |
| 13 | Regime analyst injection | Analysts adapt to current market regime |
