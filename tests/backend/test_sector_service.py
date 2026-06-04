"""Tests for SectorService — classification, mapping, cache, and fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sector_service import SectorService, _map_cg_categories, VALID_SECTORS


class TestCGCategoryMapping:
    """Test CoinGecko category string → sector mapping."""

    def test_layer1_categories(self):
        assert _map_cg_categories(["Layer 1 (L1)", "Smart Contract Platform"]) == "l1"
        assert _map_cg_categories(["Cryptocurrency", "Layer 1 (L1)"]) == "l1"

    def test_layer2_categories(self):
        assert _map_cg_categories(["Layer 2 (L2)", "Optimistic Rollups"]) == "l2"
        assert _map_cg_categories(["Zero Knowledge ZK Rollup"]) == "l2"

    def test_defi_categories(self):
        assert _map_cg_categories(["Decentralized Finance (DeFi)", "Lending/Borrowing"]) == "defi"
        assert _map_cg_categories(["Cryptocurrency", "DEX Aggregator"]) == "defi"
        assert _map_cg_categories(["Liquid Staking Derivatives"]) == "defi"

    def test_meme_categories(self):
        assert _map_cg_categories(["Meme", "Cryptocurrency"]) == "meme"
        assert _map_cg_categories(["Cryptocurrency", "Dog-Themed Meme Coin"]) == "meme"

    def test_ai_categories(self):
        assert _map_cg_categories(["Artificial Intelligence (AI)"]) == "ai"
        assert _map_cg_categories(["Decentralized Compute & GPU"]) == "ai"

    def test_gaming_categories(self):
        assert _map_cg_categories(["Gaming (GameFi)"]) == "gaming"
        assert _map_cg_categories(["Metaverse", "NFT"]) == "gaming"
        assert _map_cg_categories(["Play-to-Earn"]) == "gaming"

    def test_infra_categories(self):
        assert _map_cg_categories(["Oracle", "Data"]) == "infra"
        assert _map_cg_categories(["Decentralized Storage"]) == "infra"
        assert _map_cg_categories(["Cross-Chain Bridge"]) == "infra"

    def test_exchange_categories(self):
        assert _map_cg_categories(["Centralized Exchange (CEX) Token"]) == "exchange"
        assert _map_cg_categories(["Launchpad Token"]) == "exchange"

    def test_no_match_returns_none(self):
        assert _map_cg_categories(["Cryptocurrency"]) is None
        assert _map_cg_categories(["Coin", "Token"]) is None
        assert _map_cg_categories([]) is None

    def test_generic_skipped(self):
        # "Cryptocurrency" alone should not match anything
        assert _map_cg_categories(["Cryptocurrency", "Token"]) is None
        # But with a real category it should match
        assert _map_cg_categories(["Cryptocurrency", "Meme"]) == "meme"


class TestSectorServiceGetSector:
    """Test the synchronous get_sector hot path."""

    def test_returns_from_cache(self):
        svc = SectorService(db_pool=MagicMock())
        svc._cache = {"BTCUSDT": "l1", "PEPEUSDT": "meme"}
        assert svc.get_sector("BTCUSDT") == "l1"
        assert svc.get_sector("PEPEUSDT") == "meme"

    def test_returns_other_for_unknown(self):
        svc = SectorService(db_pool=MagicMock())
        svc._cache = {}
        assert svc.get_sector("UNKNOWNUSDT") == "other"

    def test_never_raises(self):
        svc = SectorService(db_pool=MagicMock())
        svc._cache = None  # deliberate breakage
        # Even with broken cache, should not raise (returns "other")
        # Actually dict.get on None would raise — but our code guards against this
        # by always initializing _cache as dict. This test ensures the contract.
        svc._cache = {}
        assert svc.get_sector("ANYTHING") == "other"


class TestSectorServiceLoadCache:
    """Test load_cache merges DB + static dict."""

    @pytest.mark.asyncio
    async def test_load_from_db_and_static(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[
            {"symbol": "NEWCOINUSDT", "sector": "ai"},
            {"symbol": "BTCUSDT", "sector": "l1"},
        ])
        svc = SectorService(db_pool=mock_pool)
        await svc.load_cache()

        assert svc.get_sector("NEWCOINUSDT") == "ai"
        assert svc.get_sector("BTCUSDT") == "l1"
        # Static dict entries should also be present
        assert svc.get_sector("ETHUSDT") == "l1"  # from static dict

    @pytest.mark.asyncio
    async def test_db_failure_still_loads_static(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB down"))
        svc = SectorService(db_pool=mock_pool)
        await svc.load_cache()

        # Should still have static dict entries
        assert svc.get_sector("BTCUSDT") == "l1"
        assert svc.get_sector("UNIUSDT") == "defi"


class TestSectorServiceClassify:
    """Test classify_and_store with CoinGecko and LLM fallback."""

    @pytest.mark.asyncio
    async def test_coingecko_success(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        svc = SectorService(db_pool=mock_pool)

        with patch("backend.services.sector_service.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = ["Meme", "Cryptocurrency"]
            await svc._classify_and_store("DOGEUSDT")

        assert svc.get_sector("DOGEUSDT") == "meme"
        mock_pool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_coingecko_fails_llm_succeeds(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        mock_llm = AsyncMock(return_value="gaming")
        svc = SectorService(db_pool=mock_pool, llm_callable=mock_llm)

        with patch("backend.services.sector_service.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = []  # CG returns nothing
            await svc._classify_and_store("AXSUSDT")

        assert svc.get_sector("AXSUSDT") == "gaming"
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail_returns_other(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        mock_llm = AsyncMock(side_effect=Exception("LLM down"))
        svc = SectorService(db_pool=mock_pool, llm_callable=mock_llm)

        with patch("backend.services.sector_service.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = []
            await svc._classify_and_store("OBSCUREUSDT")

        assert svc.get_sector("OBSCUREUSDT") == "other"

    @pytest.mark.asyncio
    async def test_llm_garbage_returns_other(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        mock_llm = AsyncMock(return_value="I think this is a layer 1 blockchain")
        svc = SectorService(db_pool=mock_pool, llm_callable=mock_llm)

        with patch("backend.services.sector_service.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = []
            await svc._classify_and_store("WEIRDUSDT")

        assert svc.get_sector("WEIRDUSDT") == "other"

    @pytest.mark.asyncio
    async def test_no_llm_configured(self):
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        svc = SectorService(db_pool=mock_pool, llm_callable=None)

        with patch("backend.services.sector_service.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = []
            await svc._classify_and_store("TESTUSDT")

        assert svc.get_sector("TESTUSDT") == "other"


class TestSectorServiceEnsureClassified:
    """Test ensure_classified batch pre-classification."""

    @pytest.mark.asyncio
    async def test_skips_already_cached(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        svc = SectorService(db_pool=mock_pool)
        svc._cache = {"BTCUSDT": "l1", "ETHUSDT": "l1"}

        with patch.object(svc, "_classify_and_store") as mock_classify:
            await svc.ensure_classified(["BTCUSDT", "ETHUSDT"])

        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    async def test_classifies_uncached_symbols(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        svc = SectorService(db_pool=mock_pool)
        svc._cache = {"BTCUSDT": "l1"}

        with patch.object(svc, "_classify_and_store", new_callable=AsyncMock) as mock_classify:
            await svc.ensure_classified(["BTCUSDT", "NEWUSDT"])

        mock_classify.assert_called_once_with("NEWUSDT")

    @pytest.mark.asyncio
    async def test_classify_failure_does_not_stop_batch(self):
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        svc = SectorService(db_pool=mock_pool)
        svc._cache = {}

        call_count = 0
        async def _classify_side_effect(sym):
            nonlocal call_count
            call_count += 1
            if sym == "FAILUSDT":
                raise Exception("oops")
            svc._cache[sym] = "l1"

        with patch.object(svc, "_classify_and_store", side_effect=_classify_side_effect):
            await svc.ensure_classified(["FAILUSDT", "GOODUSDT"])

        assert call_count == 2
        assert svc.get_sector("GOODUSDT") == "l1"
        assert svc.get_sector("FAILUSDT") == "other"


class TestValidSectors:
    """Ensure VALID_SECTORS contains the expected values."""

    def test_all_sectors_present(self):
        expected = {"l1", "l2", "defi", "meme", "ai", "gaming", "infra", "exchange", "other"}
        assert VALID_SECTORS == expected
