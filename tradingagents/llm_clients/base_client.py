from abc import ABC, abstractmethod
from typing import Any, Optional
import asyncio
import logging
import random
import threading
import time
import warnings

logger = logging.getLogger(__name__)

_llm_semaphore: threading.Semaphore | None = None
_llm_sem_lock = threading.Lock()

_llm_min_spacing_ms: int = 0
_llm_last_request_ts: float = 0
_llm_spacing_lock = threading.Lock()

# --- async mirrors (used only by the async graph path; see allm_rate_limited_invoke) ---
# Kept SEPARATE from the threading primitives above: an asyncio.Semaphore is bound to a
# running loop and must never be acquired from worker threads. The configured LIMIT is the
# same integer as the sync semaphore so provider pressure is identical on either path.
_allm_semaphore: "asyncio.Semaphore | None" = None
_allm_limit: int = 0
_allm_last_request_ts: float = 0.0
_allm_spacing_lock: "asyncio.Lock | None" = None

_LLM_MAX_RETRIES = 5
_LLM_BASE_DELAY = 1.0
_LLM_MAX_DELAY = 30.0

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS_CODES:
        return True
    msg = str(exc).lower()
    for hint in ("rate limit", "timeout", "timed out", "connection", "server error",
                 "bad gateway", "service unavailable", "overloaded",
                 "invalid_request_body", "failed to read request body"):
        if hint in msg:
            return True
    if status == 400:
        for hint_400 in ("invalid_request_body", "failed to read request body",
                         "request body", "could not read"):
            if hint_400 in msg:
                return True
    return False


def configure_llm_min_spacing(ms: int) -> None:
    global _llm_min_spacing_ms
    _llm_min_spacing_ms = max(0, ms)
    logger.info("LLM min spacing set to %dms", _llm_min_spacing_ms)


def configure_llm_concurrency(max_concurrent: int) -> None:
    global _llm_semaphore
    with _llm_sem_lock:
        if max_concurrent <= 0:
            _llm_semaphore = None
            logger.info("LLM concurrency: unlimited")
        else:
            _llm_semaphore = threading.Semaphore(max_concurrent)
            logger.info("LLM concurrency limit set to %d", max_concurrent)


def llm_rate_limited_invoke(super_invoke, input, config=None, **kwargs):
    global _llm_last_request_ts
    sem = _llm_semaphore
    last_exc: Exception | None = None
    for attempt in range(_LLM_MAX_RETRIES):
        if _llm_min_spacing_ms > 0:
            gap = 0.0
            with _llm_spacing_lock:
                now = time.monotonic()
                elapsed_ms = (now - _llm_last_request_ts) * 1000
                if _llm_last_request_ts > 0 and elapsed_ms < _llm_min_spacing_ms:
                    gap = (_llm_min_spacing_ms - elapsed_ms) / 1000
                _llm_last_request_ts = time.monotonic() + gap
            if gap > 0:
                logger.debug("Spacing LLM call: waiting %.1fms", gap * 1000)
                time.sleep(gap)
        if sem is not None:
            sem.acquire()
        try:
            return super_invoke(input, config, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == _LLM_MAX_RETRIES - 1:
                raise
            delay = min(_LLM_BASE_DELAY * (2 ** attempt), _LLM_MAX_DELAY)
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, _LLM_MAX_RETRIES, delay, exc,
            )
        finally:
            if sem is not None:
                sem.release()
        time.sleep(delay)
    raise last_exc  # unreachable but keeps type checkers happy


def configure_llm_concurrency_async(max_concurrent: int) -> None:
    """Async mirror of configure_llm_concurrency. Sets the LIMIT only; the actual
    asyncio.Semaphore is created lazily on the running loop in allm_rate_limited_invoke
    (a semaphore can't be safely created before the loop exists / across loops).

    Only resets the live semaphore when the limit actually CHANGES — a no-op reconfigure
    (e.g. the same value re-applied) must not drop a semaphore that in-flight calls hold,
    which would transiently over-admit (old permits + a fresh full quota) during a scan."""
    global _allm_limit, _allm_semaphore
    new_limit = max(0, max_concurrent)
    if new_limit == _allm_limit and _allm_semaphore is not None:
        return  # unchanged — keep the live semaphore, no over-admission window
    _allm_limit = new_limit
    _allm_semaphore = None  # force lazy re-create against the active loop with the new limit
    if _allm_limit <= 0:
        logger.info("LLM concurrency (async): unlimited")
    else:
        logger.info("LLM concurrency (async) limit set to %d", _allm_limit)


