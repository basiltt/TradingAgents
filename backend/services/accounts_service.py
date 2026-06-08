"""Service layer for trading account management and portfolio data."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.async_persistence import AsyncAnalysisDB
from backend.crypto import decrypt_value, encrypt_value, mask_api_key
from backend.services.bybit_client import BybitAPIError, BybitClient

logger = logging.getLogger(__name__)

_SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
_ONE_DAY_MS = 86_400_000
_MAX_RANGE_DAYS = 90
_MAX_ERROR_MESSAGE_LENGTH = 512
_WALLET_CACHE_TTL_S = 2
_POSITIONS_CACHE_TTL_S = 3
_ORDERS_CACHE_TTL_S = 10
_REFRESH_COOLDOWN_S = 10.0
_SNAPSHOT_COOLDOWN_S = 30.0
_SNAPSHOT_RETENTION_DAYS = 1095  # ~3 years

# Tier-1 maintenance margin rate used for the isolated-margin liquidation estimate
# (matches trading_rules.compute_liquidation_price's default mmr).
_TIER1_MMR = Decimal("0.005")
# Fraction of the liquidation distance the stop-loss is allowed to reach. The SL must
# trigger strictly BEFORE liquidation; 0.9 mirrors the mean-reversion guard
# (mean_reversion_math.check_geometry / MR_SL_LIQUIDATION).
_SL_LIQ_SAFETY = Decimal("0.9")


def clamp_sl_move_to_liquidation(sl_price_move_pct: Decimal, leverage: int) -> Decimal:
    """Clamp a stop-loss PRICE-MOVE percent so it triggers before liquidation.

    `sl_price_move_pct` is the adverse price move (in %) at which the SL fires —
    i.e. stop_loss_pct / leverage. Bybit isolated liquidation occurs at roughly
    (1/leverage − MMR) of adverse move. A SL placed at/beyond that never fires:
    the exchange force-liquidates first for a full-margin loss. Returns the input
    unchanged when it is already safely inside liquidation, else the clamped value
    (0.9× the liquidation distance). Money-critical: with the default config
    (stop_loss_pct=100, leverage=20 → 5% move vs ~4.5% liquidation) every losing
    trade rode to liquidation instead of stopping out.
    """
    if sl_price_move_pct <= 0 or leverage <= 0:
        return sl_price_move_pct
    lev = Decimal(str(leverage))
    liq_move_pct = (Decimal("1") / lev - _TIER1_MMR) * Decimal("100")
    max_sl_pct = liq_move_pct * _SL_LIQ_SAFETY
    if max_sl_pct > 0 and sl_price_move_pct >= max_sl_pct:
        return max_sl_pct
    return sl_price_move_pct


def _now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string (no microseconds)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_to_ms(date_str: str) -> int:
    """Convert YYYY-MM-DD date string to Unix timestamp in milliseconds."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _sanitize_error(msg: str) -> str:
    """Truncate error messages to prevent log/DB overflow."""
    if len(msg) > _MAX_ERROR_MESSAGE_LENGTH:
        msg = msg[:_MAX_ERROR_MESSAGE_LENGTH]
    return msg


