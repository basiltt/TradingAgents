from datetime import datetime, timezone
from backend.services.backtest_engine import BacktestEngine

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _signal(ticker, direction, score, analysis_price, t):
    return {"ticker": ticker, "direction": direction, "score": score,
            "analysis_price": analysis_price, "signal_time": t, "scan_id": "s1",
            "id": 1, "confidence": "high", "analysis_completed_at": None}

def _5m(t, o): return {"open_time": t, "open": o, "high": o, "low": o, "close": o, "volume": 1.0}
def _1m(t, o): return {"open_time": t, "open": o, "high": o, "low": o, "close": o, "volume": 1.0}

def test_drift_uses_5m_open_when_no_fine_window():
    """Sell, analysis 0.00855; 5m next-bar-open 0.009015 = +5.4% (price rose, move
    NOT consumed for a sell, so admitted). Establishes the 5m baseline path."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    eng._fine_klines = {}                      # NO drilldown
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # bar-aligned to a 1m boundary
    sig = _signal("BLESSUSDT", "sell", -7, 0.00855, t)
    # Entry-bar 5m candle (00:05) so _drift_reference_price can resolve bar_open;
    # next-bar-open (00:10) is the 5m reference price the gate reads.
    klines = {"BLESSUSDT": [_5m(_dt("2026-06-08T00:05:00"), 0.00860),
                            _5m(_dt("2026-06-08T00:10:00"), 0.009015)]}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    # A sell with price UP is admitted by the gate (drift_pct +5.4% is not < -3)
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is True

def test_drift_uses_1m_open_when_fine_window_present():
    """A BUY whose 5m next-bar-open trips the cap (+5.4% > 3) yet whose 1m open AT the
    signal instant (+1.0%) does NOT. With a fine window the 1m price is used → admitted.

    NOTE: `_drift_reference_price` returns the 1m candle with open_time >= current_time,
    so the signal instant MUST be a 1m boundary (00:08:00) for the 101.0 candle (its
    open_time == current_time) to be the one selected."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # 1m-aligned signal instant
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")       # the 5m bar covering 00:08:00
    # Entry-bar 5m candle (so bar_open resolves) + next-bar-open at +5.4%.
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:05:00"), 100.0),
                          _5m(_dt("2026-06-08T00:10:00"), 105.4)]}
    # 1m window for the entry bar: the 00:08:00 candle (== current_time) opens at 101.0.
    eng._fine_klines = {"FOOUSDT": {int(bar_open.timestamp()): [
        _1m(_dt("2026-06-08T00:05:00"), 100.5),
        _1m(_dt("2026-06-08T00:08:00"), 101.0),   # open_time == current_time → selected
        _1m(_dt("2026-06-08T00:09:00"), 101.2),
    ]}}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    # 5m path would REJECT (+5.4% > 3); 1m path ADMITS (+1.0% <= 3)
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is True

def test_drift_1m_still_rejects_genuine_drift():
    """If even the 1m price at the signal instant is past the cap, still reject."""
    eng = BacktestEngine()
    eng._instrument_info = {}
    eng._scan_contexts = {}; eng._ctx = None; eng._mr_mean = None
    from backend.services.backtest_engine import SimulationState
    state = SimulationState(wallet_balance=1000, sizing_capital=1000, slippage_bps=0)
    state.cycle_start_equity = 1000
    t = _dt("2026-06-08T00:08:00")              # 1m-aligned signal instant
    sig = _signal("FOOUSDT", "buy", 7, 100.0, t)
    bar_open = _dt("2026-06-08T00:05:00")
    klines = {"FOOUSDT": [_5m(_dt("2026-06-08T00:05:00"), 100.0),
                          _5m(_dt("2026-06-08T00:10:00"), 105.4)]}
    eng._fine_klines = {"FOOUSDT": {int(bar_open.timestamp()): [
        _1m(_dt("2026-06-08T00:08:00"), 104.0),   # +4.0% > 3 cap
    ]}}
    cfg = {"max_price_drift_pct": 3, "min_score": 0, "confidence_filter": "any"}
    assert eng._apply_filter_chain(cfg, sig, state, t, klines, relaxed=False) is False
