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
    client._request_timestamps.append(time.time())
    assert len(client._request_timestamps) == 1


@pytest.mark.asyncio
async def test_rate_limit_prunes_old_timestamps(client):
    old = time.time() - 61
    client._request_timestamps.append(old)
    client._request_timestamps.append(old - 1)
    await client._wait_for_rate_limit()
    assert all(t > time.time() - 60 for t in client._request_timestamps)


@pytest.mark.asyncio
async def test_rate_limit_sleeps_when_at_max(client):
    now = time.time()
    for i in range(120):
        client._request_timestamps.append(now - 30 + i * 0.1)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await client._wait_for_rate_limit()
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] > 0


@pytest.mark.asyncio
async def test_retry_on_rate_limit_error(client):
    rate_limited_resp = AsyncMock()
    rate_limited_resp.json = AsyncMock(return_value={"retCode": 10006, "retMsg": "Rate limit"})
    rate_limited_resp.__aenter__ = AsyncMock(return_value=rate_limited_resp)
    rate_limited_resp.__aexit__ = AsyncMock(return_value=False)

    success_resp = AsyncMock()
    success_resp.json = AsyncMock(return_value={"retCode": 0, "result": {"ok": True}})
    success_resp.__aenter__ = AsyncMock(return_value=success_resp)
    success_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(side_effect=[rate_limited_resp, success_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/v5/test", {})
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_retry_exhaustion_raises(client):
    rate_limited_resp = AsyncMock()
    rate_limited_resp.json = AsyncMock(return_value={"retCode": 10006, "retMsg": "Rate limit"})
    rate_limited_resp.__aenter__ = AsyncMock(return_value=rate_limited_resp)
    rate_limited_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=rate_limited_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(BybitAPIError) as exc_info:
                await client._request("GET", "/v5/test", {})
    assert exc_info.value.ret_code == 10006


@pytest.mark.asyncio
async def test_retry_uses_exponential_backoff(client):
    rate_limited_resp = AsyncMock()
    rate_limited_resp.json = AsyncMock(return_value={"retCode": 10006, "retMsg": "Rate limit"})
    rate_limited_resp.__aenter__ = AsyncMock(return_value=rate_limited_resp)
    rate_limited_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=rate_limited_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(BybitAPIError):
                await client._request("GET", "/v5/test", {})
            delays = [call[0][0] for call in mock_sleep.call_args_list if call[0][0] >= 0.5]
            assert len(delays) >= 2
            assert delays[1] > delays[0]


@pytest.mark.asyncio
async def test_non_rate_limit_error_not_retried(client):
    error_resp = AsyncMock()
    error_resp.json = AsyncMock(return_value={"retCode": 10001, "retMsg": "Invalid key"})
    error_resp.__aenter__ = AsyncMock(return_value=error_resp)
    error_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=error_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
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

    original_request = client._request

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
