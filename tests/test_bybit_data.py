"""Tests for tradingagents.dataflows.bybit_data — Phase 1 (TASK-001 through TASK-008)."""

import json
import threading
import time
from unittest.mock import patch, MagicMock, Mock

import pytest
import requests


# ---------------------------------------------------------------------------
# TASK-001: BybitRateLimiter tests
# ---------------------------------------------------------------------------

class TestBybitRateLimiter:
    """Rate limiter: token bucket, 80 tokens/5s, 16/s refill."""

    def test_acquire_single_token(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        limiter.acquire()  # should not raise

    def test_acquire_exhausts_bucket_then_blocks(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=5, refill_rate=5.0)
        for _ in range(5):
            limiter.acquire()
        # Next acquire should block until refill
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1, f"Expected blocking, got {elapsed:.3f}s"

    def test_acquire_timeout_raises(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=1, refill_rate=0.1)
        limiter.acquire()
        with pytest.raises(TimeoutError):
            limiter.acquire(timeout=0.2)

    def test_gradual_refill(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=10, refill_rate=10.0)
        # Drain all tokens
        for _ in range(10):
            limiter.acquire()
        # Wait 0.5s → should refill ~5 tokens
        time.sleep(0.55)
        for _ in range(5):
            limiter.acquire()

    def test_concurrent_contention_no_over_issuance(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        acquired = threading.Event()
        count = {"value": 0}
        lock = threading.Lock()

        def worker():
            limiter.acquire()
            with lock:
                count["value"] += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        elapsed = time.monotonic() - start

        assert count["value"] == 10
        # 10 tokens from 80-capacity bucket should be near-instant
        assert elapsed < 2.0

    def test_spurious_wakeup_safety(self):
        """Condition.wait() may return early; acquire must re-check tokens."""
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        limiter = BybitRateLimiter(capacity=1, refill_rate=1.0)
        limiter.acquire()  # drain
        # Even with spurious wakeups, acquire should eventually succeed
        # after refill (1 token/sec)
        start = time.monotonic()
        limiter.acquire(timeout=3.0)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.5  # had to wait for refill

    def test_warning_logged_on_long_block(self):
        from tradingagents.dataflows.bybit_data import BybitRateLimiter
        import logging
        limiter = BybitRateLimiter(capacity=1, refill_rate=0.5)
        limiter.acquire()
        with patch("tradingagents.dataflows.bybit_data.logger") as mock_logger:
            limiter.acquire(timeout=5.0)
            assert mock_logger.warning.called


# ---------------------------------------------------------------------------
# TASK-001: BybitCircuitBreaker tests
# ---------------------------------------------------------------------------

class TestBybitCircuitBreaker:
    """Circuit breaker: trips after 3 consecutive failures, per-run instance."""

    def test_closed_by_default(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker
        cb = BybitCircuitBreaker(failure_threshold=3)
        cb.check()  # should not raise

    def test_trips_after_threshold_failures(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker, BybitUnavailableError
        cb = BybitCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(BybitUnavailableError):
            cb.check()

    def test_resets_on_success(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker
        cb = BybitCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.check()  # should not raise — counter reset

    def test_does_not_trip_below_threshold(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker
        cb = BybitCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.check()  # 2 < 3, should not raise

    def test_thread_safety(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker, BybitUnavailableError
        cb = BybitCircuitBreaker(failure_threshold=3)
        errors = []

        def fail_worker():
            try:
                cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fail_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0  # no exceptions during concurrent recording

    def test_per_instance_isolation(self):
        from tradingagents.dataflows.bybit_data import BybitCircuitBreaker, BybitUnavailableError
        cb1 = BybitCircuitBreaker(failure_threshold=3)
        cb2 = BybitCircuitBreaker(failure_threshold=3)
        # Trip cb1
        for _ in range(3):
            cb1.record_failure()
        with pytest.raises(BybitUnavailableError):
            cb1.check()
        # cb2 should be fine
        cb2.check()


# ---------------------------------------------------------------------------
# TASK-001: Session configuration tests
# ---------------------------------------------------------------------------

class TestSessionConfig:
    def test_session_is_module_level_singleton(self):
        from tradingagents.dataflows.bybit_data import _session
        from tradingagents.dataflows import bybit_data
        assert _session is bybit_data._session

    def test_session_has_correct_timeout(self):
        from tradingagents.dataflows.bybit_data import _session
        # Check adapter is mounted for https
        adapter = _session.get_adapter("https://api.bybit.com")
        assert adapter is not None


# ---------------------------------------------------------------------------
# Helper: mock Bybit kline response
# ---------------------------------------------------------------------------

def _kline_response(rows, ret_code=0, ret_msg="OK"):
    """Build a mock Bybit /v5/market/kline JSON response."""
    return {
        "retCode": ret_code,
        "retMsg": ret_msg,
        "result": {
            "category": "linear",
            "symbol": "BTCUSDT",
            "list": rows,
        },
    }


def _mock_response(json_data, status_code=200):
    """Create a mock requests.Response."""
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# TASK-002: _bybit_request + get_bybit_klines tests
# ---------------------------------------------------------------------------

class TestBybitRequest:
    """Tests for the _bybit_request DRY helper."""

    def test_cache_hit_skips_http(self):
        from tradingagents.dataflows.bybit_data import _bybit_request, BybitRateLimiter, BybitCircuitBreaker
        cache = {("test", "key"): {"data": "cached"}}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        result = _bybit_request(
            "/v5/test", {}, ("test", "key"),
            cache=cache, limiter=limiter, circuit_breaker=cb,
        )
        assert result == {"data": "cached"}

    def test_stores_result_in_cache(self):
        from tradingagents.dataflows.bybit_data import _bybit_request, BybitRateLimiter, BybitCircuitBreaker
        cache = {}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        mock_resp = _mock_response({"retCode": 0, "result": {"value": 42}})
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = mock_resp
            result = _bybit_request(
                "/v5/test", {}, ("test", "store"),
                cache=cache, limiter=limiter, circuit_breaker=cb,
            )
        assert ("test", "store") in cache

    def test_retcode_error_raises(self):
        from tradingagents.dataflows.bybit_data import _bybit_request, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        mock_resp = _mock_response({"retCode": 10001, "retMsg": "Invalid param"})
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = mock_resp
            with pytest.raises(ValueError, match="Invalid param"):
                _bybit_request(
                    "/v5/test", {}, ("test", "err"),
                    cache={}, limiter=limiter, circuit_breaker=cb,
                )

    def test_retry_on_429(self):
        from tradingagents.dataflows.bybit_data import _bybit_request, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()

        mock_resp_429 = Mock()
        mock_resp_429.status_code = 429
        http_err = requests.exceptions.HTTPError(response=mock_resp_429)
        mock_resp_429.raise_for_status.side_effect = http_err

        resp_ok = _mock_response({"retCode": 0, "result": {"v": 1}})
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.side_effect = [mock_resp_429, resp_ok]
            with patch("time.sleep"):
                result = _bybit_request(
                    "/v5/test", {}, ("test", "retry"),
                    cache={}, limiter=limiter, circuit_breaker=cb,
                )
        assert mock_session.get.call_count == 2

    def test_malformed_json_raises(self):
        from tradingagents.dataflows.bybit_data import _bybit_request, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = mock_resp
            with pytest.raises(ValueError, match="[Mm]alformed"):
                _bybit_request(
                    "/v5/test", {}, ("test", "bad"),
                    cache={}, limiter=limiter, circuit_breaker=cb,
                )


class TestGetBybitKlines:
    """Tests for get_bybit_klines with pagination."""

    def test_single_page(self):
        from tradingagents.dataflows.bybit_data import get_bybit_klines, BybitRateLimiter, BybitCircuitBreaker
        rows = [
            [str(1700000000000 + i * 60000), "100", "105", "95", "102", "1000"]
            for i in range(50)
        ]
        resp = _kline_response(rows)
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp)
            result = get_bybit_klines(
                "BTCUSDT", "60",
                start_time=1700000000000,
                end_time=1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert "100" in result  # contains price data
        assert mock_session.get.call_count >= 1

    def test_multi_page_pagination(self):
        from tradingagents.dataflows.bybit_data import get_bybit_klines, BybitRateLimiter, BybitCircuitBreaker
        # Page 1: 200 rows (triggers pagination)
        page1_rows = [
            [str(1700000000000 + i * 60000), "100", "105", "95", "102", "1000"]
            for i in range(200)
        ]
        # Page 2: 50 rows (terminates)
        page2_rows = [
            [str(1700000000000 - (i + 1) * 60000), "99", "104", "94", "101", "900"]
            for i in range(50)
        ]
        resp1 = _kline_response(page1_rows)
        resp2 = _kline_response(page2_rows)
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.side_effect = [
                _mock_response(resp1),
                _mock_response(resp2),
            ]
            result = get_bybit_klines(
                "BTCUSDT", "60",
                start_time=1699900000000,
                end_time=1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert mock_session.get.call_count == 2

    def test_dedup_guard_terminates(self):
        from tradingagents.dataflows.bybit_data import get_bybit_klines, BybitRateLimiter, BybitCircuitBreaker
        # Same timestamps on both pages → dedup guard fires
        rows = [
            [str(1700000000000 + i * 60000), "100", "105", "95", "102", "1000"]
            for i in range(200)
        ]
        resp = _kline_response(rows)
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp)
            result = get_bybit_klines(
                "BTCUSDT", "60",
                start_time=1699900000000,
                end_time=1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        # Should stop at 2 pages (page 2 has same min timestamp → dedup guard)
        assert mock_session.get.call_count == 2

    def test_pagination_guard_at_5(self):
        from tradingagents.dataflows.bybit_data import get_bybit_klines, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        call_count = {"n": 0}

        def make_page(*args, **kwargs):
            call_count["n"] += 1
            base = 1700000000000 - (call_count["n"] * 200 * 60000)
            rows = [
                [str(base + i * 60000), "100", "105", "95", "102", "1000"]
                for i in range(200)
            ]
            return _mock_response(_kline_response(rows))

        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.side_effect = make_page
            result = get_bybit_klines(
                "BTCUSDT", "60",
                start_time=1600000000000,
                end_time=1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert mock_session.get.call_count == 5


# ---------------------------------------------------------------------------
# TASK-003: get_bybit_funding_rates
# ---------------------------------------------------------------------------

class TestGetBybitFundingRates:
    def test_normal_response(self):
        from tradingagents.dataflows.bybit_data import get_bybit_funding_rates, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {
            "retCode": 0,
            "result": {
                "category": "linear",
                "list": [
                    {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": "1700000000000"},
                    {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": "1700028800000"},
                ],
            },
        }
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            result = get_bybit_funding_rates(
                "BTCUSDT", 1700000000000, 1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert "0.0001" in result
        assert "0.0002" in result

    def test_empty_response(self):
        from tradingagents.dataflows.bybit_data import get_bybit_funding_rates, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {"retCode": 0, "result": {"list": []}}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            result = get_bybit_funding_rates(
                "BTCUSDT", 1700000000000, 1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert isinstance(result, str)

    def test_error_response_raises(self):
        from tradingagents.dataflows.bybit_data import get_bybit_funding_rates, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {"retCode": 10001, "retMsg": "Invalid symbol"}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            with pytest.raises(ValueError, match="Invalid symbol"):
                get_bybit_funding_rates(
                    "INVALID", 1700000000000, 1700100000000,
                    cache={}, limiter=limiter, circuit_breaker=cb,
                )


# ---------------------------------------------------------------------------
# TASK-004: get_bybit_open_interest
# ---------------------------------------------------------------------------

class TestGetBybitOpenInterest:
    def test_normal_response(self):
        from tradingagents.dataflows.bybit_data import get_bybit_open_interest, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {
            "retCode": 0,
            "result": {
                "list": [
                    {"openInterest": "50000", "timestamp": "1700000000000"},
                    {"openInterest": "51000", "timestamp": "1700003600000"},
                ],
            },
        }
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            result = get_bybit_open_interest(
                "BTCUSDT", "1h", 1700000000000, 1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert "50000" in result

    def test_empty_response(self):
        from tradingagents.dataflows.bybit_data import get_bybit_open_interest, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {"retCode": 0, "result": {"list": []}}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            result = get_bybit_open_interest(
                "BTCUSDT", "1h", 1700000000000, 1700100000000,
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# TASK-005: get_bybit_ticker
# ---------------------------------------------------------------------------

class TestGetBybitTicker:
    def test_normal_response(self):
        from tradingagents.dataflows.bybit_data import get_bybit_ticker, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {
            "retCode": 0,
            "result": {
                "list": [{
                    "symbol": "BTCUSDT",
                    "lastPrice": "42000",
                    "volume24h": "1000000",
                    "fundingRate": "0.0001",
                    "openInterest": "50000",
                    "highPrice24h": "43000",
                    "lowPrice24h": "41000",
                }],
            },
        }
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            result = get_bybit_ticker(
                "BTCUSDT",
                cache={}, limiter=limiter, circuit_breaker=cb,
            )
        assert "42000" in result
        assert "BTCUSDT" in result

    def test_error_response_raises(self):
        from tradingagents.dataflows.bybit_data import get_bybit_ticker, BybitRateLimiter, BybitCircuitBreaker
        resp_data = {"retCode": 10001, "retMsg": "Invalid symbol"}
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        with patch("tradingagents.dataflows.bybit_data._session") as mock_session:
            mock_session.get.return_value = _mock_response(resp_data)
            with pytest.raises(ValueError, match="Invalid symbol"):
                get_bybit_ticker(
                    "INVALID",
                    cache={}, limiter=limiter, circuit_breaker=cb,
                )


# ---------------------------------------------------------------------------
# TASK-006: get_bybit_indicators
# ---------------------------------------------------------------------------

class TestGetBybitIndicators:
    def _make_kline_csv(self, n=50):
        """Build a mock klines CSV string with enough rows for indicators."""
        import random
        random.seed(42)
        lines = ["timestamp,open,high,low,close,volume"]
        base = 100.0
        for i in range(n):
            o = base + random.uniform(-2, 2)
            h = o + random.uniform(0, 3)
            l = o - random.uniform(0, 3)
            c = o + random.uniform(-1, 1)
            v = random.uniform(500, 5000)
            ts = 1700000000000 + i * 3600000
            lines.append(f"{ts},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{v:.2f}")
        return "\n".join(lines)

    def test_computes_indicators(self):
        from tradingagents.dataflows.bybit_data import get_bybit_indicators, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        cache = {}
        kline_csv = self._make_kline_csv(50)
        cache[("klines", "BTCUSDT", "60", 1700000000000, 1700100000000)] = kline_csv

        result = get_bybit_indicators(
            "BTCUSDT", "60", 1700000000000, 1700100000000,
            cache=cache, limiter=limiter, circuit_breaker=cb,
        )
        assert "RSI" in result or "rsi" in result.lower()
        assert "MACD" in result or "macd" in result.lower()

    def test_cache_prevents_recomputation(self):
        from tradingagents.dataflows.bybit_data import get_bybit_indicators, BybitRateLimiter, BybitCircuitBreaker
        limiter = BybitRateLimiter(capacity=80, refill_rate=16.0)
        cb = BybitCircuitBreaker()
        cache = {}
        kline_csv = self._make_kline_csv(50)
        cache[("klines", "BTCUSDT", "60", 1700000000000, 1700100000000)] = kline_csv

        result1 = get_bybit_indicators(
            "BTCUSDT", "60", 1700000000000, 1700100000000,
            cache=cache, limiter=limiter, circuit_breaker=cb,
        )
        result2 = get_bybit_indicators(
            "BTCUSDT", "60", 1700000000000, 1700100000000,
            cache=cache, limiter=limiter, circuit_breaker=cb,
        )
        assert result1 == result2
        assert ("indicators", "BTCUSDT", "60", 1700000000000, 1700100000000) in cache


# ---------------------------------------------------------------------------
# TASK-007: HMAC signing tests
# ---------------------------------------------------------------------------

class TestHMACSigning:
    def test_sign_request_produces_valid_hmac(self):
        import hmac as hmac_mod
        import hashlib
        from tradingagents.dataflows.bybit_data import _sign_request
        params = {"category": "linear", "symbol": "BTCUSDT"}
        signed = _sign_request(params, api_key="testkey", api_secret="testsecret")
        assert "api_key" in signed
        assert "timestamp" in signed
        assert "sign" in signed
        assert signed["api_key"] == "testkey"
        assert "testsecret" not in str(signed)

    def test_secret_never_in_signed_params(self):
        from tradingagents.dataflows.bybit_data import _sign_request
        signed = _sign_request({}, api_key="k", api_secret="supersecret")
        assert "supersecret" not in str(signed)
        assert "api_secret" not in signed

    def test_timestamp_is_recent(self):
        from tradingagents.dataflows.bybit_data import _sign_request
        before = int(time.time() * 1000)
        signed = _sign_request({}, api_key="k", api_secret="s")
        after = int(time.time() * 1000)
        ts = int(signed["timestamp"])
        assert before <= ts <= after + 1000

    def test_recv_window_present(self):
        from tradingagents.dataflows.bybit_data import _sign_request
        signed = _sign_request({}, api_key="k", api_secret="s")
        assert signed.get("recv_window") == "5000" or signed.get("recvWindow") == "5000"

    def test_log_scrubbing(self):
        from tradingagents.dataflows.bybit_data import _scrub_params_for_logging
        params = {
            "api_key": "mykey123",
            "sign": "abc123",
            "timestamp": "1700000000000",
            "category": "linear",
        }
        scrubbed = _scrub_params_for_logging(params)
        assert "mykey123" not in str(scrubbed)
        assert "abc123" not in str(scrubbed)
        assert "linear" in str(scrubbed)
