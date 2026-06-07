"""Golden-snapshot regression for AutoTradeExecutor._try_trade (TASK-0.1, FR-001).

The load-bearing default-off guarantee: with the 3 regime features all OFF, the
executor's decisions (placed trades + skip reasons, in order) must be byte-identical
to current behavior. This harness drives _try_trade through evaluate_result over a
deterministic recorded scan with a stubbed place_trade (no Bybit), capturing a
manifest, and asserts it equals a stored golden built on first run.

After the gate-chain extraction (TASK-0.7) and every later phase, this test must
stay green for the all-OFF config — that is the proof the refactor changed nothing.
"""

import asyncio
import json
import os

import pytest

from backend.services.auto_trade_service import AutoTradeExecutor


# ── Deterministic recorded scan (a handful of signals across mixed outcomes) ──
RECORDED_RESULTS = [
    # status, ticker, direction, confidence, score
    {"status": "completed", "ticker": "BTC", "direction": "sell", "confidence": "high", "score": 8, "id": "r1"},
    {"status": "completed", "ticker": "ETH", "direction": "buy", "confidence": "moderate", "score": 6, "id": "r2"},
    {"status": "completed", "ticker": "SOL", "direction": "hold", "confidence": "low", "score": 0, "id": "r3"},
    {"status": "completed", "ticker": "DOGE", "direction": "sell", "confidence": "high", "score": 7, "id": "r4"},
    {"status": "completed", "ticker": "XRP", "direction": "sell", "confidence": "low", "score": 2, "id": "r5"},
    {"status": "failed", "ticker": "ADA", "direction": "sell", "confidence": "high", "score": 8, "id": "r6"},
]

ALL_OFF_CONFIG = {
    "account_id": "golden-acct",
    "leverage": 20,
    "capital_pct": 5,
    "take_profit_pct": 150,
    "stop_loss_pct": 100,
    "min_score": 6,
    "confidence_filter": "any",
    "signal_sides": "both",
    "max_trades": 10,
    "max_drawdown_pct": 50,
    "execution_mode": "immediate",
    # all regime features absent => default-off
}

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "regime", "golden_manifest.json")


class _StubAccounts:
    """Records place_trade calls and returns synthetic fills; no network."""

    def __init__(self):
        self.calls = []

    async def get_balance(self, account_id):
        return 1000.0

    async def get_wallet(self, account_id):
        return {"available": 1000.0, "equity": 1000.0}

    async def get_mark_price(self, account_id, symbol):
        return 100.0

    async def place_trade(self, **kwargs):
        self.calls.append({k: kwargs.get(k) for k in (
            "symbol", "signal_direction", "trade_direction", "leverage",
            "take_profit_pct", "stop_loss_pct", "capital_pct", "strategy_kind")})
        return {"trade_id": f"t{len(self.calls)}", "side": kwargs.get("signal_direction")}


def _build_executor():
    ex = AutoTradeExecutor(_StubAccounts())
    ex.init_configs([dict(ALL_OFF_CONFIG)])
    # seed base capital so the no_balance gate doesn't fire
    for st in ex._state.values():
        st.base_capital = 1000.0
    return ex


async def _capture_manifest():
    ex = _build_executor()
    manifest = []
    captured = []

    # Intercept _emit_decision to record skip/decision tuples deterministically.
    orig_emit = ex._emit_decision

    def _spy(account_id, phase, symbol, decision, reason_code, result, **detail):
        captured.append({"symbol": symbol, "decision": decision, "reason": str(reason_code)})
        return orig_emit(account_id, phase, symbol, decision, reason_code, result, **detail)

    ex._emit_decision = _spy  # type: ignore

    for result in RECORDED_RESULTS:
        try:
            await ex._try_trade(list(ex._state.values())[0], result, phase="batch")
        except Exception as e:  # capture errors deterministically rather than abort
            captured.append({"symbol": result.get("ticker"), "decision": "exception", "reason": type(e).__name__})

    placed = ex._accounts.calls
    return {"decisions": captured, "placed": placed}


@pytest.mark.asyncio
async def test_all_off_decisions_byte_identical():
    manifest = await _capture_manifest()

    if not os.path.exists(GOLDEN_PATH):
        os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
        with open(GOLDEN_PATH, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        pytest.skip("golden manifest generated on first run — re-run to assert against it")

    with open(GOLDEN_PATH) as f:
        golden = json.load(f)

    assert manifest == golden, (
        "all-off _try_trade decisions diverged from the golden snapshot — a refactor "
        "changed default-off behavior (FR-001 violation)"
    )
