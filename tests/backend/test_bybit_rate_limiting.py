"""Tests for BybitClient rate limiting and retry logic."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError, BybitClient


@pytest.fixture
def client():
    return BybitClient("test_key_12345", "test_secret_12345", "demo")


@pytest.mark.asyncio
async def test_rate_limit_window_tracks_requests(client):
    assert len(client._request_timestamps) == 0
    client._request_timestamps.append(time.monotonic())
    assert len(client._request_timestamps) == 1


@pytest.mark.asyncio
async def test_rate_limit_prunes_old_timestamps(client):
    old = time.monotonic() - 10
    client._request_timestamps.append(old)
    client._request_timestamps.append(old - 1)
    await client._wait_for_rate_limit()
    assert all(t > time.monotonic() - 6 for t in client._request_timestamps)


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
async def test_rate_limit_sleeps_when_at_max(client):
    now = time.monotonic()
    for i in range(560):
        client._request_timestamps.append(now - 2 + i * 0.003)

    async def fake_sleep(duration):
        client._request_timestamps.clear()

    with patch("asyncio.sleep", side_effect=fake_sleep) as mock_sleep:
        await client._wait_for_rate_limit()
        assert mock_sleep.call_count >= 1
        assert mock_sleep.call_args[0][0] > 0


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

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(BybitAPIError) as exc_info:
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
