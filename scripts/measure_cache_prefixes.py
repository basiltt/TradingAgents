"""Estimate token counts for each Pattern A/B stable system prefix (P1 recon).

Decides which agent call sites are worth wiring `cache_control` into during P4.
Anthropic's minimum cacheable prefix is model-dependent:
  - Sonnet 4.x = 1024 tokens
  - Opus 4.x   = 4096 tokens
A prefix below the threshold silently will NOT cache, so measuring the *stable*
portion of each system prompt is the gate for the whole feature.

Method (rigorous — avoids hand-transcription error):
  - Pattern A (analysts): a capture LLM intercepts the fully-formatted system
    message that LangChain builds, then we strip the volatile tail
    (date / instrument / live-price). What remains is the cacheable prefix:
    boilerplate + tool_names + the static system_message catalog.
  - Pattern B (trader x2, risk_manager, compliance_officer): import the real
    system constants directly — they are already pure-static strings.

Uses litellm.token_counter (already a dependency) so no extra install.
The Anthropic tokenizer is shared across Sonnet/Opus 4.x, so claude-sonnet-4-6
is a valid proxy for both thresholds.

Run: python scripts/measure_cache_prefixes.py
"""

from __future__ import annotations

import litellm

MODEL = "claude-sonnet-4-6"  # Anthropic tokenizer proxy for Sonnet & Opus 4.x
SONNET_MIN = 1024
OPUS_MIN = 4096

# Marker where the volatile tail begins in every analyst system message.
_VOLATILE_MARKER = "For your reference, the current date is"


class _CaptureError(Exception):
    """Carries the fully-formatted prompt out of a chain.invoke()."""

    def __init__(self, prompt_value):
        self.prompt_value = prompt_value


class _CaptureLLM:
    """Stands in for the real chat model; grabs the formatted prompt and bails.

    `prompt | llm.bind_tools(tools)` builds a RunnableSequence; when invoked it
    formats the ChatPromptTemplate and passes the PromptValue to our captor.
    `bind_tools` must return a real Runnable for the `|` pipe to typecheck, so
    we hand back a RunnableLambda that raises the captured prompt out. We also
    stash the tools so we can size the tool-schema portion of the cached prefix
    (Anthropic caches tools + system together when the breakpoint is on system).
    """

    def __init__(self):
        self.captured_tools = None

    def bind_tools(self, tools):
        from langchain_core.runnables import RunnableLambda

        self.captured_tools = tools

        def _capture(prompt_value):
            raise _CaptureError(prompt_value)

        return RunnableLambda(_capture)

    def invoke(self, prompt_value, *args, **kwargs):
        # Pattern A always routes through bind_tools(); this is a safety net.
        raise _CaptureError(prompt_value)


def _tool_schema_tokens(tools) -> int:
    """Approximate the token cost of the tool JSON schemas sent to the API.

    Anthropic places tool definitions before the system prompt; a cache
    breakpoint on the system block therefore caches the tools too. We convert
    each LangChain tool to its OpenAI/JSON-schema form and token-count the JSON.
    """
    if not tools:
        return 0
    try:
        import json

        from langchain_core.utils.function_calling import convert_to_openai_tool

        blob = json.dumps([convert_to_openai_tool(t) for t in tools])
        return litellm.token_counter(model=MODEL, text=blob)
    except Exception:
        return 0


def _capture_system_text(factory, state, *factory_args):
    """Run an analyst node far enough to capture its formatted system message.

    Returns (system_text, tool_schema_tokens).
    """
    llm = _CaptureLLM()
    node = factory(llm, *factory_args)
    captured = None
    try:
        node(state)
    except _CaptureError as exc:
        captured = exc.prompt_value.to_messages()[0].content
    except Exception as exc:
        # LangChain may wrap the captor's exception; dig the original out.
        cause = exc
        while cause is not None:
            if isinstance(cause, _CaptureError):
                captured = cause.prompt_value.to_messages()[0].content
                break
            cause = cause.__cause__ or cause.__context__
        if captured is None:
            raise
    if captured is None:
        raise RuntimeError(f"factory {factory.__name__} did not invoke the LLM")
    return captured, _tool_schema_tokens(llm.captured_tools)


def _stable_prefix(system_text: str) -> str:
    """Drop the volatile tail (date / instrument / live price) from a system msg."""
    idx = system_text.find(_VOLATILE_MARKER)
    return system_text[:idx] if idx != -1 else system_text


def _row(name: str, text: str, extra_tokens: int = 0) -> tuple[str, int]:
    """Token-count `text`, add any tool-schema tokens, and print a verdict row.

    `extra_tokens` is the tool-schema contribution for Pattern A (0 for B).
    The combined figure is what actually sits in the cached prefix.
    """
    sys_tok = litellm.token_counter(model=MODEL, text=text)
    n = sys_tok + extra_tokens
    tail = f" (sys {sys_tok} + tools {extra_tokens})" if extra_tokens else ""
    print(
        f"{name:34s} {n:6d} tok  "
        f"Sonnet(1024): {'YES' if n >= SONNET_MIN else 'no ':3s}  "
        f"Opus(4096): {'YES' if n >= OPUS_MIN else 'no'}{tail}"
    )
    return name, n


