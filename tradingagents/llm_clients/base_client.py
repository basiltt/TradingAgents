from abc import ABC, abstractmethod
from typing import Any, Optional
import logging
import threading
import time
import warnings

logger = logging.getLogger(__name__)

_llm_semaphore: threading.Semaphore | None = None
_llm_sem_lock = threading.Lock()

_llm_min_spacing_ms: int = 0
_llm_last_request_ts: float = 0
_llm_spacing_lock = threading.Lock()

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
