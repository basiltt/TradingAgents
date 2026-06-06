"""Unified LLM client using LiteLLM for multi-provider support.

LiteLLM routes to 100+ providers via a single interface. This module wraps
it in a LangChain-compatible chat model with rate limiting and content
normalization matching the existing BaseLLMClient contract.
"""

import logging
import os
import threading
from typing import Any, Optional

import httpx
from langchain_community.chat_models import ChatLiteLLM

from .base_client import BaseLLMClient, normalize_content, llm_rate_limited_invoke
from .model_families import OPUS_ADAPTIVE_SUBSTRINGS

logger = logging.getLogger(__name__)

# Suppress litellm's verbose debug logging unless explicitly enabled
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)

# Enable litellm's automatic parameter dropping for unsupported params
# (e.g. temperature for reasoning models that reject it)
try:
    import litellm as _litellm
    _litellm.drop_params = True
    # Suppress noisy warnings about unused providers (e.g. bedrock/botocore)
    _litellm.suppress_debug_info = True
except ImportError:
    pass

# Silence the specific botocore/bedrock warning since we don't use AWS
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)

_serialize_lock = threading.Lock()

# LiteLLM provider prefixes for model routing.
# When the model string doesn't already contain a provider prefix,
# we prepend one so litellm knows where to route.
_PROVIDER_PREFIX_MAP = {
    "openai": "",  # no prefix needed, litellm defaults to openai
    "anthropic": "anthropic/",
    "google": "gemini/",
    "azure": "azure/",
    "deepseek": "deepseek/",
    "xai": "xai/",
    "ollama": "openai/",  # ollama uses OpenAI-compatible endpoint
    "openrouter": "openrouter/",
    "nvidia": "nvidia_nim/",
    "qwen": "openai/",  # qwen uses openai-compatible endpoint
    "glm": "openai/",  # glm uses openai-compatible endpoint
}

