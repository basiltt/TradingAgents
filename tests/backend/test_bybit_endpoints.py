"""Tests for the Bybit endpoint -> (channel, endpoint_class) registry (TASK-0.1)."""
import pytest

from backend.services.bybit_endpoints import (
    classify_endpoint,
    EndpointClassificationError,
    PUBLIC,
    PRIVATE,
)


class TestEndpointClassification:
    def test_market_endpoints_are_public(self):
        for path in (
            "/v5/market/tickers",
            "/v5/market/instruments-info",
            "/v5/market/kline",
            "/v5/market/time",
        ):
            channel, ep_class = classify_endpoint(path)
            assert channel == PUBLIC, f"{path} should be public"
            assert ep_class == "market"

    def test_order_create_is_private_order_create(self):
        channel, ep_class = classify_endpoint("/v5/order/create")
        assert channel == PRIVATE
        assert ep_class == "order_create"

    def test_order_cancel_class(self):
        assert classify_endpoint("/v5/order/cancel") == (PRIVATE, "order_cancel")

    def test_set_leverage_class(self):
        assert classify_endpoint("/v5/position/set-leverage") == (PRIVATE, "set_leverage")

    def test_set_trading_stop_class(self):
        assert classify_endpoint("/v5/position/trading-stop") == (PRIVATE, "set_trading_stop")

    def test_position_list_class(self):
        assert classify_endpoint("/v5/position/list") == (PRIVATE, "position_list")

    def test_wallet_balance_class(self):
        assert classify_endpoint("/v5/account/wallet-balance") == (PRIVATE, "wallet")

    def test_order_history_is_order_query(self):
        assert classify_endpoint("/v5/order/history") == (PRIVATE, "order_query")
        assert classify_endpoint("/v5/order/realtime") == (PRIVATE, "order_query")

    def test_unmapped_path_raises(self):
        with pytest.raises(EndpointClassificationError):
            classify_endpoint("/v5/some/unmapped/path")

    def test_query_string_is_ignored(self):
        # classify works on the path even if a caller passes a trailing query
        channel, ep_class = classify_endpoint("/v5/market/tickers?category=linear")
        assert channel == PUBLIC and ep_class == "market"

    def test_registry_validation_passes(self):
        """Every private endpoint class must have a per-second cap (no silent un-limit)."""
        from backend.services.bybit_endpoints import validate_registry
        validate_registry()  # must not raise

    def test_every_private_class_has_a_cap(self):
        from backend.services.bybit_endpoints import _REGISTRY, ENDPOINT_PER_SECOND_CAP, PRIVATE
        for channel, ep_class in _REGISTRY.values():
            if channel == PRIVATE:
                assert ep_class in ENDPOINT_PER_SECOND_CAP, f"{ep_class} missing a cap"

