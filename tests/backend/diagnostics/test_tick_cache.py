from datetime import datetime, timezone
from backend.diagnostics.parity.tick_cache import TickSeries, price_at, merged_upnl_crossing


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_tick_series_price_at_returns_last_trade_at_or_before():
    ts = TickSeries(
        timestamps=[1.0, 2.0, 3.0, 4.0],
        prices=[100.0, 101.0, 102.0, 103.0],
    )
    # exactly on a tick
    assert price_at(ts, 3.0) == 102.0
    # between ticks -> last at/before
    assert price_at(ts, 3.5) == 102.0
    # before first -> None
    assert price_at(ts, 0.5) is None
    # after last -> last
    assert price_at(ts, 99.0) == 103.0


def test_merged_upnl_crossing_finds_first_threshold_tick():
    # Two short positions; price drops are GOOD (uPnL up). base=1000.
    # pos A: entry 100, qty 10  -> uPnL = (100-mark)*10
    # pos B: entry 50,  qty 20  -> uPnL = (50-mark)*20
    # Build ticks where combined uPnL rises and crosses +150 (15% of 1000).
    a = TickSeries([1.0, 2.0, 3.0], [100.0, 99.0, 95.0])   # uPnL_A: 0,10,50
    b = TickSeries([1.0, 2.5, 3.0], [50.0, 49.0, 48.0])    # uPnL_B: 0,20,40
    positions = [
        {"symbol": "A", "side": "Sell", "entry_price": 100.0, "qty": 10.0, "ticks": a},
        {"symbol": "B", "side": "Sell", "entry_price": 50.0, "qty": 20.0, "ticks": b},
    ]
    # threshold +150 absolute uPnL. Walk merged ticks chronologically:
    #  t=1.0: A=0,  B=0   -> 0
    #  t=2.0: A=10, B=0   -> 10
    #  t=2.5: A=10, B=20  -> 30
    #  t=3.0: A=50, B=40  -> 90   (never reaches 150)
    res = merged_upnl_crossing(positions, threshold=150.0, direction="rise")
    assert res is None  # never crosses

    # Lower threshold to +80 -> crosses at t=3.0 (uPnL 90 >= 80)
    res2 = merged_upnl_crossing(positions, threshold=80.0, direction="rise")
    assert res2 is not None
    assert res2["time"] == 3.0
    # exit prices at the crossing instant
    assert res2["exit_prices"]["A"] == 95.0
    assert res2["exit_prices"]["B"] == 48.0


def test_merged_upnl_crossing_drawdown_direction():
    # Short position that goes against us (price rises). drawdown crossing at -100.
    a = TickSeries([1.0, 2.0, 3.0], [100.0, 105.0, 112.0])  # uPnL=(100-mark)*10: 0,-50,-120
    positions = [{"symbol": "A", "side": "Sell", "entry_price": 100.0, "qty": 10.0, "ticks": a}]
    res = merged_upnl_crossing(positions, threshold=-100.0, direction="drop")
    assert res is not None
    assert res["time"] == 3.0          # -120 <= -100 first at t=3
    assert res["exit_prices"]["A"] == 112.0
