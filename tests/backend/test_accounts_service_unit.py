"""Unit tests for AccountsService — covers CRUD, caching, trade placement, and lifecycle."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.accounts_service import (
    AccountsService, _now_iso, _date_to_ms, _sanitize_error,
    clamp_sl_move_to_liquidation,
)


# ── SL-vs-liquidation clamp (money-critical regression) ───────────────────────


class TestStopLossLiquidationClamp:
    """The protective stop must fire BEFORE liquidation. clamp_sl_move_to_liquidation
    caps the SL price-move so a losing trade stops out instead of liquidating.
    Regression for the default config (stop_loss_pct=100, leverage=20)."""

    def test_default_config_is_clamped_inside_liquidation(self):
        # default: stop_loss_pct=100 / leverage=20 = 5.0% move; liquidation ~4.5% →
        # clamp to 0.9 * (1/20 - 0.005) * 100 = 4.05%
        out = clamp_sl_move_to_liquidation(Decimal("5.0"), 20)
        assert out == Decimal("4.05")
        liq_move = (Decimal("1") / 20 - Decimal("0.005")) * 100  # 4.5%
        assert out < liq_move

    def test_tight_stop_passes_through_unchanged(self):
        # stop_loss_pct=50 / leverage=20 = 2.5% move — already safe, untouched
        assert clamp_sl_move_to_liquidation(Decimal("2.5"), 20) == Decimal("2.5")

    def test_clamped_at_every_leverage(self):
        # the default stop_loss_pct=100 sits at/beyond liquidation at EVERY leverage
        for lev in (10, 20, 50):
            sl_move = Decimal("100") / lev
            liq_move = (Decimal("1") / lev - Decimal("0.005")) * 100
            out = clamp_sl_move_to_liquidation(sl_move, lev)
            assert out < liq_move, f"lev={lev}: clamped SL {out} not inside liq {liq_move}"

    def test_zero_or_negative_inputs_passthrough(self):
        assert clamp_sl_move_to_liquidation(Decimal("0"), 20) == Decimal("0")
        assert clamp_sl_move_to_liquidation(Decimal("3"), 0) == Decimal("3")


# ── Helper utilities tests ────────────────────────────────────────────────────


class TestHelperUtilities:
    def test_now_iso_format(self):
        result = _now_iso()
        assert len(result) in (19, 20)
        assert "T" in result

    def test_date_to_ms(self):
        ms = _date_to_ms("2024-01-01")
        assert ms == 1704067200000

    def test_sanitize_error_short(self):
        assert _sanitize_error("short") == "short"

    def test_sanitize_error_truncates(self):
        long_msg = "x" * 1000
        result = _sanitize_error(long_msg)
        assert len(result) == 512


# ── Cache tests ───────────────────────────────────────────────────────────────


class TestAccountsServiceCache:
    def _make_svc(self):
        db = AsyncMock()
        return AccountsService(db=db)

    def test_get_cached_miss(self):
        svc = self._make_svc()
        assert svc._get_cached("foo", 10) is None

    def test_set_and_get_cached(self):
        svc = self._make_svc()
        svc._set_cached("key1", {"data": 1}, ttl=60)
        result = svc._get_cached("key1", 60)
        assert result == {"data": 1}

    def test_cache_expired(self):
        svc = self._make_svc()
        svc._cache["key1"] = (time.monotonic() - 1, "old")
        assert svc._get_cached("key1", 60) is None

    def test_cache_eviction_at_max(self):
        svc = self._make_svc()
        svc._CACHE_MAX = 3
        svc._set_cached("a", 1, 60)
        svc._set_cached("b", 2, 60)
        svc._set_cached("c", 3, 60)
        svc._set_cached("d", 4, 60)
        assert len(svc._cache) <= 3

    def test_invalidate_cache_clears_keys(self):
        svc = self._make_svc()
        svc._cache["acc1:wallet"] = (time.monotonic() + 60, "data")
        svc._cache["acc1:positions"] = (time.monotonic() + 60, "data")
        svc._cache["acc2:wallet"] = (time.monotonic() + 60, "data")
        svc._refresh_locks["acc1"] = time.monotonic()
        svc.invalidate_cache("acc1")
        assert "acc1:wallet" not in svc._cache
        assert "acc1:positions" not in svc._cache
        assert "acc2:wallet" in svc._cache
        assert "acc1" not in svc._refresh_locks


# ── Refresh cooldown tests ────────────────────────────────────────────────────


class TestRefreshCooldown:
    def _make_svc(self):
        db = AsyncMock()
        return AccountsService(db=db)

    def test_can_refresh_when_never_refreshed(self):
        svc = self._make_svc()
        assert svc._can_refresh("acc1") is True

    def test_cannot_refresh_within_cooldown(self):
        svc = self._make_svc()
        svc._refresh_locks["acc1"] = time.monotonic()
        assert svc._can_refresh("acc1") is False

    def test_can_refresh_after_cooldown(self):
        svc = self._make_svc()
        svc._refresh_locks["acc1"] = time.monotonic() - 20
        assert svc._can_refresh("acc1") is True

    def test_mark_refreshed_prunes_stale(self):
        svc = self._make_svc()
        svc._CACHE_MAX = 2
        svc._refresh_locks["old1"] = time.monotonic() - 10000
        svc._refresh_locks["old2"] = time.monotonic() - 10000
        svc._refresh_locks["recent"] = time.monotonic()
        svc._mark_refreshed("new")
        assert "new" in svc._refresh_locks


# ── Client management tests ───────────────────────────────────────────────────


class TestBuildClient:
    @pytest.fixture
    def svc(self):
        db = AsyncMock()
        return AccountsService(db=db)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_build_client_not_found(self, svc):
        svc._db.get_account_credentials = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await svc._build_client("missing-id")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_build_client_caches(self, svc):
        mock_client = MagicMock()
        svc._clients["acc1"] = mock_client
        result = await svc._build_client("acc1")
        assert result is mock_client

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_client_delegates(self, svc):
        mock_client = MagicMock()
        svc._clients["acc1"] = mock_client
        result = await svc.get_client("acc1")
        assert result is mock_client


# ── Shutdown tests ────────────────────────────────────────────────────────────


class TestShutdown:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_closes_clients(self):
        db = AsyncMock()
        svc = AccountsService(db=db)
        mock_client = AsyncMock()
        svc._clients["c1"] = mock_client
        svc._cache["c1:wallet"] = (time.monotonic() + 60, "data")
        await svc.shutdown()
        mock_client.close.assert_awaited_once()
        assert len(svc._clients) == 0
        assert len(svc._cache) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_handles_client_error(self):
        db = AsyncMock()
        svc = AccountsService(db=db)
        mock_client = AsyncMock()
        mock_client.close.side_effect = Exception("close failed")
        svc._clients["c1"] = mock_client
        await svc.shutdown()
        assert len(svc._clients) == 0


# ── Client lifecycle (aiohttp session leak regression) ────────────────────────


class TestClientLifecycle:
    """invalidate_cache must NOT tear down the reusable BybitClient.

    Regression: invalidate_cache used to pop+close the pooled client on every trade
    and every position close, scheduling client.close() as a fire-and-forget task held
    only by a local var. The event loop keeps weak refs to tasks, so under load the GC
    reclaimed the close task before it ran — leaking the aiohttp ClientSession/connector
    ("Unclosed client session" / "Unclosed connector"). Concurrent trades on one account
    also orphaned a session when one trade closed the shared client mid-flight of another.

    Teardown that IS legitimate (credential rotation, deactivation, deletion) now goes
    through discard_client, which clears the cache AND awaits close() deterministically.
    """

    def _make_svc(self):
        db = AsyncMock()
        return AccountsService(db=db)

    def test_invalidate_cache_preserves_client(self):
        svc = self._make_svc()
        mock_client = AsyncMock()
        svc._clients["acc1"] = mock_client
        svc._cache["acc1:wallet"] = (time.monotonic() + 60, "data")
        svc._refresh_locks["acc1"] = time.monotonic()

        svc.invalidate_cache("acc1")

        # Stale data is cleared so the next poll refetches…
        assert "acc1:wallet" not in svc._cache
        assert "acc1" not in svc._refresh_locks
        # …but the healthy, reusable client is left intact and never torn down.
        assert svc._clients.get("acc1") is mock_client
        mock_client.close.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_discard_client_closes_and_removes(self):
        svc = self._make_svc()
        mock_client = AsyncMock()
        svc._clients["acc1"] = mock_client
        svc._cache["acc1:wallet"] = (time.monotonic() + 60, "data")
        svc._refresh_locks["acc1"] = time.monotonic()

        await svc.discard_client("acc1")

        assert "acc1:wallet" not in svc._cache
        assert "acc1" not in svc._refresh_locks
        assert "acc1" not in svc._clients
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_discard_client_without_cached_client_is_noop(self):
        svc = self._make_svc()
        svc._cache["acc1:wallet"] = (time.monotonic() + 60, "data")

        # No cached client for acc1 — must clear data and not raise.
        await svc.discard_client("acc1")

        assert "acc1:wallet" not in svc._cache

    @pytest.mark.asyncio(loop_scope="function")
    async def test_discard_client_swallows_close_error(self):
        svc = self._make_svc()
        mock_client = AsyncMock()
        mock_client.close.side_effect = Exception("close failed")
        svc._clients["acc1"] = mock_client

        # A failing close must not propagate, and the client must still be removed.
        await svc.discard_client("acc1")

        assert "acc1" not in svc._clients


# ── Trade dependencies ────────────────────────────────────────────────────────


class TestTradeDependencies:
    def test_set_trade_dependencies(self):
        db = AsyncMock()
        svc = AccountsService(db=db)
        repo = MagicMock()
        service = MagicMock()
        svc.set_trade_dependencies(repo, service)
        assert svc._trade_repo is repo
        assert svc._trade_service is service


# ── Create account tests ──────────────────────────────────────────────────────


class TestCreateAccount:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_account_connection_test_fails(self):
        db = AsyncMock()
        svc = AccountsService(db=db)

        with patch("backend.services.accounts_service.BybitClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.test_connection.return_value = {"success": False, "error": "auth failed"}
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            with pytest.raises(ValueError, match="Connection test failed"):
                await svc.create_account("Test", "demo", "key", "secret")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_account_success(self):
        db = AsyncMock()
        db.insert_account = AsyncMock()
        db.get_account = AsyncMock(return_value={"id": "abc", "label": "Test"})
        svc = AccountsService(db=db)

        with patch("backend.services.accounts_service.BybitClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.test_connection.return_value = {"success": True, "uid": "12345"}
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            with patch("backend.services.accounts_service.encrypt_value", return_value="enc"):
                with patch("backend.services.accounts_service.mask_api_key", return_value="***key"):
                    result = await svc.create_account("Test", "demo", "key", "secret")

        assert result["label"] == "Test"
        db.insert_account.assert_awaited_once()


# ── Place trade tests ─────────────────────────────────────────────────────────


class TestPlaceTrade:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_place_trade_invalid_source(self):
        db = AsyncMock()
        svc = AccountsService(db=db)
        with pytest.raises(ValueError, match="Invalid source"):
            await svc.place_trade(
                "acc1", "BTCUSDT", "buy", "straight", 10, 50, 25, 10, 1000, source="invalid"
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_place_trade_inactive_account(self):
        db = AsyncMock()
        db.get_account = AsyncMock(return_value={"is_active": False})
        db.get_account_credentials = AsyncMock(return_value={
            "api_key_encrypted": "enc_key",
            "api_secret_encrypted": "enc_secret",
            "account_type": "demo",
        })
        svc = AccountsService(db=db)

        with patch("backend.services.accounts_service.decrypt_value", return_value="value"):
            with patch("backend.services.accounts_service.BybitClient") as MockClient:
                mock_client = AsyncMock()
                MockClient.return_value = mock_client
                with pytest.raises(ValueError, match="inactive"):
                    await svc.place_trade(
                        "acc1", "BTCUSDT", "buy", "straight", 10, 50, 25, 10, 1000
                    )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_place_trade_reverse_direction(self):
        db = AsyncMock()
        db.get_account = AsyncMock(return_value={"is_active": True})
        db.get_account_credentials = AsyncMock(return_value={
            "api_key_encrypted": "enc_key",
            "api_secret_encrypted": "enc_secret",
            "account_type": "demo",
        })

        svc = AccountsService(db=db)

        with patch("backend.services.accounts_service.decrypt_value", return_value="value"):
            with patch("backend.services.accounts_service.BybitClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get_mark_price = AsyncMock(return_value="50000.00")
                mock_client.get_instrument_info = AsyncMock(return_value={
                    "leverageFilter": {"maxLeverage": "100"},
                    "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001", "maxOrderQty": "100"},
                    "priceFilter": {"tickSize": "0.01"},
                })
                mock_client.set_leverage = AsyncMock()
                mock_client.place_market_order = AsyncMock(return_value={"orderId": "ord123"})
                MockClient.return_value = mock_client

                result = await svc.place_trade(
                    "acc1", "BTCUSDT", "buy", "reverse", 10, 50, 25, 10, 1000
                )

        assert result["side"] == "Sell"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_place_trade_qty_below_minimum(self):
        db = AsyncMock()
        db.get_account = AsyncMock(return_value={"is_active": True})
        db.get_account_credentials = AsyncMock(return_value={
            "api_key_encrypted": "enc_key",
            "api_secret_encrypted": "enc_secret",
            "account_type": "demo",
        })

        svc = AccountsService(db=db)

        with patch("backend.services.accounts_service.decrypt_value", return_value="value"):
            with patch("backend.services.accounts_service.BybitClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get_mark_price = AsyncMock(return_value="50000.00")
                mock_client.get_instrument_info = AsyncMock(return_value={
                    "leverageFilter": {"maxLeverage": "100"},
                    "lotSizeFilter": {"minOrderQty": "1000", "qtyStep": "0.001", "maxOrderQty": "100000"},
                    "priceFilter": {"tickSize": "0.01"},
                })
                mock_client.set_leverage = AsyncMock()
                MockClient.return_value = mock_client

                with pytest.raises(ValueError, match="below minimum"):
                    await svc.place_trade(
                        "acc1", "BTCUSDT", "buy", "straight", 10, 50, 25, 1, 100
                    )