# Provider-specific base URLs (used when no custom base_url is provided)
_PROVIDER_BASE_URLS = {
    "xai": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "glm": "https://api.z.ai/api/paas/v4/",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

# Provider-specific API key environment variable names
_PROVIDER_API_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "azure": "AZURE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class NormalizedChatLiteLLM(ChatLiteLLM):
    """ChatLiteLLM with normalized content output and rate limiting.

    Also fixes api_key propagation: langchain's ChatLiteLLM sets api_key as
    a litellm module global but does NOT pass it to litellm.completion().
    We override _client_params to include it explicitly.
    """

    @property
    def _client_params(self) -> dict:
        params = super()._client_params
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def invoke(self, input, config=None, **kwargs):
        if getattr(self, "_cache_enabled", False) and str(self.model).startswith("anthropic/"):
            input = self._inject_cache_control(input)
        return normalize_content(llm_rate_limited_invoke(super().invoke, input, config, **kwargs))

    def _inject_cache_control(self, input):
        """Rewrite the first system message to a cache_control block (Anthropic only).
        Handles ChatPromptValue / list[BaseMessage] / list[dict]. Other shapes pass
        through unchanged (no-op)."""
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        if hasattr(input, "to_messages"):
            return apply_cache_control_to_messages(input.to_messages())
        if isinstance(input, list):
            return apply_cache_control_to_messages(input)
        return input

    def __iter__(self):
        with _serialize_lock:
            yield from list(super().__iter__())


class LiteLLMClient(BaseLLMClient):
    """Unified client that routes to any provider via LiteLLM.

    Supports:
    - All major providers (OpenAI, Anthropic, Google, Azure, DeepSeek, xAI, etc.)
    - Custom base_url / proxy URL override
    - Auto model routing via litellm's prefix system
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def _get_litellm_model_name(self) -> str:
        """Build the litellm model string with provider prefix."""
        prefix = _PROVIDER_PREFIX_MAP.get(self.provider, "openai/")

        # If model already has a provider prefix (contains /), use as-is
        if "/" in self.model:
            return self.model

        return f"{prefix}{self.model}"

    def get_llm(self) -> Any:
        """Return configured ChatLiteLLM instance."""
        self.warn_if_unknown_model()

        model_name = self._get_litellm_model_name()
        llm_kwargs: dict[str, Any] = {"model": model_name}

        # Base URL: explicit > provider default > litellm's built-in
        base_url = self.base_url or _PROVIDER_BASE_URLS.get(self.provider)
        if base_url:
            llm_kwargs["api_base"] = base_url

        # Azure-specific: litellm reads AZURE_API_BASE and AZURE_API_VERSION
        # from env, but we also support explicit base_url override and the
        # legacy AZURE_OPENAI_ENDPOINT env var.
        if self.provider == "azure" and "api_base" not in llm_kwargs:
            azure_endpoint = os.environ.get("AZURE_API_BASE") or os.environ.get("AZURE_OPENAI_ENDPOINT")
            if azure_endpoint:
                llm_kwargs["api_base"] = azure_endpoint

        # API key resolution
        api_key = self.kwargs.get("api_key")
        if not api_key:
            env_var = _PROVIDER_API_KEY_ENVS.get(self.provider)
            if env_var:
                api_key = os.environ.get(env_var)
            # Azure fallback: also check AZURE_OPENAI_API_KEY
            if not api_key and self.provider == "azure":
                api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        if api_key:
            llm_kwargs["api_key"] = api_key
        elif self.base_url:
            # Custom proxy URL without explicit key — use dummy
            llm_kwargs["api_key"] = "dummy"
        elif self.provider == "ollama":
            # Ollama doesn't require auth but OpenAI-compatible mode needs a value
            llm_kwargs["api_key"] = "ollama"

        # Forward supported kwargs
        for key in ("temperature", "max_tokens", "timeout", "max_retries",
                    "top_p", "n", "stop", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Provider-specific model kwargs passed through to litellm
        model_kwargs = {}
        if self.kwargs.get("reasoning_effort"):
            # OpenAI reasoning models (o-series, GPT-5)
            model_kwargs["reasoning_effort"] = self.kwargs["reasoning_effort"]
        if self.kwargs.get("effort"):
            # Anthropic thinking. Current Opus (4.7/4.8) removed budget_tokens and
            # require adaptive thinking; the legacy enabled+budget_tokens shape 400s.
            # Use adaptive for those models; keep the legacy budget shape for older
            # Anthropic models that still accept it.
            model_l = self.model.lower()
            if any(s in model_l for s in OPUS_ADAPTIVE_SUBSTRINGS):
                model_kwargs["thinking"] = {"type": "adaptive"}
            else:
                budget = {"high": 32000, "medium": 16000, "low": 4000}.get(
                    self.kwargs["effort"], 16000
                )
                model_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if self.kwargs.get("thinking_level"):
            # Google Gemini thinking level — passed as extra kwarg.
            # Litellm may pass this through; for full fidelity use legacy client.
            model_kwargs["thinking_level"] = self.kwargs["thinking_level"]
        if model_kwargs:
            llm_kwargs["model_kwargs"] = model_kwargs

        instance = NormalizedChatLiteLLM(**llm_kwargs)
        instance._cache_enabled = bool(self.kwargs.get("prompt_cache_enabled", False))
        return instance

    def validate_model(self) -> bool:
        """LiteLLM supports any model string — validation is permissive."""
        return True


def fetch_models_from_endpoint(
    base_url: str,
    api_key: Optional[str] = None,
    timeout: float = 10.0,
) -> list[dict[str, str]]:
    """Fetch available models from an OpenAI-compatible /v1/models endpoint.

    Returns a list of dicts with 'id' and optionally 'name' keys.
    """

    url = base_url.rstrip("/")
    if not url.endswith("/v1/models"):
        url = f"{url}/v1/models"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code not in (200, 201):
            logger.warning("Failed to fetch models from %s: HTTP %d", url, resp.status_code)
            return []
        data = resp.json()
        if not isinstance(data, dict):
            return []
        return [
            {"id": m.get("id", ""), "name": m.get("name", m.get("id", ""))}
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]
    except Exception as e:
        logger.warning("Failed to fetch models from %s: %s", url, e)
        return []


def get_litellm_supported_providers() -> list[str]:
    """Return list of providers supported by litellm."""
    return sorted(_PROVIDER_PREFIX_MAP.keys())
