"""AI Manager LLM Provider — creates the async callable for LLM decisions.

Supports explicit parameters (from scan_config) with fallback to environment
variables, matching the same resolution pattern as analysis_service:
  - provider: "openai", "anthropic", or "azure"
  - api_key: the provider's API key
  - model: model name for decisions
  - backend_url: optional proxy/backend URL (e.g. Minimax endpoint)

Returns an async callable with signature: async (system_prompt: str, context_prompt: str) -> str
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable, Coroutine, Optional

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

LLMCallable = Callable[[str, str], Coroutine[None, None, str]]

_active_clients: list["httpx.AsyncClient"] = []

_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}


async def _close_stale_clients() -> None:
    """Close and discard all previously created clients before creating new ones."""
    for client in _active_clients:
        try:
            await client.aclose()
        except Exception:
            pass
    _active_clients.clear()


def create_llm_callable(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    backend_url: Optional[str] = None,
) -> tuple[Optional[LLMCallable], str]:
    """Create an LLM callable. Explicit params take priority over env vars.

    Returns (callable_or_None, resolved_model_name).
    """
    provider = (provider or os.getenv("TRADINGAGENTS_LLM_PROVIDER", "")).lower()
    if not provider:
        logger.warning("AI Manager: No LLM provider configured (set TRADINGAGENTS_LLM_PROVIDER)")
        return None, "unknown"

    if not api_key:
        env_key = _PROVIDER_KEY_MAP.get(provider)
        if not env_key:
            logger.warning("AI Manager: Unsupported LLM provider '%s'", provider)
            return None, "unknown"
        api_key = os.getenv(env_key)
        if not api_key:
            logger.warning("AI Manager: %s not set — LLM disabled", env_key)
            return None, "unknown"

    model = model or os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-4o-mini")
    backend_url = backend_url or os.getenv("TRADINGAGENTS_BACKEND_URL")

    if provider == "openai" or provider == "azure":
        return _create_openai_callable(api_key, model, backend_url, provider), model
    elif provider == "anthropic":
        return _create_anthropic_callable(api_key, model, backend_url), model

    return None, "unknown"


def _create_openai_callable(
    api_key: str, model: str, backend_url: Optional[str], provider: str
) -> LLMCallable:
    import httpx

    url = backend_url or "https://api.openai.com"
    url = url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = httpx.AsyncClient(timeout=35.0)
    _active_clients.append(client)

    async def call_openai(system_prompt: str, context_prompt: str) -> str:
        """Invoke OpenAI chat completion and return the response text."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    return call_openai


def _create_anthropic_callable(api_key: str, model: str, backend_url: Optional[str] = None) -> LLMCallable:
    import httpx

    base = backend_url or "https://api.anthropic.com"
    url = base.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    client = httpx.AsyncClient(timeout=35.0)
    _active_clients.append(client)

    async def call_anthropic(system_prompt: str, context_prompt: str) -> str:
        """Invoke Anthropic messages API and return the response text."""
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": context_prompt}],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

    return call_anthropic


async def close_llm_clients() -> None:
    """Close all httpx clients created by create_llm_callable."""
    await _close_stale_clients()
