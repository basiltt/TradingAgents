"""AI Manager LLM Provider — creates the async callable for LLM decisions.

Reads provider config from environment variables (same pattern as analysis_service):
  - TRADINGAGENTS_LLM_PROVIDER: "openai", "anthropic", or "azure"
  - OPENAI_API_KEY / ANTHROPIC_API_KEY / AZURE_OPENAI_API_KEY
  - TRADINGAGENTS_QUICK_THINK_LLM: model name for fast decisions (default: gpt-4o-mini)
  - TRADINGAGENTS_BACKEND_URL: optional proxy/backend URL

Returns an async callable with signature: async (system_prompt: str, context_prompt: str) -> str
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

LLMCallable = Callable[[str, str], Coroutine[None, None, str]]

_active_clients: list = []

_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}


def create_llm_callable() -> Optional[LLMCallable]:
    """Create an LLM callable based on environment configuration. Returns None if not configured."""
    provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER", "").lower()
    if not provider:
        logger.warning("AI Manager: No LLM provider configured (set TRADINGAGENTS_LLM_PROVIDER)")
        return None

    env_key = _PROVIDER_KEY_MAP.get(provider)
    if not env_key:
        logger.warning("AI Manager: Unsupported LLM provider '%s'", provider)
        return None

    api_key = os.getenv(env_key)
    if not api_key:
        logger.warning("AI Manager: %s not set — LLM disabled", env_key)
        return None

    model = os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-4o-mini")
    backend_url = os.getenv("TRADINGAGENTS_BACKEND_URL")

    if provider == "openai" or provider == "azure":
        return _create_openai_callable(api_key, model, backend_url, provider)
    elif provider == "anthropic":
        return _create_anthropic_callable(api_key, model)

    return None


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


def _create_anthropic_callable(api_key: str, model: str) -> LLMCallable:
    import httpx

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    client = httpx.AsyncClient(timeout=35.0)
    _active_clients.append(client)

    async def call_anthropic(system_prompt: str, context_prompt: str) -> str:
        payload = {
            "model": model if "claude" in model.lower() else "claude-sonnet-4-20250514",
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
    for client in _active_clients:
        await client.aclose()
    _active_clients.clear()
