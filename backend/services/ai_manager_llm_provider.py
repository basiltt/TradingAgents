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

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Callable, Coroutine, Optional

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

LLMCallable = Callable[[str, str], Coroutine[None, None, str]]

_active_clients: list["httpx.AsyncClient"] = []


def _sampling_params(model: str) -> dict:
    """Return the sampling/token params to merge into a payload for this model.

    Always includes max_tokens. Omits temperature (and other sampling params)
    for models that 400 on them (current Opus). Conservative default: include
    temperature unless the model is known to reject it. The Opus list lives in
    tradingagents.llm_clients.model_families so the engine and API agree.
    """
    from tradingagents.llm_clients.model_families import OPUS_ADAPTIVE_SUBSTRINGS

    params: dict = {"max_tokens": 1024}
    model_l = (model or "").lower()
    if not any(s in model_l for s in OPUS_ADAPTIVE_SUBSTRINGS):
        params["temperature"] = 0.2
    return params


async def _acquire_global_rate_limit() -> bool:
    """Respect the global LLM concurrency semaphore and minimum spacing.

    These are the same globals configured by configure_llm_concurrency / configure_llm_min_spacing
    in tradingagents.llm_clients.base_client, ensuring the AI Manager's direct httpx calls
    don't bypass the central rate limiter.

    Returns True if the semaphore was acquired (and must be released), False otherwise.
    """
    import tradingagents.llm_clients.base_client as _base

    # Enforce minimum spacing
    if _base._llm_min_spacing_ms > 0:
        gap = 0.0
        with _base._llm_spacing_lock:
            now = time.monotonic()
            elapsed_ms = (now - _base._llm_last_request_ts) * 1000
            if _base._llm_last_request_ts > 0 and elapsed_ms < _base._llm_min_spacing_ms:
                gap = (_base._llm_min_spacing_ms - elapsed_ms) / 1000
            _base._llm_last_request_ts = time.monotonic() + gap
        if gap > 0:
            await asyncio.sleep(gap)

    # Acquire concurrency semaphore using non-blocking poll to stay cancellation-safe.
    # Capture reference once so acquire/release target the same object.
    # Timeout after 25s to avoid holding upstream PriorityLLMScheduler slots indefinitely.
    sem = _base._llm_semaphore
    if sem is not None:
        deadline = time.monotonic() + 25.0
        while not sem.acquire(blocking=False):
            if time.monotonic() >= deadline:
                raise TimeoutError("Global LLM semaphore not available within 25s")
            await asyncio.sleep(0.05)
        return True
    return False


def _release_global_rate_limit(acquired: bool) -> None:
    """Release the global LLM concurrency semaphore if it was acquired."""
    if not acquired:
        return
    import tradingagents.llm_clients.base_client as _base
    if _base._llm_semaphore is not None:
        _base._llm_semaphore.release()

_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
}

_OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "xai": "https://api.x.ai",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode",
    "glm": "https://open.bigmodel.cn/api/paas",
}


async def _close_stale_clients() -> None:
    """Close and discard all previously created clients before creating new ones."""
    for client in _active_clients:
        try:
            await client.aclose()
        except Exception:
            pass
    _active_clients.clear()


def _extract_openai_text(data: dict, model: str) -> str:
    """Extract assistant text from an OpenAI-compatible chat response.

    Degrades gracefully to "" when the response is degenerate (no choices, or
    null content). The decision graph parses "" as no-decision → HOLD, so the
    AI Manager stays safe instead of raising on a malformed/empty response.
    """
    choices = data.get("choices") or []
    if not choices:
        logger.warning(
            "OpenAI-compatible empty response — no choices, model=%s; treating as HOLD",
            model,
        )
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if not content:
        logger.warning(
            "OpenAI-compatible empty response — null/empty content, model=%s; treating as HOLD",
            model,
        )
        return ""
    return content


