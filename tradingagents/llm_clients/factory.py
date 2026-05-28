from typing import Optional

from .base_client import BaseLLMClient

# Providers that use the OpenAI-compatible chat completions API (legacy path)
_OPENAI_COMPATIBLE = (
    "openai", "xai", "deepseek", "qwen", "glm", "ollama", "openrouter", "nvidia",
)


def create_llm_client(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    use_litellm: bool = True,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    By default, routes through the unified LiteLLM client which supports
    100+ providers with a single interface. Set use_litellm=False to use
    the legacy provider-specific clients.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint (proxy/custom URL)
        use_litellm: Use the unified LiteLLM client (default True)
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()
    model_lower = model.lower()

    # Any model whose name contains "gpt" is treated as an OpenAI model
    # regardless of the declared provider.
    if "gpt" in model_lower and provider_lower not in _OPENAI_COMPATIBLE:
        provider_lower = "openai"

    # LiteLLM unified path (default)
    if use_litellm:
        from .litellm_client import LiteLLMClient, _PROVIDER_PREFIX_MAP
        if provider_lower not in _PROVIDER_PREFIX_MAP:
            raise ValueError(
                f"Unsupported LLM provider: {provider}. "
                f"Supported: {', '.join(sorted(_PROVIDER_PREFIX_MAP.keys()))}"
            )
        return LiteLLMClient(model, base_url, provider=provider_lower, **kwargs)

    # Legacy provider-specific clients (fallback)
    if provider_lower in _OPENAI_COMPATIBLE:
        from .openai_client import OpenAIClient
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        return AzureOpenAIClient(model, base_url, **kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
