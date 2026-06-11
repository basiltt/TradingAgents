"""Replay-mode runner for account-ledger backtests plus engine diagnostics.

The displayed replay result is built from the account's actual scanner trade ledger
so a historical account audit can match live. In parallel, the same live selection is
replayed through BacktestEngine and stored as a live-vs-engine diagnostic comparison.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import run_cycles_isolated, build_report
from backend.diagnostics.parity.models import Cycle

# Bounds so a replay over a large/live account can't OOM (klines) or flood the
# exchange (per-trade 1m drill fetches) or write an unbounded comparison blob.
_MAX_CYCLES = 200
_MAX_SYMBOLS = 300


class ReplayError(Exception):
    """Replay cannot produce a meaningful comparison (no cycles, or over a bound).

    Mapped by the service to a failed run with this message, so the user sees WHY
    rather than a silent empty/garbage result.
    """


def _correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)


def _build_live_ledger_result(cycles: list[Cycle]) -> dict[str, Any]:
    """Build the displayed replay result from the account's actual closed trades.

    Replay/selective mode is an account-audit path, not a predictive optimizer run:
    trade membership, fills, exits, fees, and realized PnL come from the exchange
    ledger. The pure candle engine still runs and is persisted in replay_comparison
    as a diagnostic, but the run's headline metrics must match the live account.
    """
    return _build_live_ledger_result_from_start(cycles, cycles[0].base_capital if cycles else 0.0)


def _build_live_ledger_result_from_start(cycles: list[Cycle], starting_capital: float) -> dict[str, Any]:
    if not cycles:
        return {"trades": [], "equity_curve": [], "starting_capital": starting_capital}

    trades: list[dict[str, Any]] = []
    for cycle in cycles:
        for live in cycle.live_trades:
            entry = float(live.entry_price)
            exit_price = float(live.exit_price) if live.exit_price is not None else None
            qty = float(live.qty or 0.0)
            leverage = int(live.leverage or 1)
            margin = (entry * qty / leverage) if entry > 0 and qty > 0 and leverage > 0 else 0.0
            pnl = live.account_pnl
            pnl_pct = (pnl / margin * 100.0) if margin > 0 else live.realized_pnl_pct
            trades.append({
                "symbol": live.symbol,
                "side": live.side,
                "entry_price": entry,
                "exit_price": exit_price,
                "qty": qty,
                "leverage": leverage,
                "entry_time": live.opened_at,
                "exit_time": live.closed_at,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "fees_paid": live.fees,
                "close_reason": live.close_reason,
                "mfe_pct": None,
                "mae_pct": None,
                "signal_score": None,
                "signal_confidence": None,
                "scan_id": cycle.scan_id,
                "strategy_kind": live.strategy_kind or "trend",
            })
    trades.sort(key=lambda t: (t.get("exit_time") is None, t.get("exit_time") or t.get("entry_time")))

    first_open = min(
        (t.opened_at for c in cycles for t in c.live_trades if t.opened_at is not None),
        default=cycles[0].signal_time,
    )
    equity = starting_capital
    peak = starting_capital
    equity_curve = [{"ts": first_open, "equity": equity, "drawdown_pct": 0.0}]
    for cycle in cycles:
        equity += cycle.live_net_pnl
        peak = max(peak, equity)
        closed_times = [t.closed_at for t in cycle.live_trades if t.closed_at is not None]
        ts = max(closed_times) if closed_times else cycle.signal_time
        drawdown_pct = round(((equity - peak) / peak) * 100.0, 4) if peak > 0 else 0.0
        equity_curve.append({"ts": ts, "equity": equity, "drawdown_pct": drawdown_pct})

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "starting_capital": starting_capital,
    }


async def run_replay(
    data_access: Any, kline_cache: Any, account_id: str,
    start: datetime, end: datetime, base_config: dict[str, Any],
    drilldown: bool = True, run_sync: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (result_dict, replay_comparison).

    result_dict mimics SimulationResult enough for persistence and is built from the
    live account ledger: {trades, equity_curve}. replay_comparison keeps the pure
    candle-engine replay for diagnostics.

    `run_sync`, when provided, is an awaitable wrapper (e.g. loop.run_in_executor) that
    runs the CPU-bound, synchronous cycle-replay OFF the event loop. Called as
    `await run_sync(fn)` where fn is a zero-arg callable returning the engine trades.
    When None, the simulation runs inline (fine for tests / small replays).

    Raises ReplayError when there are no pinnable cycles, or the work exceeds the
    cycle/symbol bounds — so the service can fail the run with a clear reason rather
    than persist an empty/garbage comparison.
    """
    trade_rows = await data_access.fetch_live_trades(account_id, start, end)
    cycles = build_cycles(trade_rows)
    excluded = {}
    if hasattr(data_access, "fetch_excluded_counts"):
        excluded = await data_access.fetch_excluded_counts(account_id, start, end)

    if not cycles:
        raise ReplayError(
            "No scanner trades to replay in this window for this account. "
            "(Replay excludes AI-Manager-closed and non-scanner trades.) "
            f"Excluded in window: {excluded or 'n/a'}.")
    if len(cycles) > _MAX_CYCLES:
        raise ReplayError(
            f"Replay window has {len(cycles)} cycles (max {_MAX_CYCLES}). "
            "Narrow the date range.")

    signals = await data_access.fetch_signals([c.scan_id for c in cycles])
    pinned, missing = pin_signals(signals, cycles, return_missing=True)

    symbols = sorted({s["ticker"] for s in pinned})
    if len(symbols) > _MAX_SYMBOLS:
        raise ReplayError(
            f"Replay touches {len(symbols)} symbols (max {_MAX_SYMBOLS}). "
            "Narrow the date range.")

    signals_by_scan: dict[str, list] = {}
    for s in pinned:
        signals_by_scan.setdefault(s["scan_id"], []).append(s)

    klines = await data_access.fetch_klines(kline_cache, symbols, start, end, "5m")
    # Coverage guard: a pinned symbol with NO cached candles can't be simulated, so the
    # engine skips it and the comparison silently under-trades. Count them for disclosure.
    symbols_no_kline = sum(1 for s in symbols if not klines.get(s))

    cfg = dict(base_config)
    cfg.update({"date_range_start": start, "date_range_end": end})

    # CONTIGUOUS per-cycle 1m drill-down over each cycle's ACTIVE span
    # [first signal .. synchronized close], with small padding. Contiguous coverage
    # (not just isolated entry/exit bars) is required so the engine's book-wide equity
    # walk (drawdown / target-goal) has 1m for EVERY open position at the firing bar —
    # the portfolio close can fire on an INTERMEDIATE bar that an entry/exit-only scope
    # leaves at 5m, costing parity (validated: scoped -13% vs contiguous -8%). The fetch
    # stays bounded because cycles are short (minutes–hours) and _MAX_CYCLES caps the
    # count; the 24h max-duration cycles are the only long ones. Skipped without a cache.
    fine_by_scan: dict[str, Any] | None = None
    if drilldown and kline_cache is not None and hasattr(data_access, "build_fine_klines"):
        from datetime import timedelta
        fine_by_scan = {}
        for c in cycles:
            csyms = sorted({t.symbol for t in c.live_trades})
            closes = [t.closed_at for t in c.live_trades if t.closed_at is not None]
            if not csyms or not closes:
                continue
            opens = [t.opened_at for t in c.live_trades if t.opened_at is not None]
            window_start = (min(opens) if opens else c.signal_time)
            fine_by_scan[c.scan_id] = await data_access.build_fine_klines(
                kline_cache, csyms, window_start - timedelta(hours=1),
                max(closes) + timedelta(hours=1), sim_interval_seconds=300)

    # Run the synchronous per-cycle engine replay OFF the event loop when a run_sync
    # wrapper is supplied (the service passes loop.run_in_executor). The engine is
    # CPU-bound; running it inline would block all other async request handling.
    def _do_cycles() -> list[dict[str, Any]]:
        return run_cycles_isolated(
            BacktestEngine(), cycles, signals_by_scan, klines, cfg,
            fine_klines_by_scan=fine_by_scan)

    if run_sync is not None:
        engine_trades = await run_sync(_do_cycles)
    else:
        engine_trades = _do_cycles()

    # Replay is an account-ledger audit. Its starting capital comes from the first
    # live cycle's stored base_capital, not the generic form default, so users do not
    # have to guess the historical wallet balance.
    starting_capital = cycles[0].base_capital
    report = build_report(cycles, engine_trades, starting_capital, tolerance_pct=1.0)

    live_pnls = [cc.live_net_pnl for cc in report.cycles]
    bt_pnls = [cc.backtest_net_pnl for cc in report.cycles]
    comparison = {
        "n_cycles": len(report.cycles),
        "pinned_trades": len(pinned),
        # Data-integrity disclosure — fidelity is computed over the pinned set only.
        "missing_pins": len(missing),
        "excluded_trades": excluded,
        "symbols_no_kline": symbols_no_kline,
        "live_final_equity": report.live_final_equity,
        "backtest_final_equity": report.backtest_final_equity,
        "final_equity_delta_pct": report.final_equity_delta_pct,
        "pnl_correlation": _correlation(live_pnls, bt_pnls),
        "directional_agreement": sum(
            1 for a, b in zip(live_pnls, bt_pnls) if (a >= 0) == (b >= 0)),
        "cycles": [
            {"scan_id": cc.scan_id, "signal_time": cc.signal_time,
             "live_net_pnl": cc.live_net_pnl, "backtest_net_pnl": cc.backtest_net_pnl,
             "live_equity_after": cc.live_equity_after,
             "backtest_equity_after": cc.backtest_equity_after,
             "delta_pct": cc.delta_pct}
            for cc in report.cycles
        ],
    }
    result = _build_live_ledger_result(cycles)
    return result, comparison