def _extract_anthropic_text(data: dict, model: str) -> str:
    """Extract assistant text from an Anthropic /v1/messages response.

    Degrades gracefully to "" when the response has an empty content array
    (e.g. a proxy/model returned a degenerate response such as stop_reason=None).
    The decision graph parses "" as no-decision → HOLD, so the AI Manager stays
    safe instead of raising a noisy ERROR-level traceback for what is a
    recoverable, expected upstream condition.

    `model` is the request model (not data.get("model"), which a degenerate
    proxy response may omit) so the warning log identifies the call reliably.
    """
    content = data.get("content") or []
    if not content:
        logger.warning(
            "Anthropic empty response — stop_reason=%s, model=%s; treating as HOLD",
            data.get("stop_reason"),
            model,
        )
        return ""
    # Prefer the first text block (skip thinking/tool_use blocks).
    for block in content:
        if block.get("type") == "text":
            return block["text"]
    # Fallback: return first block's text-like field.
    return content[0].get("text") or content[0].get("thinking") or str(content[0])


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

    if provider in ("openai", "azure", "deepseek", "xai", "google", "openrouter", "qwen", "glm"):
        if not backend_url and provider in _OPENAI_COMPATIBLE_BASE_URLS:
            backend_url = _OPENAI_COMPATIBLE_BASE_URLS[provider]
        return _create_openai_callable(api_key, model, backend_url, provider), model
    elif provider == "anthropic":
        return _create_anthropic_callable(api_key, model, backend_url), model

    return None, "unknown"


def create_llm_callable_with_cleanup(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    backend_url: Optional[str] = None,
) -> tuple[Optional[LLMCallable], str, Optional[Callable]]:
    """Like create_llm_callable but returns (callable, model, async_close_fn).

    The async_close_fn closes the httpx client when the per-account task is torn down.
    This avoids leaking clients into the module-level _active_clients list.
    """
    import httpx

    provider = (provider or os.getenv("TRADINGAGENTS_LLM_PROVIDER", "")).lower()
    if not provider:
        return None, "unknown", None

    if not api_key:
        env_key = _PROVIDER_KEY_MAP.get(provider)
        if not env_key:
            return None, "unknown", None
        api_key = os.getenv(env_key)
        if not api_key:
            return None, "unknown", None

    model = model or os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-4o-mini")
    backend_url = backend_url or os.getenv("TRADINGAGENTS_BACKEND_URL")

    if provider in ("openai", "azure", "deepseek", "xai", "google", "openrouter", "qwen", "glm"):
        if not backend_url and provider in _OPENAI_COMPATIBLE_BASE_URLS:
            backend_url = _OPENAI_COMPATIBLE_BASE_URLS[provider]
        url = backend_url or "https://api.openai.com"
        url = url.rstrip("/") + "/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        client = httpx.AsyncClient(timeout=60.0)

        async def _close():
            try:
                await client.aclose()
            except Exception:
                pass

        async def call_openai(system_prompt: str, context_prompt: str) -> str:
            acquired = await _acquire_global_rate_limit()
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": context_prompt},
                    ],
                    **_sampling_params(model),
                }
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return _extract_openai_text(data, model)
            finally:
                _release_global_rate_limit(acquired)

        return call_openai, model, _close

    elif provider == "anthropic":
        base = backend_url or "https://api.anthropic.com"
        url = base.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        client = httpx.AsyncClient(timeout=60.0)

        async def _close():
            try:
                await client.aclose()
            except Exception:
                pass

        async def call_anthropic(system_prompt: str, context_prompt: str) -> str:
            acquired = await _acquire_global_rate_limit()
            try:
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": context_prompt}],
                    **_sampling_params(model),
                }
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return _extract_anthropic_text(data, model)
            finally:
                _release_global_rate_limit(acquired)

        return call_anthropic, model, _close

    return None, "unknown", None


def _create_openai_callable(
    api_key: str, model: str, backend_url: Optional[str], provider: str
) -> LLMCallable:
    import httpx

    url = backend_url or "https://api.openai.com"
    url = url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = httpx.AsyncClient(timeout=60.0)
    _active_clients.append(client)

    async def call_openai(system_prompt: str, context_prompt: str) -> str:
        """Invoke OpenAI chat completion and return the response text."""
        acquired = await _acquire_global_rate_limit()
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context_prompt},
                ],
                **_sampling_params(model),
            }
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return _extract_openai_text(data, model)
        finally:
            _release_global_rate_limit(acquired)

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
    client = httpx.AsyncClient(timeout=60.0)
    _active_clients.append(client)

    async def call_anthropic(system_prompt: str, context_prompt: str) -> str:
        """Invoke Anthropic messages API and return the response text."""
        acquired = await _acquire_global_rate_limit()
        try:
            payload = {
                "model": model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": context_prompt}],
                **_sampling_params(model),
            }
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return _extract_anthropic_text(data, model)
        finally:
            _release_global_rate_limit(acquired)

    return call_anthropic


async def close_llm_clients() -> None:
    """Close all httpx clients created by create_llm_callable."""
    await _close_stale_clients()