def measure_pattern_a() -> list[tuple[str, int]]:
    """Stock + crypto analysts. Capture the real formatted system prompt."""
    from tradingagents.agents.analysts.market_analyst import create_market_analyst
    from tradingagents.agents.analysts.news_analyst import create_news_analyst
    from tradingagents.agents.analysts.social_media_analyst import (
        create_social_media_analyst,
    )
    from tradingagents.agents.analysts.fundamentals_analyst import (
        create_fundamentals_analyst,
    )
    from tradingagents.agents import crypto_analysts as ca

    rows: list[tuple[str, int]] = []

    # ---- Stock analysts: state used directly, no filter, no extra tools ----
    stock_state = {
        "trade_date": "2026-06-06",
        "company_of_interest": "AAPL",
        "messages": [],
    }
    stock_sites = {
        "stock/market_analyst (A)": create_market_analyst,
        "stock/news_analyst (A)": create_news_analyst,
        "stock/social_media_analyst (A)": create_social_media_analyst,
        "stock/fundamentals_analyst (A)": create_fundamentals_analyst,
    }
    for name, factory in stock_sites.items():
        text, tool_tok = _capture_system_text(factory, stock_state)
        rows.append(_row(name, _stable_prefix(text), tool_tok))

    # ---- Crypto analysts: build the REAL tools so schema tokens are accurate ----
    # crypto_interval=None and regime_context="" => no HTF / no regime section,
    # i.e. exactly the always-present static base of the system message.
    from tradingagents.agents.utils.crypto_agent_utils import make_crypto_tools
    from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools

    crypto_tools = make_crypto_tools()
    coingecko_tools = make_coingecko_tools()
    crypto_state = {
        "trade_date": "2026-06-06",
        "company_of_interest": "BTCUSDT",
        "crypto_interval": None,
        "current_price_context": "",
        "regime_context": "",
        "messages": [],
    }
    crypto_sites = [
        ("crypto/technical_analyst (A)", ca.create_crypto_technical_analyst, (crypto_tools,)),
        ("crypto/derivatives_analyst (A)", ca.create_crypto_derivatives_analyst, (crypto_tools,)),
        ("crypto/news_analyst (A)", ca.create_crypto_news_analyst, ()),
        ("crypto/fundamentals_analyst (A)", ca.create_crypto_fundamentals_analyst, (coingecko_tools,)),
        ("crypto/social_analyst (A)", ca.create_crypto_social_analyst, (coingecko_tools,)),
    ]
    for name, factory, extra in crypto_sites:
        try:
            text, tool_tok = _capture_system_text(factory, crypto_state, *extra)
            rows.append(_row(name, _stable_prefix(text), tool_tok))
        except Exception as exc:  # pragma: no cover - diagnostic
            print(f"{name:34s} SKIP ({type(exc).__name__}: {exc})")
    return rows


def measure_pattern_b() -> list[tuple[str, int]]:
    """Trader (2 passes), risk_manager, compliance_officer: static system consts."""
    from tradingagents.agents.trader.trader import _DIRECTION_SYSTEM, _LEVELS_SYSTEM
    from tradingagents.agents.risk.risk_manager import _RISK_SYSTEM
    from tradingagents.agents.compliance.compliance_officer import _COMPLIANCE_SYSTEM

    sites = {
        "trader/_DIRECTION_SYSTEM (B)": _DIRECTION_SYSTEM,
        "trader/_LEVELS_SYSTEM (B)": _LEVELS_SYSTEM,
        "risk_manager/_RISK_SYSTEM (B)": _RISK_SYSTEM,
        "compliance/_COMPLIANCE_SYSTEM (B)": _COMPLIANCE_SYSTEM,
    }
    return [_row(name, text) for name, text in sites.items()]


def measure_ai_manager() -> list[tuple[str, int]]:
    """AI Manager system prompt (separate, mostly-static per account)."""
    from backend.services.ai_manager_prompts import build_system_prompt

    sites = {
        "ai_manager/system (moderate)": build_system_prompt("moderate"),
        "ai_manager/system (+target+cold)": build_system_prompt(
            "conservative", cold_start=True, daily_profit_target_pct=2.0
        ),
    }
    return [_row(name, text) for name, text in sites.items()]


if __name__ == "__main__":
    print(f"Tokenizer model: {MODEL}  (Sonnet min {SONNET_MIN}, Opus min {OPUS_MIN})\n")
    print("=== Pattern A (analysts) — stable prefix = boilerplate+tools+catalog ===")
    measure_pattern_a()
    print("\n=== Pattern B (trader/risk/compliance) — static system constants ===")
    measure_pattern_b()
    print("\n=== AI Manager (separate system prompt) ===")
    measure_ai_manager()
