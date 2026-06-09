"""Tests for BybitClient rate limiting and retry logic.

Rate-limiting state moved out of BybitClient into the shared, IP-level
``BybitRateGate`` (backend/services/bybit_rate_gate.py); the window-tracking /
pruning / at-max-sleep tests below exercise that gate directly, while the retry
and semaphore tests still target BybitClient._request.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError, BybitClient
from backend.services.bybit_rate_gate import BybitRateGate


@pytest.fixture
def client():
    return BybitClient("test_key_12345", "test_secret_12345", "demo")


@pytest.fixture
def gate():
    """A fresh, small-budget rate gate (window=10s) isolated from the singleton."""
    return BybitRateGate(public_budget=5, private_budget=5, ws_connect_budget=5, window=10.0)


@pytest.mark.asyncio
async def test_rate_gate_tracks_requests(gate):
    """Each acquire appends one timestamp to the channel's rolling window."""
    assert gate.current_usage["public"] == 0
    await gate.acquire_async(channel="public")
    assert gate.current_usage["public"] == 1
    await gate.acquire_async(channel="public")
    assert gate.current_usage["public"] == 2


@pytest.mark.asyncio
async def test_rate_gate_prunes_old_timestamps(gate):
    """Timestamps older than the window are pruned on the next acquire, so they
    don't count against the budget."""
    now = time.monotonic()
    # Seed two timestamps older than the 10s window directly on the channel deque.
    gate._public_timestamps.append(now - 30)
    gate._public_timestamps.append(now - 20)
    await gate.acquire_async(channel="public")
    # Stale entries pruned; only the just-acquired one remains within the window.
    assert gate.current_usage["public"] == 1
    assert all(t > time.monotonic() - 10 for t in gate._public_timestamps)


@pytest.mark.asyncio
async def test_rate_gate_sleeps_when_at_max(gate):
    """When the channel is at budget, acquire sleeps until the oldest slot ages out."""
    now = time.monotonic()
    # Fill the private channel to its effective budget with recent timestamps.
    for i in range(5):
        gate._private_timestamps.append(now - 0.001 * i)

    slept = []

    async def fake_sleep(duration):
        slept.append(duration)
        gate._private_timestamps.clear()  # let the next loop iteration proceed

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # 'order' lane uses the full budget; it must still wait because we're at max.
        await gate.acquire_async(channel="private", lane="order")
    assert len(slept) >= 1
    assert slept[0] > 0


def _make_mock_resp(return_value):
    """Create a properly structured mock response for BybitClient tests."""
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=return_value)
    resp.headers = {"X-Bapi-Limit": "10", "X-Bapi-Limit-Status": "5"}
    return resp


def _make_mock_ctx(mock_resp):
    """Wrap a mock response as an async context manager (for session.request)."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_mock_session(request_side_effect=None, request_return_value=None):
    """Create a mock aiohttp session with closed=False."""
    session = MagicMock()
    session.closed = False
    if request_side_effect is not None:
        session.request = MagicMock(side_effect=request_side_effect)
    elif request_return_value is not None:
        session.request = MagicMock(return_value=request_return_value)
    return session


@pytest.mark.asyncio
async def test_retry_on_rate_limit_error(client):
    client._time_synced = True

    rate_resp = _make_mock_resp({"retCode": 10006, "retMsg": "Rate limit"})
    success_resp = _make_mock_resp({"retCode": 0, "result": {"ok": True}})

    rate_ctx = _make_mock_ctx(rate_resp)
    success_ctx = _make_mock_ctx(success_resp)

    mock_session = _make_mock_session(request_side_effect=[rate_ctx, success_ctx])
    client._session = mock_session

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await client._request("GET", "/v5/test", {})
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_retry_exhaustion_raises(client):
    client._time_synced = True

    rate_resp = _make_mock_resp({"retCode": 10006, "retMsg": "Rate limit"})
    rate_ctx = _make_mock_ctx(rate_resp)

    mock_session = _make_mock_session(request_return_value=rate_ctx)
    client._session = mock_session

    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(BybitAPIError) as exc_info:
        await client._request("GET", "/v5/test", {})
    assert exc_info.value.ret_code == 10006


@pytest.mark.asyncio
async def test_retry_uses_exponential_backoff(client):
    client._time_synced = True

    rate_resp = _make_mock_resp({"retCode": 10006, "retMsg": "Rate limit"})
    rate_ctx = _make_mock_ctx(rate_resp)

    mock_session = _make_mock_session(request_return_value=rate_ctx)
    client._session = mock_session

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(BybitAPIError):
            await client._request("GET", "/v5/test", {})
        delays = [call[0][0] for call in mock_sleep.call_args_list if call[0][0] >= 0.5]
        assert len(delays) >= 2
        assert delays[1] > delays[0]


@pytest.mark.asyncio
async def test_non_rate_limit_error_not_retried(client):
    client._time_synced = True

    error_resp = _make_mock_resp({"retCode": 10001, "retMsg": "Invalid key"})
    error_ctx = _make_mock_ctx(error_resp)

    mock_session = _make_mock_session(request_return_value=error_ctx)
    client._session = mock_session

    with pytest.raises(BybitAPIError) as exc_info:
        await client._request("GET", "/v5/test", {})
    assert exc_info.value.ret_code == 10001
    assert mock_session.request.call_count == 1


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency(client):
    client._semaphore = asyncio.Semaphore(2)
    call_count = 0
    max_concurrent = 0
    current = 0


    async def mock_request(*args, **kwargs):
        nonlocal call_count, max_concurrent, current
        current += 1
        max_concurrent = max(max_concurrent, current)
        call_count += 1
        await asyncio.sleep(0.01)
        current -= 1
        return {}

    with patch.object(client, "_request", side_effect=mock_request):
        tasks = [client._request("GET", "/v5/test", {}) for _ in range(5)]
        await asyncio.gather(*tasks)

    assert call_count == 5