class AccountsService:
    """Manages trading accounts: CRUD, exchange client lifecycle, portfolio data, and caching.

    Owns per-account Bybit client instances, an in-memory cache (bounded, TTL-based),
    and coordinates with TradeRepository/TradeService for trade operations.
    """

    _CACHE_MAX = 500
    _REFRESH_COOLDOWN_S: float = _REFRESH_COOLDOWN_S

    def __init__(self, db: AsyncAnalysisDB, ws_manager=None, trade_repo=None, trade_service=None):
        """Initialize with database, optional WebSocket manager, and trade dependencies.

        Args:
            db: Async database adapter for account/snapshot persistence.
            ws_manager: WebSocket connection manager for real-time pushes.
            trade_repo: TradeRepository instance (can be wired later via set_trade_dependencies).
            trade_service: TradeService instance (can be wired later via set_trade_dependencies).
        """
        self._db = db
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._refresh_locks: Dict[str, float] = {}
        self._clients: Dict[str, BybitClient] = {}
        self._client_lock = asyncio.Lock()
        self._shutting_down = False
        self._ws_manager = ws_manager
        self._trade_repo = trade_repo
        self._trade_service = trade_service

    async def shutdown(self) -> None:
        """Close all exchange clients and clear caches."""
        # Set BEFORE closing clients so any in-flight call that races shutdown
        # (e.g. a scan task not yet fully drained) refuses to recreate a client and
        # place an untracked trade against the exchange during teardown.
        self._shutting_down = True
        logger.info("shutdown_start", extra={"client_count": len(self._clients)})
        for cid, client in self._clients.items():
            try:
                await client.close()
            except Exception:
                logger.warning("shutdown_client_close_failed", extra={"client_id": cid})
        self._clients.clear()
        self._cache.clear()
        logger.info("shutdown_complete")

    def _get_cached(self, key: str, ttl: float) -> Any | None:
        """Return cached value if within TTL, else None."""
        entry = self._cache.get(key)
        if entry and time.monotonic() < entry[0]:
            return entry[1]
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        """Store a value in the bounded cache, evicting expired/oldest if at capacity."""
        if len(self._cache) >= self._CACHE_MAX:
            now = time.monotonic()
            expired = [k for k, (exp, _) in self._cache.items() if now >= exp]
            for k in expired:
                del self._cache[k]
            if len(self._cache) >= self._CACHE_MAX:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
        self._cache[key] = (time.monotonic() + ttl, data)

    def invalidate_cache(self, account_id: str) -> None:
        """Clear cached wallet/position/order data so the next poll refetches.

        Does NOT touch the pooled BybitClient — the exchange client is a long-lived,
        reusable connection and is safe (indeed required) to keep across trades and
        position closes. Tearing it down here previously leaked aiohttp sessions
        (fire-and-forget close() tasks were GC'd before running, and concurrent
        trades orphaned a shared client mid-flight). To intentionally retire a
        client (credential rotation, deactivation, deletion) use discard_client.
        """
        keys_to_remove = [k for k in self._cache if k.startswith(f"{account_id}:")]
        for k in keys_to_remove:
            del self._cache[k]
        self._refresh_locks.pop(account_id, None)

    async def discard_client(self, account_id: str) -> None:
        """Clear cached data and deterministically close the account's exchange client.

        Use when the client must actually be retired — credentials changed, account
        deactivated/deleted — so a subsequent call rebuilds a fresh client. Awaits
        close() so the underlying aiohttp session/connector is released before
        returning (no fire-and-forget GC race).
        """
        self.invalidate_cache(account_id)
        client = self._clients.pop(account_id, None)
        if client:
            try:
                await client.close()
            except Exception:
                logger.warning("client_close_failed", extra={"account_id": account_id})

    def invalidate_all_caches(self) -> None:
        """Clear all cached wallet/position data so the next poll fetches fresh state."""
        self._cache.clear()

    def _can_refresh(self, account_id: str, cooldown: float = _REFRESH_COOLDOWN_S) -> bool:
        """Return True if cooldown has elapsed since last refresh for this account."""
        last = self._refresh_locks.get(account_id, 0)
        return time.monotonic() - last >= cooldown

    def _mark_refreshed(self, account_id: str) -> None:
        """Record current monotonic time as last refresh for this account."""
        now = time.monotonic()
        self._refresh_locks[account_id] = now
        if len(self._refresh_locks) > self._CACHE_MAX:
            stale = [k for k, v in self._refresh_locks.items() if now - v > self._REFRESH_COOLDOWN_S * 10]
            for k in stale:
                del self._refresh_locks[k]

    async def _build_client(self, account_id: str) -> BybitClient:
        """Get or create a BybitClient for the account, decrypting credentials on first call."""
        if account_id in self._clients:
            return self._clients[account_id]
        # Money-safety: never spin up a NEW exchange client once shutdown has begun.
        # A scan task racing teardown could otherwise recreate a just-closed client
        # and place an untracked trade during shutdown.
        if self._shutting_down:
            raise RuntimeError("AccountsService is shutting down; refusing to create a new client")

        async with self._client_lock:
            if account_id in self._clients:
                return self._clients[account_id]
            if self._shutting_down:
                raise RuntimeError("AccountsService is shutting down; refusing to create a new client")

            creds = await self._db.get_account_credentials(account_id)
            if not creds:
                raise ValueError(f"Account {account_id} not found")

            def _decrypt_and_create() -> BybitClient:
                """Decrypt stored credentials and construct a BybitClient (runs in thread)."""
                api_key = decrypt_value(creds["api_key_encrypted"])
                api_secret = decrypt_value(creds["api_secret_encrypted"])
                return BybitClient(api_key, api_secret, creds["account_type"])

            client = await asyncio.to_thread(_decrypt_and_create)
            self._clients[account_id] = client
            return client

    async def get_client(self, account_id: str) -> BybitClient:
        """Get or create a Bybit API client for the given account."""
        return await self._build_client(account_id)

    def set_trade_dependencies(self, trade_repo, trade_service) -> None:
        """Wire trade repo and service after construction to break circular init."""
        self._trade_repo = trade_repo
        self._trade_service = trade_service

    # ── Market Data ───────────────────────────────────────────────────────

    async def get_mark_price(self, account_id: str, symbol: str) -> float:
        """Fetch current mark price for a symbol via the account's Bybit client."""
        client = await self._build_client(account_id)
        price_str = await client.get_mark_price(symbol)
        return float(price_str)

    # ── Trade Execution ──────────────────────────────────────────────────

    async def place_trade(
        self,
        account_id: str,
        symbol: str,
        signal_direction: str,
        trade_direction: str,
        leverage: int,
        take_profit_pct: float,
        stop_loss_pct: float,
        capital_pct: float,
        base_capital: float,
        source: str = "manual",
        source_id: int | None = None,
        scan_result_id: int | None = None,
        strategy_kind: str = "trend",
        strategy_cohort: str = "trend",
        f1_active: bool = False,
    ) -> Dict[str, Any]:
        """Place a market trade with leverage, TP, and SL.

        TP/SL percentages are leverage-adjusted (e.g. 100% TP at 10x = 10% price move).
        Qty is calculated from base_capital * capital_pct, leveraged, divided by mark price.
        """
        from decimal import ROUND_DOWN, Decimal

        _VALID_PLACEMENT_SOURCES = {"manual", "cycle", "scanner"}
        if source not in _VALID_PLACEMENT_SOURCES:
            raise ValueError(f"Invalid source: {source}. Allowed: {_VALID_PLACEMENT_SOURCES}")

        t0 = time.monotonic()
        client = await self._build_client(account_id)

        account = await self._db.get_account(account_id)
        if not account or not account.get("is_active"):
            raise ValueError("Account is inactive or not found")

        if trade_direction == "straight":
            side = "Buy" if signal_direction in ("buy", "long") else "Sell"
        else:
            side = "Sell" if signal_direction in ("buy", "long") else "Buy"

        logger.info("place_trade_start", extra={
            "account_id": account_id, "side": side, "symbol": symbol,
            "leverage": leverage, "capital_pct": capital_pct, "base_capital": base_capital,
            "signal": signal_direction, "direction": trade_direction,
        })

        mark_price_str, instrument = await asyncio.gather(
            client.get_mark_price(symbol),
            client.get_instrument_info(symbol),
        )
        mark_price = Decimal(mark_price_str)
        if mark_price <= 0:
            raise ValueError(f"Invalid mark price {mark_price} for {symbol}")

        leverage_filter = instrument.get("leverageFilter", {})
        max_leverage = int(float(leverage_filter.get("maxLeverage", "125")))
        if leverage > max_leverage:
            logger.info("Leverage %dx exceeds max %dx for %s, capping", leverage, max_leverage, symbol)
            leverage = max_leverage

        await client.set_leverage(symbol, leverage)

        lot_filter = instrument.get("lotSizeFilter", {})
        min_qty = Decimal(lot_filter.get("minOrderQty", "1"))
        qty_step = Decimal(lot_filter.get("qtyStep", "1"))
        max_qty = Decimal(lot_filter.get("maxOrderQty", "1000000"))
        price_filter = instrument.get("priceFilter", {})
        tick_size = Decimal(price_filter.get("tickSize", "0.01"))

        # Calculate position size:
        # usdt_amount = base_capital * (capital_pct / 100)
        # qty = usdt_amount * leverage / mark_price
        usdt_amount = Decimal(str(base_capital)) * Decimal(str(capital_pct)) / Decimal("100")
        qty = usdt_amount * Decimal(str(leverage)) / mark_price

        # Round qty down to qty_step
        qty_rounded = (qty / qty_step).quantize(Decimal("1"), rounding=ROUND_DOWN) * qty_step

        if qty_rounded < min_qty:
            raise ValueError(
                f"Calculated qty {qty_rounded} is below minimum {min_qty} for {symbol}. "
                f"Increase capital % or base capital."
            )
        if qty_rounded > max_qty:
            qty_rounded = max_qty

        # Convert leverage-adjusted percentages to actual price percentages
        _ONE = Decimal("1")
        _HUNDRED = Decimal("100")
        tp_price_pct = Decimal(str(take_profit_pct)) / Decimal(str(leverage))
        sl_price_pct = Decimal(str(stop_loss_pct)) / Decimal(str(leverage))

        if sl_price_pct > 0 and sl_price_pct >= _HUNDRED:
            raise ValueError("Stop loss exceeds 100% price move — reduce SL % or increase leverage")
        if side == "Sell" and tp_price_pct > 0 and tp_price_pct >= _HUNDRED:
            raise ValueError("Take profit exceeds 100% price move for short — reduce TP % or increase leverage")

        # ── SL-vs-liquidation clamp (money-critical) ──────────────────────────
        # The protective stop must trigger BEFORE the position liquidates, else the
        # exchange force-liquidates for a full-margin loss and the SL never fires.
        # The default config (stop_loss_pct=100, leverage=20 → 5% move) sat AT/BEYOND
        # the ~4.5% liquidation distance, so every losing trade rode to liquidation
        # instead of stopping out (observed in live PnL). Clamp (not reject) so existing
        # default-config trades still place, now with a stop that actually protects.
        # Mirrors the mean-reversion path's MR_SL_LIQUIDATION guard.
        if sl_price_pct > 0:
            _clamped_sl = clamp_sl_move_to_liquidation(sl_price_pct, int(leverage))
            if _clamped_sl != sl_price_pct:
                logger.warning(
                    "sl_clamped_to_avoid_liquidation",
                    extra={
                        "symbol": symbol, "leverage": leverage,
                        "requested_sl_move_pct": float(sl_price_pct),
                        "clamped_sl_move_pct": float(_clamped_sl),
                    },
                )
                sl_price_pct = _clamped_sl

        # Calculate TP/SL prices (skip when pct is 0 or not provided).
        # Round DIRECTIONALLY (away from the mark) so a tight TP + coarse tick can
        # never round back across the mark and get rejected by the exchange, and a
        # SL never rounds to the wrong side of the entry.
        from decimal import ROUND_UP

        def round_price(p: Decimal, *, round_up: bool) -> str:
            rounding = ROUND_UP if round_up else ROUND_DOWN
            rounded = (p / tick_size).quantize(Decimal("1"), rounding=rounding) * tick_size
            if rounded <= 0:
                raise ValueError(f"Price rounded to {rounded} after tick alignment — adjust parameters")
            return str(rounded)

        tp_price_str: str | None = None
        sl_price_str: str | None = None
        if tp_price_pct > 0:
            if side == "Buy":
                # long TP is ABOVE mark → round UP (away from entry) so it stays
                # strictly above mark even after tick alignment
                tp_price = mark_price * (_ONE + tp_price_pct / _HUNDRED)
                if tp_price > 0:
                    tp_price_str = round_price(tp_price, round_up=True)
                    # guarantee at least one tick above mark (else exchange rejects)
                    if Decimal(tp_price_str) <= mark_price:
                        tp_price_str = str(((mark_price / tick_size).quantize(Decimal("1"), rounding=ROUND_DOWN) + 1) * tick_size)
            else:
                # short TP is BELOW mark → round DOWN (away from entry)
                tp_price = mark_price * (_ONE - tp_price_pct / _HUNDRED)
                if tp_price > 0:
                    tp_price_str = round_price(tp_price, round_up=False)
                    if Decimal(tp_price_str) >= mark_price:
                        tp_price_str = str(((mark_price / tick_size).quantize(Decimal("1"), rounding=ROUND_DOWN) - 1) * tick_size)
        if sl_price_pct > 0:
            if side == "Buy":
                # long SL is BELOW mark → round DOWN (away from entry; slightly wider)
                sl_price = mark_price * (_ONE - sl_price_pct / _HUNDRED)
                if sl_price > 0:
                    sl_price_str = round_price(sl_price, round_up=False)
            else:
                # short SL is ABOVE mark → round UP (away from entry)
                sl_price = mark_price * (_ONE + sl_price_pct / _HUNDRED)
                if sl_price > 0:
                    sl_price_str = round_price(sl_price, round_up=True)

        logger.info("place_trade_order_params", extra={
            "side": side, "symbol": symbol, "qty": str(qty_rounded),
            "mark_price": str(mark_price), "tp": tp_price_str, "sl": sl_price_str, "leverage": leverage,
        })

        try:
            result = await client.place_market_order(
                symbol=symbol,
                side=side,
                qty=str(qty_rounded),
                take_profit=tp_price_str,
                stop_loss=sl_price_str,
            )
        except Exception:
            logger.error("place_trade_exchange_failed", extra={
                "account_id": account_id, "symbol": symbol, "side": side, "qty": str(qty_rounded),
            })
            raise

        self.invalidate_cache(account_id)

        trade_record = None
        if self._trade_repo:
            try:
                async with self._db.pool.acquire() as conn, conn.transaction():
                    trade_record = await self._trade_repo.create_trade(
                        conn, account_id=account_id, symbol=symbol,
                        side=side, qty=float(qty_rounded), leverage=leverage,
                        margin_mode="isolated", order_type="market",
                        source=source, source_id=source_id, scan_result_id=scan_result_id,
                        stop_loss_price=float(sl_price_str) if sl_price_str else None,
                        take_profit_price=float(tp_price_str) if tp_price_str else None,
                        mark_price_at_open=float(mark_price),
                        capital_pct=capital_pct, base_capital=base_capital,
                        signal_direction=signal_direction, trade_direction=trade_direction,
                        take_profit_pct=take_profit_pct, stop_loss_pct=stop_loss_pct,
                        strategy_kind=strategy_kind, strategy_cohort=strategy_cohort,
                        f1_active=f1_active,
                        actor="system" if source == "cycle" else "user",
                    )
                    await self._trade_repo.update_trade_status(
                        conn, trade_id=str(trade_record["id"]),
                        account_id=account_id,
                        expected_version=trade_record["version"],
                        new_status="open",
                        event_type="filled", actor="system",
                        updates={
                            "order_id": result.get("orderId", ""),
                            "filled_qty": float(result.get("cumExecQty") or qty_rounded),
                            "entry_price": float(result.get("avgPrice") or mark_price),
                            "avg_fill_price": float(result.get("avgPrice") or mark_price),
                            "fees": float(result.get("cumExecFee") or 0),
                            "opened_at": datetime.now(timezone.utc),
                        },
                    )
                if self._trade_service:
                    self._trade_service.invalidate_stats_cache(account_id)
                    if trade_record:
                        await self._trade_service._broadcast_trade_event("trade.opened", trade_record)
            except Exception:
                logger.exception("trade_record_creation_failed", extra={
                    "account_id": account_id, "symbol": symbol, "side": side,
                    "order_id": result.get("orderId", ""),
                })

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info("place_trade_done", extra={
            "account_id": account_id, "symbol": symbol, "side": side,
            "trade_id": str(trade_record["id"]) if trade_record else None,
            "duration_ms": round(elapsed_ms, 1),
        })
        return {
            "side": side,
            "leverage": leverage,
            "max_leverage": max_leverage,
            "mark_price": str(mark_price),
            "take_profit_price": tp_price_str,
            "stop_loss_price": sl_price_str,
            "qty": str(qty_rounded),
            "usdt_amount": str(usdt_amount),
            "trade_id": str(trade_record["id"]) if trade_record else None,
        }

    # ── CRUD ────────────────────────────────────────────────────────────

    async def create_account(
        self, label: str, account_type: str, api_key: str, api_secret: str
    ) -> Dict[str, Any]:
        """Create a new trading account with encrypted credentials."""
        client = BybitClient(api_key, api_secret, account_type)
        try:
            test_result = await client.test_connection()
        finally:
            await client.close()
        if not test_result["success"]:
            raise ValueError(f"Connection test failed: {test_result['error']}")

        account_id = str(uuid.uuid4())
        now = _now_iso()
        await self._db.insert_account({
            "id": account_id,
            "label": label,
            "account_type": account_type,
            "api_key_masked": mask_api_key(api_key),
            "api_key_encrypted": encrypt_value(api_key),
            "api_secret_encrypted": encrypt_value(api_secret),
            "bybit_uid": test_result.get("uid"),
            "last_connected_at": now,
            "created_at": now,
            "updated_at": now,
        })

        result = await self._db.get_account(account_id)
        if self._ws_manager:
            asyncio.ensure_future(self._ws_manager.start_account(account_id))
        logger.info("create_account_done", extra={"account_id": account_id, "account_type": account_type})
        return result  # type: ignore

    async def list_accounts(self) -> List[Dict[str, Any]]:
        """Return all trading accounts with masked API keys."""
        return await self._db.list_accounts()

    async def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single account by ID, or None if not found."""
        return await self._db.get_account(account_id)

    async def update_account(self, account_id: str, label: str | None = None, is_active: bool | None = None, strategy_cohort: str | None = None) -> Optional[Dict[str, Any]]:
        """Update account label, active status, and/or strategy cohort (F3)."""
        fields: Dict[str, Any] = {"updated_at": _now_iso()}
        if label is not None:
            fields["label"] = label
        if is_active is not None:
            fields["is_active"] = 1 if is_active else 0
        if strategy_cohort is not None:
            fields["strategy_cohort"] = strategy_cohort
        await self._db.update_account(account_id, **fields)
        if is_active is False:
            await self.discard_client(account_id)
        return await self._db.get_account(account_id)

    async def rotate_credentials(
        self, account_id: str, api_key: str, api_secret: str
    ) -> Optional[Dict[str, Any]]:
        """Replace and re-encrypt API credentials, then verify connectivity."""
        account = await self._db.get_account(account_id)
        if not account:
            return None

        client = BybitClient(api_key, api_secret, account["account_type"])
        try:
            test_result = await client.test_connection()
        finally:
            await client.close()
        if not test_result["success"]:
            raise ValueError(f"Connection test failed: {test_result['error']}")

        await self._db.rotate_account_credentials(
            account_id,
            mask_api_key(api_key),
            encrypt_value(api_key),
            encrypt_value(api_secret),
            _now_iso(),
        )
        await self.discard_client(account_id)
        logger.info("rotate_credentials_done", extra={"account_id": account_id})
        return await self._db.get_account(account_id)

    async def delete_account(self, account_id: str) -> bool:
        """Soft-delete an account and invalidate its cache/client."""
        result = await self._db.soft_delete_account(account_id, _now_iso())
        if result:
            await self.discard_client(account_id)
            if self._ws_manager:
                asyncio.ensure_future(self._ws_manager.stop_account(account_id))
            try:
                modified_ids = await self._db.remove_account_from_scheduled_scans(account_id)
                if modified_ids:
                    logger.info("delete_account_cleaned_scheduled_scans", extra={"account_id": account_id, "schedule_ids": modified_ids})
            except Exception as e:
                logger.warning("delete_account_scheduled_scan_cleanup_failed", extra={"account_id": account_id, "error": str(e)[:200]})
            logger.info("delete_account_done", extra={"account_id": account_id})
        return result

    async def test_connection(self, account_id: str) -> Dict[str, Any]:
        """Verify exchange connectivity and return server time."""
        client = await self._build_client(account_id)
        result = await client.test_connection()
        now = _now_iso()
        if result["success"]:
            await self._db.update_account(
                account_id,
                last_connected_at=now, last_error=None, updated_at=now,
            )
        else:
            await self._db.update_account(
                account_id,
                last_error=_sanitize_error(result["error"] or ""), updated_at=now,
            )
        return result

    # ── Portfolio Data ──────────────────────────────────────────────────

    async def get_wallet(self, account_id: str) -> Dict[str, Any]:
        """Fetch wallet balances from exchange, cached with 30s TTL."""
        cache_key = f"{account_id}:wallet"
        cached = self._get_cached(cache_key, _WALLET_CACHE_TTL_S)
        if cached is not None:
            return cached

        client = await self._build_client(account_id)
        try:
            data = await client.get_wallet_balance()
            data["fetched_at"] = _now_iso()
            self._set_cached(cache_key, data, _WALLET_CACHE_TTL_S)
            await self._db.update_account(
                account_id,
                last_connected_at=_now_iso(), last_error=None, updated_at=_now_iso(),
            )
            return data
        except BybitAPIError as e:
            logger.warning("get_wallet_failed", extra={"account_id": account_id, "error": e.ret_msg[:200]})
            await self._db.update_account(
                account_id,
                last_error=_sanitize_error(e.ret_msg), updated_at=_now_iso(),
            )
            raise

    async def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Fetch open perpetual positions from exchange, cached with 15s TTL."""
        cache_key = f"{account_id}:positions"
        cached = self._get_cached(cache_key, _POSITIONS_CACHE_TTL_S)
        if cached is not None:
            return cached

        client = await self._build_client(account_id)
        data = await client.get_positions()
        self._set_cached(cache_key, data, _POSITIONS_CACHE_TTL_S)
        return data

    async def get_orders(self, account_id: str) -> List[Dict[str, Any]]:
        """Fetch active orders from exchange, cached with 15s TTL."""
        cache_key = f"{account_id}:orders"
        cached = self._get_cached(cache_key, _ORDERS_CACHE_TTL_S)
        if cached is not None:
            return cached

        client = await self._build_client(account_id)
        data = await client.get_open_orders()
        self._set_cached(cache_key, data, _ORDERS_CACHE_TTL_S)
        return data

    async def get_closed_pnl(
        self, account_id: str, start_date: str, end_date: str,
        page: int = 1, limit: int = 100,
    ) -> Dict[str, Any]:
        """Fetch closed PnL records for a date range from the database."""
        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (_ONE_DAY_MS - 1)

        if start_ms > end_ms:
            raise ValueError("start_date must be before or equal to end_date")

        days_diff = (end_ms - start_ms) / _ONE_DAY_MS
        if days_diff > _MAX_RANGE_DAYS:
            raise ValueError(f"Date range exceeds maximum of {_MAX_RANGE_DAYS} days")

        await self._fetch_and_store_closed_pnl(account_id, start_ms, end_ms)
        return await self._db.get_closed_pnl(account_id, start_ms, end_ms, page, limit)

    async def get_pnl_summary(
        self, account_id: str, start_date: str, end_date: str,
    ) -> Dict[str, Any]:
        """Compute aggregated PnL summary (total, win rate, avg) for a date range."""
        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (_ONE_DAY_MS - 1)

        if start_ms > end_ms:
            raise ValueError("start_date must be before or equal to end_date")

        days_diff = (end_ms - start_ms) / _ONE_DAY_MS
        if days_diff > _MAX_RANGE_DAYS:
            raise ValueError(f"Date range exceeds maximum of {_MAX_RANGE_DAYS} days")

        await self._fetch_and_store_closed_pnl(account_id, start_ms, end_ms)
        return await self._db.get_closed_pnl_summary(account_id, start_ms, end_ms)

    async def _fetch_and_store_closed_pnl(self, account_id: str, start_ms: int, end_ms: int) -> None:
        """Page through Bybit closed-PnL API in 7-day windows and persist records."""
        client = await self._build_client(account_id)
        current_start = start_ms
        max_pages = 50

        while current_start < end_ms:
            window_end = min(current_start + _SEVEN_DAYS_MS, end_ms)
            cursor = ""
            for _ in range(max_pages):
                result = await client.get_closed_pnl(current_start, window_end, limit=100, cursor=cursor)
                records = result.get("list", [])
                if records:
                    await self._db.insert_closed_pnl_records(account_id, records)
                next_cursor = result.get("nextPageCursor", "")
                if not next_cursor or not records:
                    break
                cursor = next_cursor
            current_start = window_end

    # ── Aggregation ─────────────────────────────────────────────────────

    async def _fetch_card(self, acc: Dict[str, Any], today_start_ms: int, today_end_ms: int) -> Dict[str, Any]:
        """Build a single dashboard card by fetching wallet, positions, and today's PnL."""
        if not acc["is_active"]:
            return {**acc, "total_equity": None, "total_perp_upl": None, "total_wallet_balance": None, "positions_count": 0, "today_pnl": None, "status": "disabled"}

        try:
            wallet, positions, _ = await asyncio.gather(
                self.get_wallet(acc["id"]),
                self.get_positions(acc["id"]),
                self._fetch_and_store_closed_pnl(acc["id"], today_start_ms, today_end_ms),
            )
            today_summary = await self._db.get_closed_pnl_summary(
                acc["id"], today_start_ms, today_end_ms,
            )
            return {
                **acc,
                "total_equity": wallet.get("totalEquity", "0"),
                "total_perp_upl": wallet.get("totalPerpUPL", "0"),
                "total_wallet_balance": wallet.get("totalWalletBalance", "0"),
                "positions_count": len(positions),
                "today_pnl": today_summary.get("total_pnl", "0"),
                "status": "active",
            }
        except Exception as e:
            return {
                **acc,
                "total_equity": None,
                "total_perp_upl": None,
                "total_wallet_balance": None,
                "positions_count": 0,
                "today_pnl": None,
                "status": "error",
                "last_error": _sanitize_error(str(e)),
            }

    async def get_dashboard(self) -> List[Dict[str, Any]]:
        """Build dashboard cards for all active accounts with equity, PnL, and positions."""
        accounts = await self._db.list_accounts()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_start_ms = _date_to_ms(today_str)
        today_end_ms = today_start_ms + (_ONE_DAY_MS - 1)

        cards = await asyncio.gather(
            *[self._fetch_card(acc, today_start_ms, today_end_ms) for acc in accounts]
        )
        cards = list(cards)

        try:
            rule_counts, rule_targets = await asyncio.gather(
                self._db.count_active_rules_by_account(),
                self._db.get_active_targets_by_account(),
            )
            for card in cards:
                card["active_rules_count"] = rule_counts.get(card["id"], 0)
                card["active_rule_targets"] = rule_targets.get(card["id"], [])
        except Exception:
            for card in cards:
                card["active_rules_count"] = 0
                card["active_rule_targets"] = []

        return cards

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """Aggregate wallet data across all active accounts into a portfolio summary."""
        accounts = await self._db.list_accounts()
        active_accs = [a for a in accounts if a["is_active"]]

        async def _fetch_wallet(acc_id: str) -> Optional[Dict[str, Any]]:
            """Fetch wallet for one account, returning None on failure."""
            try:
                return await self.get_wallet(acc_id)
            except Exception:
                return None

        results = await asyncio.gather(*[_fetch_wallet(a["id"]) for a in active_accs])

        total_equity = 0.0
        total_pnl = 0.0
        active_count = 0
        failed_count = 0
        for wallet in results:
            if wallet is not None:
                total_equity += float(wallet.get("totalEquity", 0))
                total_pnl += float(wallet.get("totalPerpUPL", 0))
                active_count += 1
            else:
                failed_count += 1

        return {
            "total_equity": str(total_equity),
            "total_unrealised_pnl": str(total_pnl),
            "active_accounts": active_count,
            "total_accounts": len(accounts),
            "failed_accounts": failed_count,
        }

    # ── Daily Snapshots ────────────────────────────────────────────────

    async def take_snapshot(self, account_id: str) -> Dict[str, Any]:
        """Capture a point-in-time snapshot of account equity, positions, and wallet."""
        account = await self._db.get_account(account_id)
        if not account:
            raise ValueError("Account not found")
        if not account["is_active"]:
            raise ValueError("Account is inactive")

        snap_key = f"snap:{account_id}"
        if not self._can_refresh(snap_key, cooldown=_SNAPSHOT_COOLDOWN_S):
            raise ValueError("Snapshot rate limited — try again in 30 seconds")
        self._mark_refreshed(snap_key)

        today_dt = datetime.now(timezone.utc).date()
        today = today_dt.isoformat()
        today_start_ms = _date_to_ms(today)
        today_end_ms = today_start_ms + (_ONE_DAY_MS - 1)

        wallet, positions = await asyncio.gather(
            self.get_wallet(account_id),
            self.get_positions(account_id),
        )

        equity = float(wallet.get("totalEquity") or 0)
        wallet_balance = float(wallet.get("totalWalletBalance") or 0)
        available_balance = float(wallet.get("totalAvailableBalance") or 0)
        unrealised_pnl = float(wallet.get("totalPerpUPL") or 0)
        margin_used = wallet_balance - available_balance if wallet_balance > available_balance else 0

        await self._fetch_and_store_closed_pnl(account_id, today_start_ms, today_end_ms)
        today_summary = await self._db.get_closed_pnl_summary(
            account_id, today_start_ms, today_end_ms,
        )
        realised_pnl = float(today_summary.get("total_pnl", 0))

        prev = await self._db.get_latest_snapshot(account_id)
        is_resnapshot = prev and str(prev["snapshot_date"]) == today
        if is_resnapshot:
            yesterday = await self._db.get_previous_snapshot(account_id, today_dt)
        else:
            yesterday = None

        if is_resnapshot and prev:
            prev_equity = yesterday["equity"] if yesterday else equity
            prev_cumulative = prev["cumulative_pnl"] - prev["realised_pnl"]
            prev_peak = max(prev["peak_equity"], yesterday["peak_equity"]) if yesterday else prev["peak_equity"]
        elif prev:
            prev_equity = prev["equity"]
            prev_cumulative = prev["cumulative_pnl"]
            prev_peak = prev["peak_equity"]
        else:
            prev_equity = equity
            prev_cumulative = 0
            prev_peak = equity
        daily_return_pct = ((equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0
        cumulative_pnl = prev_cumulative + realised_pnl
        peak_equity = max(prev_peak, equity)
        drawdown_pct = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0

        snapshot = {
            "account_id": account_id,
            "snapshot_date": today_dt,
            "equity": equity,
            "wallet_balance": wallet_balance,
            "available_balance": available_balance,
            "unrealised_pnl": unrealised_pnl,
            "realised_pnl": realised_pnl,
            "positions_count": len(positions),
            "margin_used": margin_used,
            "cumulative_pnl": cumulative_pnl,
            "daily_return_pct": round(daily_return_pct, 4),
            "peak_equity": peak_equity,
            "drawdown_pct": round(drawdown_pct, 4),
        }
        await self._db.upsert_daily_snapshot(snapshot)
        logger.info("take_snapshot_done", extra={
            "account_id": account_id, "equity": equity, "positions": len(positions),
        })
        return snapshot

    async def take_all_snapshots(self) -> List[Dict[str, Any]]:
        """Take snapshots for all active accounts concurrently."""
        accounts = await self._db.list_accounts()
        eligible = [a for a in accounts if a["is_active"] and a.get("include_in_analytics", True)]
        sem = asyncio.Semaphore(5)

        async def _snap_one(acc: Dict[str, Any]) -> Dict[str, Any]:
            """Take a daily snapshot for one account under semaphore, returning error dict on failure."""
            async with sem:
                try:
                    return await self.take_snapshot(acc["id"])
                except Exception as e:
                    logger.warning("Snapshot failed for %s: %s", acc["id"], e)
                    return {"account_id": acc["id"], "error": "snapshot_failed"}

        return list(await asyncio.gather(*[_snap_one(a) for a in eligible]))

    async def get_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve daily snapshots for an account within a date range."""
        rows = await self._db.get_daily_snapshots(account_id, start_date, end_date)
        for r in rows:
            if "snapshot_date" in r:
                r["snapshot_date"] = str(r["snapshot_date"])
        return rows

    async def get_portfolio_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate daily snapshots across all accounts into portfolio-level time series."""
        rows = await self._db.get_all_account_snapshots(start_date, end_date, account_type=account_type)
        aggregated: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            d = str(r["snapshot_date"])
            if d not in aggregated:
                aggregated[d] = {
                    "snapshot_date": d, "equity": 0, "wallet_balance": 0,
                    "available_balance": 0, "unrealised_pnl": 0, "realised_pnl": 0,
                    "positions_count": 0, "margin_used": 0, "cumulative_pnl": 0,
                    "daily_return_pct": 0, "drawdown_pct": 0, "peak_equity": 0,
                }
            agg = aggregated[d]
            agg["equity"] += r["equity"]
            agg["wallet_balance"] += r["wallet_balance"]
            agg["available_balance"] += r.get("available_balance", 0)
            agg["unrealised_pnl"] += r["unrealised_pnl"]
            agg["realised_pnl"] += r["realised_pnl"]
            agg["positions_count"] += r["positions_count"]
            agg["margin_used"] += r.get("margin_used", 0)
            agg["cumulative_pnl"] += r["cumulative_pnl"]

        result = sorted(aggregated.values(), key=lambda x: x["snapshot_date"])
        running_peak = result[0]["equity"] if result else 0.0
        prev_equity = 0.0
        for i, r in enumerate(result):
            running_peak = max(running_peak, r["equity"])
            r["peak_equity"] = running_peak
            if running_peak > 0:
                r["drawdown_pct"] = round((running_peak - r["equity"]) / running_peak * 100, 4)
            if i > 0 and prev_equity > 0:
                r["daily_return_pct"] = round((r["equity"] - prev_equity) / prev_equity * 100, 4)
            prev_equity = r["equity"]
        return result

    # ── High-Frequency Snapshot Queries ─────────────────────────────────

    @staticmethod
    def _hf_to_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a high-frequency DB row into the standardized snapshot dict shape."""
        ts = row["ts"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
        return {
            "snapshot_date": ts_str,
            "equity": row["equity"],
            "wallet_balance": row.get("balance", 0),
            "available_balance": 0,
            "unrealised_pnl": row.get("unrealised_pnl", 0),
            "realised_pnl": row.get("realised_pnl", 0),
            "positions_count": row.get("position_count", 0),
            "margin_used": 0,
            "cumulative_pnl": 0,
            "daily_return_pct": 0,
            "peak_equity": row["equity"],
            "drawdown_pct": 0,
        }

    def _enrich_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compute running peak equity, drawdown %, and daily return % across snapshot series."""
        if not snapshots:
            return []
        running_peak = snapshots[0]["equity"]
        prev_equity = 0.0
        for i, s in enumerate(snapshots):
            running_peak = max(running_peak, s["equity"])
            s["peak_equity"] = running_peak
            if running_peak > 0:
                s["drawdown_pct"] = round((running_peak - s["equity"]) / running_peak * 100, 4)
            if i > 0 and prev_equity > 0:
                s["daily_return_pct"] = round((s["equity"] - prev_equity) / prev_equity * 100, 4)
            prev_equity = s["equity"]
        return snapshots

    async def get_hf_snapshots(self, account_id: str, since_ts: datetime) -> List[Dict[str, Any]]:
        """Retrieve and enrich high-frequency snapshots for one account since a timestamp."""
        rows = await self._db.get_hf_snapshots(account_id, since_ts)
        snapshots = [self._hf_to_snapshot(r) for r in rows]
        return self._enrich_hf_snapshots(snapshots)

    async def get_portfolio_hf_snapshots(
        self, since_ts: datetime, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate high-frequency snapshots across accounts into portfolio-level time series."""
        rows = await self._db.get_all_hf_snapshots(since_ts, account_type=account_type)
        by_ts: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            ts = r["ts"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
            if ts_str not in by_ts:
                by_ts[ts_str] = {
                    "snapshot_date": ts_str, "equity": 0, "wallet_balance": 0,
                    "available_balance": 0, "unrealised_pnl": 0, "realised_pnl": 0,
                    "positions_count": 0, "margin_used": 0, "cumulative_pnl": 0,
                    "daily_return_pct": 0, "peak_equity": 0, "drawdown_pct": 0,
                }
            agg = by_ts[ts_str]
            agg["equity"] += r["equity"]
            agg["wallet_balance"] += r.get("balance", 0)
            agg["unrealised_pnl"] += r.get("unrealised_pnl", 0)
            agg["realised_pnl"] += r.get("realised_pnl", 0)
            agg["positions_count"] += r.get("position_count", 0)
        result = sorted(by_ts.values(), key=lambda x: x["snapshot_date"])
        return self._enrich_hf_snapshots(result)

    async def compute_hf_analytics(self, account_id: str, since_ts: datetime) -> Dict[str, Any]:
        """Compute performance analytics from high-frequency snapshots for one account."""
        snapshots = await self.get_hf_snapshots(account_id, since_ts)
        return self._compute_analytics_from_snapshots(snapshots, account_id)

    async def compute_portfolio_hf_analytics(
        self, since_ts: datetime, account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute high-frequency portfolio analytics from HF snapshots."""
        snapshots = await self.get_portfolio_hf_snapshots(since_ts, account_type=account_type)
        return self._compute_analytics_from_snapshots(snapshots, None)

    # ── Performance Analytics ──────────────────────────────────────────

    async def compute_analytics(
        self, account_id: str, start_date: str, end_date: str,
    ) -> Dict[str, Any]:
        """Compute full performance analytics (Sharpe, Sortino, drawdown, etc.) for one account."""
        snapshots = await self._db.get_daily_snapshots(account_id, start_date, end_date)
        if not snapshots:
            return self._empty_analytics()

        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (_ONE_DAY_MS - 1)
        pnl_summary = await self._db.get_closed_pnl_summary(account_id, start_ms, end_ms)

        equities = [s["equity"] for s in snapshots]
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                daily_returns.append(0)
        running_peak = equities[0] if equities else 0.0
        drawdowns = []
        for eq in equities:
            running_peak = max(running_peak, eq)
            dd = round((running_peak - eq) / running_peak * 100, 4) if running_peak > 0 else 0
            drawdowns.append(dd)

        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0

        sharpe = self._calc_sharpe(daily_returns)
        sortino = self._calc_sortino(daily_returns)
        calmar = self._calc_calmar(daily_returns, max_drawdown)

        max_consecutive_losses = self._max_consecutive(daily_returns, negative=True)
        max_consecutive_wins = self._max_consecutive(daily_returns, negative=False)

        dd_snapshots = [{"drawdown_pct": d} for d in drawdowns]
        dd_duration, recovery_time = self._calc_drawdown_duration(dd_snapshots)

        profit_factor = 0.0
        win_count = pnl_summary.get("win_count", 0)
        loss_count = pnl_summary.get("loss_count", 0)
        avg_win = float(pnl_summary.get("avg_win", 0))
        avg_loss = float(pnl_summary.get("avg_loss", 0))
        if avg_loss > 0 and loss_count > 0:
            gross_profit = avg_win * win_count
            gross_loss = avg_loss * loss_count
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        expectancy = 0.0
        total_trades = pnl_summary.get("total_count", win_count + loss_count)
        if total_trades > 0:
            expectancy = (avg_win * win_count - avg_loss * loss_count) / total_trades

        best_day = max(daily_returns) if daily_returns else 0
        worst_day = min(daily_returns) if daily_returns else 0

        best_idx = daily_returns.index(best_day) if daily_returns else 0
        worst_idx = daily_returns.index(worst_day) if daily_returns else 0
        best_date = str(snapshots[best_idx + 1]["snapshot_date"]) if daily_returns and best_idx + 1 < len(snapshots) else ""
        worst_date = str(snapshots[worst_idx + 1]["snapshot_date"]) if daily_returns and worst_idx + 1 < len(snapshots) else ""

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(sharpe), 2),
            "sortino_ratio": round(self._clamp(sortino), 2),
            "calmar_ratio": round(self._clamp(calmar), 2),
            "profit_factor": round(self._clamp(profit_factor, 0, 999.99), 2),
            "win_rate": pnl_summary.get("win_rate", 0),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": pnl_summary.get("avg_win", "0"),
            "avg_loss": pnl_summary.get("avg_loss", "0"),
            "expectancy": round(expectancy, 2),
            "avg_daily_return_pct": round(avg_daily_return, 4),
            "best_day_pct": round(best_day, 2),
            "best_day_date": best_date,
            "worst_day_pct": round(worst_day, 2),
            "worst_day_date": worst_date,
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": total_trades,
            "total_pnl": pnl_summary.get("total_pnl", "0"),
            "snapshot_count": len(snapshots),
        }

    async def compute_portfolio_analytics(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute aggregated performance analytics across all accounts in a date range."""
        portfolio_snaps = await self.get_portfolio_snapshots(start_date, end_date, account_type=account_type)
        if not portfolio_snaps:
            return self._empty_analytics()

        equities = [s["equity"] for s in portfolio_snaps]
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                daily_returns.append(0)

        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        drawdowns = [s.get("drawdown_pct", 0) for s in portfolio_snaps]
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0

        dd_duration, recovery_time = self._calc_drawdown_duration(portfolio_snaps)
        max_consecutive_losses = self._max_consecutive(daily_returns, negative=True)
        max_consecutive_wins = self._max_consecutive(daily_returns, negative=False)

        best_day = max(daily_returns) if daily_returns else 0
        worst_day = min(daily_returns) if daily_returns else 0
        best_idx = daily_returns.index(best_day) if daily_returns else 0
        worst_idx = daily_returns.index(worst_day) if daily_returns else 0
        best_date = portfolio_snaps[best_idx + 1]["snapshot_date"] if daily_returns and best_idx + 1 < len(portfolio_snaps) else ""
        worst_date = portfolio_snaps[worst_idx + 1]["snapshot_date"] if daily_returns and worst_idx + 1 < len(portfolio_snaps) else ""

        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (_ONE_DAY_MS - 1)
        pnl_summary = await self._db.get_portfolio_pnl_summary(start_ms, end_ms, account_type=account_type)

        win_count = pnl_summary.get("win_count", 0)
        loss_count = pnl_summary.get("loss_count", 0)
        avg_win = float(pnl_summary.get("avg_win", 0))
        avg_loss = float(pnl_summary.get("avg_loss", 0))
        profit_factor = 0.0
        if avg_loss > 0 and loss_count > 0:
            gross_profit = avg_win * win_count
            gross_loss = avg_loss * loss_count
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        total_trades = pnl_summary.get("total_count", win_count + loss_count)
        expectancy = (avg_win * win_count - avg_loss * loss_count) / total_trades if total_trades > 0 else 0.0

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(self._calc_sharpe(daily_returns)), 2),
            "sortino_ratio": round(self._clamp(self._calc_sortino(daily_returns)), 2),
            "calmar_ratio": round(self._clamp(self._calc_calmar(daily_returns, max_drawdown)), 2),
            "profit_factor": round(self._clamp(profit_factor, 0, 999.99), 2),
            "win_rate": pnl_summary.get("win_rate", 0),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": pnl_summary.get("avg_win", "0"),
            "avg_loss": pnl_summary.get("avg_loss", "0"),
            "expectancy": round(expectancy, 2),
            "avg_daily_return_pct": round(avg_daily_return, 4),
            "best_day_pct": round(best_day, 2),
            "best_day_date": str(best_date),
            "worst_day_pct": round(worst_day, 2),
            "worst_day_date": str(worst_date),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": total_trades,
            "total_pnl": pnl_summary.get("total_pnl", "0"),
            "snapshot_count": len(portfolio_snaps),
        }

    def _compute_analytics_from_snapshots(
        self, snapshots: List[Dict[str, Any]], account_id: Optional[str],
    ) -> Dict[str, Any]:
        """Derive analytics dict from pre-built snapshot series (shared by daily and HF paths)."""
        if not snapshots:
            return self._empty_analytics()

        equities = [s["equity"] for s in snapshots]
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                returns.append(0)

        drawdowns = [s.get("drawdown_pct", 0) for s in snapshots]
        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_return = sum(returns) / len(returns) if returns else 0

        dd_duration, recovery_time = self._calc_drawdown_duration(snapshots)
        max_consecutive_losses = self._max_consecutive(returns, negative=True)
        max_consecutive_wins = self._max_consecutive(returns, negative=False)

        best = max(returns) if returns else 0
        worst = min(returns) if returns else 0
        best_idx = returns.index(best) if returns else 0
        worst_idx = returns.index(worst) if returns else 0
        best_date = snapshots[best_idx + 1]["snapshot_date"] if returns and best_idx + 1 < len(snapshots) else ""
        worst_date = snapshots[worst_idx + 1]["snapshot_date"] if returns and worst_idx + 1 < len(snapshots) else ""

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(self._calc_sharpe(returns)), 2),
            "sortino_ratio": round(self._clamp(self._calc_sortino(returns)), 2),
            "calmar_ratio": round(self._clamp(self._calc_calmar(returns, max_drawdown)), 2),
            "profit_factor": 0,
            "win_rate": 0,
            "win_count": 0,
            "loss_count": 0,
            "avg_win": "0",
            "avg_loss": "0",
            "expectancy": 0,
            "avg_daily_return_pct": round(avg_return, 4),
            "best_day_pct": round(best, 2),
            "best_day_date": str(best_date),
            "worst_day_pct": round(worst, 2),
            "worst_day_date": str(worst_date),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": 0,
            "total_pnl": "0",
            "snapshot_count": len(snapshots),
        }

    @staticmethod
    def _empty_analytics() -> Dict[str, Any]:
        """Return a zeroed-out analytics dict as the default when no data is available."""
        return {
            "total_return_pct": 0, "max_drawdown_pct": 0,
            "sharpe_ratio": 0, "sortino_ratio": 0, "calmar_ratio": 0,
            "profit_factor": 0, "win_rate": 0, "win_count": 0, "loss_count": 0,
            "avg_win": "0", "avg_loss": "0", "expectancy": 0,
            "avg_daily_return_pct": 0, "best_day_pct": 0, "best_day_date": "",
            "worst_day_pct": 0, "worst_day_date": "", "max_consecutive_wins": 0,
            "max_consecutive_losses": 0, "drawdown_duration_days": 0,
            "recovery_time_days": 0, "total_trades": 0, "total_pnl": "0",
            "snapshot_count": 0,
        }

    @staticmethod
    def _clamp(value: float, lo: float = -999.99, hi: float = 999.99) -> float:
        """Clamp a float to [lo, hi], returning 0.0 for NaN/Inf."""
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return max(lo, min(hi, value))

    @staticmethod
    def _calc_sharpe(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Annualized Sharpe ratio from daily return percentages."""
        if len(daily_returns) < 2:
            return 0.0
        mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1))
        if std_r == 0:
            return 0.0
        return (mean_r / std_r) * math.sqrt(365)

    @staticmethod
    def _calc_sortino(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Annualized Sortino ratio (downside deviation only) from daily return percentages."""
        if len(daily_returns) < 2:
            return 0.0
        mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
        downside_sq = [min(r, 0) ** 2 for r in daily_returns]
        downside_dev = math.sqrt(sum(downside_sq) / (len(daily_returns) - 1))
        if downside_dev == 0:
            return 0.0
        return (mean_r / downside_dev) * math.sqrt(365)

    @staticmethod
    def _calc_calmar(daily_returns: List[float], max_drawdown: float) -> float:
        """Calmar ratio: annualized mean return divided by max drawdown percentage."""
        if not daily_returns or max_drawdown == 0:
            return 0.0
        annual_return = sum(daily_returns) / len(daily_returns) * 365
        return annual_return / max_drawdown

    @staticmethod
    def _max_consecutive(daily_returns: List[float], negative: bool) -> int:
        """Count the longest consecutive streak of positive (or negative) returns."""
        max_count = 0
        count = 0
        for r in daily_returns:
            if (negative and r < 0) or (not negative and r > 0):
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count

    @staticmethod
    def _calc_drawdown_duration(snapshots: List[Dict[str, Any]]) -> tuple[int, int]:
        """Return (max_drawdown_duration, max_recovery_time) in snapshot periods."""
        if not snapshots:
            return 0, 0
        max_duration = 0
        current_duration = 0
        max_recovery = 0
        recovery_start = -1
        for i, s in enumerate(snapshots):
            if s.get("drawdown_pct", 0) > 0:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
                if recovery_start < 0:
                    recovery_start = i
            else:
                if recovery_start >= 0:
                    max_recovery = max(max_recovery, i - recovery_start)
                current_duration = 0
                recovery_start = -1
        if recovery_start >= 0:
            max_recovery = max(max_recovery, len(snapshots) - recovery_start)
        return max_duration, max_recovery

    # ── High-Frequency Snapshots & Scheduler ──────────────────────────

    async def take_all_hf_snapshots(self) -> int:
        """Take high-frequency snapshots for all active accounts. Returns count saved."""
        accounts = await self._db.list_accounts()
        eligible = [a for a in accounts if a["is_active"] and a.get("include_in_analytics", True)]
        sem = asyncio.Semaphore(5)

        async def _snap_one(acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Fetch wallet + positions for one HF snapshot under semaphore, returning None on failure."""
            async with sem:
                try:
                    wallet = await self.get_wallet(acc["id"])
                    positions = await self.get_positions(acc["id"])
                    return {
                        "account_id": acc["id"],
                        "equity": float(wallet.get("totalEquity") or 0),
                        "unrealised_pnl": float(wallet.get("totalPerpUPL") or 0),
                        "realised_pnl": 0,
                        "balance": float(wallet.get("totalWalletBalance") or 0),
                        "position_count": len(positions),
                    }
                except Exception:
                    logger.warning("hf_snapshot_skipped", extra={"account_id": acc["id"]})
                    return None

        results = await asyncio.gather(*[_snap_one(a) for a in eligible])
        snapshots = [r for r in results if r is not None]
        if snapshots:
            return await self._db.insert_hf_snapshots(snapshots)
        if eligible:
            logger.warning("All %d eligible accounts failed HF snapshot", len(eligible))
        return 0

    async def auto_cleanup_old_snapshots(self) -> int:
        """Delete snapshots older than retention period. Returns rows deleted."""
        return await self._db.cleanup_old_hf_snapshots(max_age_days=_SNAPSHOT_RETENTION_DAYS)

    async def set_analytics_inclusion(self, account_id: str, include: bool) -> Optional[Dict[str, Any]]:
        """Toggle whether an account is included in analytics aggregations."""
        account = await self._db.get_account(account_id)
        if not account:
            return None
        await self._db.update_account(account_id, include_in_analytics=include)
        return await self._db.get_account(account_id)

    @staticmethod
    def _resolve_cleanup_dates(
        preset: Optional[str],
        before_date: Optional[str],
        after_date: Optional[str],
    ) -> tuple:
        """Convert a preset name (1w, 1m, 3m, 6m, 1y, all) into (before, after) date strings."""
        before_ts = before_date
        after_ts = after_date
        if preset:
            today = datetime.now(timezone.utc).date()
            preset_map = {
                "1w": timedelta(days=7),
                "1m": timedelta(days=30),
                "3m": timedelta(days=90),
                "6m": timedelta(days=180),
                "1y": timedelta(days=365),
            }
            if preset == "all":
                before_ts = None
                after_ts = None
            elif preset in preset_map:
                cutoff = today - preset_map[preset]
                before_ts = str(cutoff)
                after_ts = None
            else:
                raise ValueError(f"Invalid preset: {preset}")
        return before_ts, after_ts

    async def cleanup_snapshot_data(
        self,
        account_id: Optional[str],
        preset: Optional[str] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        tables: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Delete snapshot rows matching the date range/preset. Returns deleted counts per table."""
        if tables is None:
            tables = ["daily_snapshots", "high_freq_snapshots"]
        for table in tables:
            if table not in self._db._VALID_SNAPSHOT_TABLES:
                raise ValueError(f"Invalid table: {table}")
        before_ts, after_ts = self._resolve_cleanup_dates(preset, before_date, after_date)

        result: Dict[str, int] = {}
        for table in tables:
            count = await self._db.cleanup_snapshots(account_id, before_ts, after_ts, table)
            result[table] = count
        logger.info("cleanup_snapshot_data_done", extra={
            "account_id": account_id, "preset": preset, "tables": tables, "deleted": result,
        })
        return result

    async def count_snapshot_data(
        self,
        account_id: Optional[str],
        preset: Optional[str] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        tables: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Count snapshot rows matching the date range/preset without deleting."""
        if tables is None:
            tables = ["daily_snapshots", "high_freq_snapshots"]
        before_ts, after_ts = self._resolve_cleanup_dates(preset, before_date, after_date)

        result: Dict[str, int] = {}
        for table in tables:
            count = await self._db.count_snapshots(account_id, before_ts, after_ts, table)
            result[table] = count
        return result
