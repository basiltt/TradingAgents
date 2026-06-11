"""Async DB reads for the parity harness (local DB, read-only)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

# Reuse the production signal/kline loaders' query shape so the engine gets
# byte-identical inputs to a real backtest. Window params are datetime objects
# (asyncpg requires real datetimes for timestamptz comparisons).
# Pinnable live trades = scanner-opened, NOT AI-Manager-closed (the backtest engine
# excludes the AI Manager, so an AI-closed trade's exit can't be reproduced and would
# depress the fidelity comparison). LEFT JOIN scan_results/scans so a scanner trade
# whose scan row is archived/missing still surfaces (scan_id NULL) rather than being
# silently dropped by an inner join — the caller groups only rows with a scan_id and
# can report the remainder. Window is on opened_at (trade entry).
_TRADES_SQL = """
    SELECT t.symbol, t.side, t.net_pnl, t.close_reason, t.entry_price, t.exit_price,
           t.scan_result_id, t.status, t.base_capital, t.opened_at, t.closed_at,
           t.source, t.ai_closed, t.qty, t.leverage, t.fees, t.realized_pnl_pct,
           t.strategy_kind, cpr.closed_pnl AS exchange_closed_pnl,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           sr.scan_id AS scan_id
    FROM trades t
    LEFT JOIN scan_results sr ON sr.id = t.scan_result_id
    LEFT JOIN scans s ON s.scan_id = sr.scan_id
    LEFT JOIN LATERAL (
        SELECT c.closed_pnl
        FROM closed_pnl_records c
        WHERE c.account_id = t.account_id
          AND c.symbol = t.symbol
          AND c.side = CASE WHEN t.side = 'Sell' THEN 'Buy' ELSE 'Sell' END
          AND (
              c.qty IS NULL OR t.qty IS NULL
              OR ABS(c.qty - t.qty) <= GREATEST(ABS(t.qty) * 0.000001, 0.00000001)
          )
          AND c.created_time BETWEEN
              ((EXTRACT(EPOCH FROM t.closed_at) - 120) * 1000)::bigint
              AND ((EXTRACT(EPOCH FROM t.closed_at) + 120) * 1000)::bigint
        ORDER BY ABS(c.created_time - (EXTRACT(EPOCH FROM t.closed_at) * 1000)::bigint)
        LIMIT 1
    ) cpr ON TRUE
    WHERE t.account_id = $1
      AND t.opened_at >= $2
      AND t.opened_at <  $3
      AND t.source = 'scanner'
      AND t.ai_closed IS NOT TRUE
    ORDER BY t.opened_at
"""

# Count of trades in-window EXCLUDED from the pinned set (non-scanner OR AI-closed),
# so the comparison can disclose what it left out instead of silently under-counting.
_EXCLUDED_TRADES_SQL = """
    SELECT count(*) AS n
    FROM trades t
    WHERE t.account_id = $1
      AND t.opened_at >= $2
      AND t.opened_at <  $3
      AND (t.source <> 'scanner' OR t.ai_closed IS TRUE)
"""

# Scanner, non-AI trades that WOULD be pinned but whose scan_results row didn't
# resolve (archived/deleted) — reported separately so a coverage gap is visible.
_UNJOINED_TRADES_SQL = """
    SELECT count(*) AS n
    FROM trades t
    LEFT JOIN scan_results sr ON sr.id = t.scan_result_id
    WHERE t.account_id = $1
      AND t.opened_at >= $2
      AND t.opened_at <  $3
      AND t.source = 'scanner'
      AND t.ai_closed IS NOT TRUE
      AND sr.id IS NULL
"""

# Same SELECT/ORDER BY as BacktestService._load_signals "explicit" mode.
_SIGNALS_SQL = """
    SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           sr.completed_at::timestamptz AS completed_at,
           ar.completed_at::timestamptz AS analysis_completed_at,
           s.scan_id, sr.signal_source, sr.analysis_price
    FROM scan_results sr
    JOIN scans s ON sr.scan_id = s.scan_id
    LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
    WHERE s.scan_id = ANY($1)
      AND sr.status = 'completed'
      AND sr.direction IN ('buy', 'sell')
    ORDER BY signal_time, sr.id