def _get_async_sem() -> "asyncio.Semaphore | None":
    """Lazily bind the async semaphore to the current running loop."""
    global _allm_semaphore
    if _allm_limit <= 0:
        return None
    if _allm_semaphore is None:
        _allm_semaphore = asyncio.Semaphore(_allm_limit)
    return _allm_semaphore


async def allm_rate_limited_invoke(super_ainvoke, input, config=None, **kwargs):
    """Async mirror of llm_rate_limited_invoke. IDENTICAL retry/backoff/spacing/concurrency
    semantics — only awaited (asyncio.sleep / asyncio.Semaphore) instead of blocking, so it
    never stalls the event loop. Reuses _is_retryable verbatim so retry decisions match the
    sync path exactly."""
    global _allm_last_request_ts, _allm_spacing_lock
    last_exc: Exception | None = None
    for attempt in range(_LLM_MAX_RETRIES):
        if _llm_min_spacing_ms > 0:
            if _allm_spacing_lock is None:
                _allm_spacing_lock = asyncio.Lock()
            gap = 0.0
            async with _allm_spacing_lock:
                now = time.monotonic()
                elapsed_ms = (now - _allm_last_request_ts) * 1000
                if _allm_last_request_ts > 0 and elapsed_ms < _llm_min_spacing_ms:
                    gap = (_llm_min_spacing_ms - elapsed_ms) / 1000
                _allm_last_request_ts = time.monotonic() + gap
            if gap > 0:
                logger.debug("Spacing LLM call (async): waiting %.1fms", gap * 1000)
                await asyncio.sleep(gap)
        sem = _get_async_sem()
        if sem is not None:
            await sem.acquire()
        try:
            return await super_ainvoke(input, config, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == _LLM_MAX_RETRIES - 1:
                raise
            # FULL JITTER backoff (async only): under high async concurrency many coroutines
            # can 429 simultaneously; a deterministic delay would wake them all at once
            # (thundering herd) and re-storm the provider. Randomising the wait in
            # [0, capped_backoff] de-synchronises retries. The sync path keeps its
            # deterministic delay (it is thread-throttled, so no herd) to stay byte-identical.
            delay = random.uniform(0.0, min(_LLM_BASE_DELAY * (2 ** attempt), _LLM_MAX_DELAY))
            logger.warning(
                "LLM call failed (async, attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, _LLM_MAX_RETRIES, delay, exc,
            )
        finally:
            if sem is not None:
                sem.release()
        await asyncio.sleep(delay)
    raise last_exc  # unreachable but keeps type checkers happy


def normalize_content(response):
    """Normalize LLM response content to a plain string.

    Multiple providers (OpenAI Responses API, Google Gemini 3) return content
    as a list of typed blocks, e.g. [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}].
    Downstream agents expect response.content to be a string. This extracts
    and joins the text blocks, discarding reasoning/metadata blocks.
    """
    content = response.content
    if isinstance(content, list):
        texts = [
            item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
            else item if isinstance(item, str) else ""
            for item in content
        ]
        response.content = "\n".join(t for t in texts if t)
    return response


def extract_cache_metrics(response) -> dict:
    """Pull normalized cache token counts from a langchain response.

    langchain maps Anthropic / OpenAI-Responses / Gemini all to
    usage_metadata['input_token_details']['cache_read' | 'cache_creation'].
    Returns None for a field the provider did not report (distinct from 0).
    Gemini caveat: cache_read may be unpopulated even when caching fired
    (known langchain_google_genai issue) — treat Gemini cache_read==0/None
    as inconclusive, not proof of no caching.
    """
    um = getattr(response, "usage_metadata", None) or {}
    details = um.get("input_token_details") or {}
    return {
        "input_tokens": um.get("input_tokens"),
        "cache_read": details.get("cache_read"),
        "cache_creation": details.get("cache_creation"),
    }


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        """Return the provider name used in warning messages."""
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """Warn when the model is outside the known list for the provider."""
        if self.validate_model():
            return
        if getattr(self, "_warned_unknown_model", False):
            return
        self._warned_unknown_model = True

        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        """Return the configured LLM instance."""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """Validate that the model is supported by this client."""
        pass
