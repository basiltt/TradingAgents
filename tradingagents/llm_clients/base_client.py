from abc import ABC, abstractmethod
from typing import Any, Optional
import logging
import threading
import warnings

logger = logging.getLogger(__name__)

_llm_semaphore: threading.Semaphore | None = None
_llm_sem_lock = threading.Lock()


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
    sem = _llm_semaphore
    if sem is None:
        return super_invoke(input, config, **kwargs)
    sem.acquire()
    try:
        return super_invoke(input, config, **kwargs)
    finally:
        sem.release()


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