"""


class ParityDataAccess:
    """Read-only accessor for the parity harness over the LOCAL db."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch_live_trades(
        self, account_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Pinnable scanner trades for the window (non-scanner / AI-closed excluded).

        Rows whose scan row didn't resolve (scan_id NULL) are dropped here but counted
        via fetch_excluded_counts so the caller can disclose them — never a silent drop.
        """
        rows = await self._db.pool.fetch(_TRADES_SQL, account_id, start, end)
        return [dict(r) for r in rows if r["scan_id"] is not None]

    async def fetch_excluded_counts(
        self, account_id: str, start: datetime, end: datetime
    ) -> dict[str, int]:
        """How many in-window trades were left out of the pinned set, by reason —
        surfaced in the replay comparison so fidelity is never computed over a silently
        truncated trade set."""
        excluded = await self._db.pool.fetchval(_EXCLUDED_TRADES_SQL, account_id, start, end)
        # Scanner trades whose scan_results/scans row didn't resolve (archived/missing):
        unjoined = await self._db.pool.fetchval(_UNJOINED_TRADES_SQL, account_id, start, end)
        return {"excluded_non_scanner_or_ai": int(excluded or 0),
                "scanner_without_scan_row": int(unjoined or 0)}

    async def fetch_signals(self, scan_ids: list[str]) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(_SIGNALS_SQL, scan_ids)
        return [
            {
                "id": r["id"], "ticker": r["ticker"], "direction": r["direction"],
                "confidence": r["confidence"], "score": r["score"],
                "signal_time": r["signal_time"],
                "completed_at": r["completed_at"],
                "analysis_completed_at": r["analysis_completed_at"],
                "scan_id": r["scan_id"], "signal_source": r["signal_source"],
                "analysis_price": float(r["analysis_price"]) if r["analysis_price"] is not None else None,
            }
            for r in rows
        ]

    async def fetch_klines(
        self, kline_cache: Any, symbols: list[str], start: datetime, end: datetime,
        interval: str = "5m",
    ) -> dict[str, list[dict]]:
        import asyncio
        symbols = sorted(set(symbols))
        if kline_cache is not None and hasattr(kline_cache, "ensure_coverage"):
            try:
                await kline_cache.ensure_coverage(symbols, interval, start, end)
            except Exception:
                # Replay/parity should still disclose any symbols with no candles via
                # symbols_no_kline; a transient warm-up failure must not hide the
                # comparison behind an infrastructure exception.
                pass
        results = await asyncio.gather(
            *(kline_cache.get_klines(sym, interval, start, end) for sym in symbols)
        )
        return {sym: series for sym, series in zip(symbols, results)}

    async def build_fine_klines(
        self, kline_cache: Any, symbols: list[str], window_start: datetime,
        window_end: datetime, sim_interval_seconds: int = 300,
    ) -> dict[str, dict[int, list[dict]]]:
        """Warm + bucket 1m candles into the engine's drill-down shape.

        Returns {symbol: {bar_open_epoch: [1m candles asc]}} for the given window —
        the structure BacktestEngine.run accepts as `fine_klines`. The engine then
        refines TP/SL/equity-rule exit prices to 1m within each 5m bar, WITHOUT
        shifting the 5m entry/selection timeline. Mirrors BacktestService's
        _build_fine_klines bucketing (key = floor(open_time / sim_bar) * sim_bar).

        Best-effort: warms coverage first so the 1m candles exist locally; a symbol
        with no 1m data is simply omitted (engine falls back to 5m for it).
        """
        symbols = sorted(set(symbols))
        # Warm 1m coverage for the window (fetches from Bybit if missing).
        try:
            await kline_cache.ensure_coverage(symbols, "1m", window_start, window_end)
        except Exception:
            pass  # fail-soft: bucket whatever is cached; engine falls back to 5m

        out: dict[str, dict[int, list[dict]]] = {}
        for sym in symbols:
            ones = await kline_cache.get_klines(sym, "1m", window_start, window_end)
            if not ones:
                continue
            buckets: dict[int, list[dict]] = {}
            for c in ones:
                ot = c["open_time"]
                key = (int(ot.timestamp()) // sim_interval_seconds) * sim_interval_seconds
                buckets.setdefault(key, []).append(c)
            for key in buckets:
                buckets[key].sort(key=lambda c: c["open_time"])
            out[sym] = buckets
        return out

    async def build_fine_klines_scoped(
        self, kline_cache: Any, trade_windows: list[tuple[str, datetime, datetime]],
        sim_interval_seconds: int = 300, neighbour_bars: int = 1,
    ) -> dict[str, dict[int, list[dict]]]:
        """Scoped drill-down: 1m candles ONLY around each trade's entry + exit bars.

        High performance + high accuracy: instead of warming 1m for whole multi-hour
        cycles, fetch a narrow 1m window around each trade's ENTRY bar and EXIT bar
        (±neighbour_bars), mirroring BacktestService._build_fine_klines. Returns the
        engine's fine_klines shape {symbol: {bar_open_epoch: [1m candles asc]}}.

        trade_windows: (symbol, entry_time, exit_time) per pinned live trade — ALL
        trades of ONE cycle (they share ~one entry instant and close together).

        FULL-BOOK coverage for portfolio-equity closes: the engine's 1m equity walk
        (drawdown / smart / target-goal / close_on_profit) only engages on a bar when
        EVERY open position has a 1m window there — equity is a book-wide sum. Because
        a cycle's positions can exit on slightly different bars, each trade's exit bar
        (±neighbour) is added to EVERY symbol in the cycle, so the firing bar is 1m for
        the whole book (mirrors BacktestService._build_fine_klines portfolio coverage).
        """
        bar_s = sim_interval_seconds

        def _bar_epoch(dt: datetime) -> int:
            return (int(dt.timestamp()) // bar_s) * bar_s

        all_symbols = sorted({sym for sym, _, _ in trade_windows})

        # Cross-position exit epochs: every trade's exit bar (±neighbour) must be 1m
        # for ALL symbols so a book-wide equity close fires at 1m, not 5m.
        shared_exit_epochs: set[int] = set()
        for _sym, _et, xt in trade_windows:
            if isinstance(xt, datetime):
                xe = _bar_epoch(xt)
                for n in range(-neighbour_bars, neighbour_bars + 1):
                    shared_exit_epochs.add(xe + n * bar_s)

        wanted: dict[str, set[int]] = {s: set(shared_exit_epochs) for s in all_symbols}
        for sym, et, xt in trade_windows:
            if isinstance(et, datetime):
                ee = _bar_epoch(et)
                # entry fills at next bar open when not bar-aligned → cover ee..ee+1+neighbour
                for n in range(0, neighbour_bars + 2):
                    wanted[sym].add(ee + n * bar_s)

        out: dict[str, dict[int, list[dict]]] = {}
        for sym, epochs in wanted.items():
            if not epochs:
                continue
            lo = datetime.fromtimestamp(min(epochs), tz=timezone.utc)
            hi = datetime.fromtimestamp(max(epochs) + bar_s, tz=timezone.utc)
            try:
                await kline_cache.ensure_coverage([sym], "1m", lo, hi)
            except Exception:
                pass
            ones = await kline_cache.get_klines(sym, "1m", lo, hi)
            if not ones:
                continue
            buckets: dict[int, list[dict]] = {}
            for c in ones:
                key = (int(c["open_time"].timestamp()) // bar_s) * bar_s
                if key in epochs:
                    buckets.setdefault(key, []).append(c)
            for key in buckets:
                buckets[key].sort(key=lambda c: c["open_time"])
            if buckets:
                out[sym] = buckets
        return out
