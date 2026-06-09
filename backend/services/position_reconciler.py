"""Background service that reconciles DB trade state with exchange positions.

Detects trades that were closed externally (SL/TP, liquidation, ADL, manual)
and updates the DB with real PnL data from Bybit's closed-pnl API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_INITIAL_DELAY_S = 30
_DEFAULT_INTERVAL_S = 60
_API_CALL_DELAY_S = 0.25
# Max closed-PnL pages to scan when matching a stale trade to its exchange close.
# Bounds the cursor walk so a huge history can't stall reconciliation, while being
# deep enough (50 × 100 = 5000 records) that a busy account's older closes still
# surface — mirrors accounts_service._fetch_and_store_closed_pnl's max_pages.
_MAX_CLOSED_PNL_PAGES = 50


class PositionReconciler:
    """Background loop that reconciles DB trades with exchange positions and backfills closed PnL."""

    def __init__(
        self,
        db: Any,
        accounts_service: Any,
        trade_service: Any,
        ws_manager: Any = None,
    ):
        self._db = db
        self._accounts_service = accounts_service
        self._trade_service = trade_service
        self._ws = ws_manager
        self._task: asyncio.Task | None = None
        self._interval = int(os.environ.get("POSITION_SYNC_INTERVAL_S", _DEFAULT_INTERVAL_S))
        self._enabled = os.environ.get("POSITION_SYNC_ENABLED", "true").lower() != "false"
        self._in_progress: set[str] = set()

    async def start(self) -> None:
        """Start the periodic reconciliation loop unless disabled via env var."""
        if not self._enabled:
            logger.info("Position reconciler disabled via POSITION_SYNC_ENABLED=false")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Position reconciler started (interval=%ds)", self._interval)

    async def shutdown(self) -> None:
        """Cancel and await the reconciliation loop task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Position reconciler stopped")

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(_INITIAL_DELAY_S)
        except asyncio.CancelledError:
            return
        while True:
            try:
                await self._reconcile_all_accounts()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("reconciliation_loop_error")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _reconcile_all_accounts(self) -> None:
        accounts = await self._db.list_accounts()
        active = [a for a in accounts if a.get("is_active")]
        for account in active:
            try:
                await self._reconcile_account(str(account["id"]))
            except Exception:
                logger.exception("reconcile_account_error account_id=%s", account["id"])
        # FR-051: sweep abandoned pre-submit intents (rejected/never-filled MR orders
        # whose trade row was never created, so delete_intent never ran). Without this
        # a stale intent could mislabel a LATER orphan on the same (account,symbol,side)
        # as mean_reversion, and the table would grow unbounded.
        try:
            from backend.services import pending_intents as _pi
            await _pi.gc_stale(self._db)
        except Exception:
            logger.warning("pending_intent_gc_sweep_failed", exc_info=True)

    async def _reconcile_account(self, account_id: str) -> None:
        try:
            client = await self._accounts_service.get_client(account_id)
        except Exception:
            logger.debug("Cannot get client for account %s, skipping", account_id)
            return

        open_trades = await self._trade_service.get_open_trades(account_id, limit=500)
        # Also fetch trades stuck in 'closing' or 'partially_closed'
        # AND recently-closed trades with zero exit_price (closed by _handle_close_failure with no PnL)
        async with self._db.pool.acquire() as conn:
            stalled = await conn.fetch(
                "SELECT * FROM trades WHERE account_id = $1 "
                "AND status IN ('closing', 'partially_closed') "
                "ORDER BY created_at DESC LIMIT 200",
                account_id,
            )
            zero_pnl_closed = await conn.fetch(
                "SELECT * FROM trades WHERE account_id = $1 "
                "AND status = 'closed' AND exit_price = 0 "
                "AND closed_at > NOW() - INTERVAL '24 hours' "
                "ORDER BY closed_at DESC LIMIT 50",
                account_id,
            )
        all_reconcile_candidates = open_trades + [dict(r) for r in stalled]
        backfill_trades = [dict(r) for r in zero_pnl_closed]

        if not all_reconcile_candidates and not backfill_trades:
            return

        try:
            positions = await client.get_positions()
        except Exception:
            logger.warning("Failed to fetch positions for account %s", account_id)
            return

        # Build a map of (symbol, side) -> count of open exchange positions
        position_counts: dict[tuple[str, str], int] = {}
        for p in positions:
            if float(p.get("size", 0)) > 0:
                key = (p["symbol"], p["side"])
                position_counts[key] = position_counts.get(key, 0) + 1

        # Build a map of (symbol, side) -> list of DB trades
        trade_groups: dict[tuple[str, str], list[dict]] = {}
        for t in all_reconcile_candidates:
            key = (t["symbol"], t["side"])
            trade_groups.setdefault(key, []).append(t)

        stale_trades: list[dict] = []
        # A just-placed trade (DB row exists, but the exchange may not yet reflect
        # the order, or a limit order is still unfilled) must NOT be judged
        # "stale" and force-closed in the DB — that would orphan a live position.
        # Skip trades younger than this grace window from stale detection.
        from datetime import datetime, timedelta, timezone

        _now = datetime.now(timezone.utc)
        _grace = timedelta(seconds=90)

        def _is_young(t: dict) -> bool:
            ts = t.get("created_at") or t.get("opened_at")
            if ts is None:
                return False
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    dt = ts
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (_now - dt) < _grace
            except Exception:
                return False

        # AI-CONTEXT: untrusted-empty guard. client.get_positions() can return an
        # OK-but-EMPTY/partial list on a transient Bybit blip (throttle, replication
        # lag, retCode 0 with [] ) WITHOUT raising. If we trusted that, every
        # eligible DB trade would see exchange_count==0 and be force-closed below —
        # mass-orphaning LIVE exchange positions (their DB rows flipped to
        # closed/external, never un-closed by the PnL backfill). So: if the exchange
        # reports ZERO open positions while the DB has eligible (non-young) open
        # trades, treat the reading as untrustworthy and SKIP stale-detection this
        # cycle. A genuinely-flat account simply has no eligible trades to reconcile,
        # so this never blocks a real close — only a real position confirmed gone on
        # a later cycle (with a non-empty list) will be reconciled. Backfill (PnL on
        # already-closed trades) still proceeds; it does not force-close anything.
        _has_eligible_open = any(
            not _is_young(t) for t in all_reconcile_candidates
        )
        _trust_positions = bool(position_counts) or not _has_eligible_open
        if not _trust_positions:
            logger.warning(
                "reconcile_skip_untrusted_empty_positions account=%s db_open=%d",
                account_id, len(all_reconcile_candidates),
            )

        for key, trades in trade_groups.items():
            if not _trust_positions:
                break
            exchange_count = position_counts.get(key, 0)
            # exclude young trades from the "stale" candidate set for this key
            eligible = [t for t in trades if not _is_young(t)]
            young_count = len(trades) - len(eligible)
            if exchange_count == 0:
                # No position on exchange — eligible (non-young) DB trades are stale
                stale_trades.extend(eligible)
            elif exchange_count < len(eligible):
                # Fewer positions than eligible DB trades — oldest are likely closed.
                # Young trades are assumed to occupy exchange slots, so subtract them.
                sorted_trades = sorted(eligible, key=lambda t: t.get("created_at") or "")
                n_stale = max(0, len(eligible) - max(0, exchange_count - young_count))
                stale_trades.extend(sorted_trades[:n_stale])

        # Backfill trades are already closed but need PnL data
        all_to_process = stale_trades + backfill_trades

        # Reverse pass: detect orphan positions (exchange position with no DB trade)
        for key, count in position_counts.items():
            db_count = len(trade_groups.get(key, []))
            orphan_count = count - db_count
            if orphan_count > 0:
                symbol, side = key
                # FR-051: recover the originating strategy from the pre-submit intent
                # (the order_link_id is never on the exchange, so we match by
                # account/symbol/side). This tells the operator whether the orphan is a
                # mean-reversion position — it is NEVER silently adopted as 'trend'.
                recovered_strategy = None
                try:
                    from backend.services import pending_intents as _pi
                    recovered_strategy = await _pi.lookup_strategy(self._db, account_id, symbol, side)
                except Exception:
                    pass
                logger.error(
                    "ORPHAN_POSITION_DETECTED: %s %s on account %s — %d exchange position(s) with no DB trade (strategy=%s). Manual intervention required.",
                    side, symbol, account_id, orphan_count, recovered_strategy or "unknown",
                )
                if self._ws:
                    try:
                        await self._ws.broadcast_to_account(account_id, "orphan_position_detected", {
                            "symbol": symbol, "side": side, "count": orphan_count,
                            "strategy_kind": recovered_strategy,
                            "message": f"{orphan_count} {side} {symbol} position(s) on exchange with no DB trade record"
                                       + (f" (strategy: {recovered_strategy})" if recovered_strategy else "")
                                       + ". Manual intervention required.",
                        })
                    except Exception:
                        pass

        if not all_to_process:
            return

        logger.info(
            "Found %d stale + %d backfill trades for account %s",
            len(stale_trades), len(backfill_trades), account_id,
        )

        for trade in all_to_process:
            trade_id = str(trade["id"])
            if trade_id in self._in_progress:
                continue
            self._in_progress.add(trade_id)
            try:
                is_backfill = trade["status"] == "closed"
                await self._reconcile_trade(client, trade, backfill_only=is_backfill)
            except Exception:
                logger.exception(
                    "reconcile_trade_error trade_id=%s symbol=%s",
                    trade["id"], trade["symbol"],
                )
            finally:
                self._in_progress.discard(trade_id)
                await asyncio.sleep(_API_CALL_DELAY_S)

        # If no positions remain on exchange, delete leftover close rules
        if stale_trades and not position_counts:
            try:
                await self._db.delete_non_executed_rules_for_account(account_id)
                logger.info("Deleted stale close rules for account %s (no positions)", account_id)
            except Exception:
                logger.warning("Failed to delete rules for account %s", account_id)

    async def _reconcile_trade(self, client: Any, trade: dict, *, backfill_only: bool = False) -> None:
        trade_id = str(trade["id"])
        account_id = trade["account_id"]
        symbol = trade["symbol"]
        side = trade["side"]

        opened_at = trade.get("opened_at") or trade.get("created_at")
        start_ms = int(opened_at.timestamp() * 1000) if opened_at else 0
        end_ms = int(time.time() * 1000)

        pnl_record = await self._fetch_closed_pnl_match(
            client, symbol, side, start_ms, end_ms
        )

        if not pnl_record:
            if backfill_only:
                return  # Can't backfill without data, retry next cycle
            # Still close the trade with zero values
            exit_price = 0.0
            closed_pnl = 0.0
            fees = 0.0
            net_pnl = 0.0
            realized_pnl_pct = 0.0
            close_reason = "external"
        else:
            exit_price = float(pnl_record.get("avgExitPrice", 0))
            closed_pnl = float(pnl_record.get("closedPnl", 0))
            entry_fee = float(pnl_record.get("totalEntryFee", 0))
            exit_fee = float(pnl_record.get("totalExitFee", 0))
            fees = entry_fee + exit_fee
            # Bybit's closedPnl is raw PnL (without fees deducted)
            net_pnl = closed_pnl - fees
            order_type = pnl_record.get("orderType", "")
            close_reason = self._infer_close_reason(order_type, pnl_record, trade, exit_price)

            entry_price = float(trade.get("entry_price") or trade.get("avg_fill_price") or 0)
            qty = float(trade.get("qty") or 0)
            if entry_price > 0 and qty > 0:
                realized_pnl_pct = (closed_pnl / (entry_price * qty)) * 100
            else:
                realized_pnl_pct = 0.0

        if backfill_only:
            # Trade is already closed — just update the PnL fields
            async with self._db.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE trades SET exit_price = $1, realized_pnl = $2, "
                    "realized_pnl_pct = $3, fees = $4, net_pnl = $5, close_reason = $6 "
                    "WHERE id = $7 AND account_id = $8 AND status = 'closed'",
                    exit_price, closed_pnl, realized_pnl_pct,
                    fees, net_pnl, close_reason, trade["id"], account_id,
                )
            self._trade_service.invalidate_stats_cache(account_id)
            logger.info(
                "Backfilled PnL for trade %s (%s %s): pnl=%.4f exit=%.4f",
                trade_id, symbol, side, closed_pnl, exit_price,
            )
            return

        try:
            closed_trade = await self._trade_service.reconcile_close(
                trade_id=trade_id,
                account_id=account_id,
                exit_price=exit_price,
                realized_pnl=closed_pnl,
                realized_pnl_pct=realized_pnl_pct,
                fees=fees,
                net_pnl=net_pnl,
                close_reason=close_reason,
            )
        except Exception as e:
            if "already closed" in str(e).lower() or "ConcurrentModification" in type(e).__name__:
                logger.debug("Trade %s already reconciled, skipping", trade_id)
                return
            raise

        if closed_trade:
            logger.info(
                "Reconciled trade %s (%s %s): pnl=%.4f exit=%.4f reason=%s",
                trade_id, symbol, side, closed_pnl, exit_price, close_reason,
            )

    async def _fetch_closed_pnl_match(
        self, client: Any, symbol: str, side: str, start_ms: int, end_ms: int,
    ) -> dict | None:
        """Fetch closed-PnL records and find the matching one for this trade.

        Pages the exchange's closed-PnL feed cursor-to-cursor (bounded by
        _MAX_CLOSED_PNL_PAGES) until the symbol's record is found or the feed is
        exhausted. AI-CONTEXT: previously this read only 2 pages (200 records); a busy
        account that closed >200 positions of OTHER symbols inside the trade's window
        would never surface this trade's record, leaving it unreconciled (zero
        exit_price/PnL) forever. Returns the newest matching record, or None.
        """
        close_side = "Sell" if side == "Buy" else "Buy"
        cursor = ""
        for _page in range(_MAX_CLOSED_PNL_PAGES):
            try:
                result = await client.get_closed_pnl(
                    start_time=start_ms, end_time=end_ms, limit=100, cursor=cursor,
                ) if cursor else await client.get_closed_pnl(
                    start_time=start_ms, end_time=end_ms, limit=100,
                )
            except Exception:
                logger.warning("get_closed_pnl failed for %s", symbol)
                return None
            matches = [
                r for r in result.get("list", [])
                if r.get("symbol") == symbol and r.get("side") == close_side
            ]
            if matches:
                matches.sort(key=lambda r: int(r.get("updatedTime", 0)), reverse=True)
                return matches[0]
            cursor = result.get("nextPageCursor", "")
            if not cursor:
                break
        return None

    @staticmethod
    def _infer_close_reason(order_type: str, record: dict, trade: dict | None = None, exit_price: float = 0.0) -> str:
        exec_type = record.get("execType", "")
        if exec_type == "BustTrade" or "liq" in exec_type.lower():
            return "liquidation"
        if exec_type == "AdlTrade":
            return "adl"
        ot = order_type.lower()
        if ot in ("limit", "stoplimit"):
            closed_pnl = float(record.get("closedPnl", 0))
            return "take_profit" if closed_pnl >= 0 else "stop_loss"
        # For market orders, check if exit_price matches TP/SL levels
        if trade and exit_price > 0:
            tp = float(trade.get("take_profit_price") or 0)
            sl = float(trade.get("stop_loss_price") or 0)
            if tp > 0 and abs(exit_price - tp) / tp < 0.005:
                return "take_profit"
            if sl > 0 and abs(exit_price - sl) / sl < 0.005:
                return "stop_loss"
        return "external"
