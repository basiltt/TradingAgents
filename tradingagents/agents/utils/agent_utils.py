"""Agent utility functions and tool re-exports for LangGraph trading agents.

Re-exports all LangChain tools (stock data, indicators, fundamentals, news)
and provides helper functions for message management and instrument context.
"""
from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files — re-exported for consumers
from tradingagents.agents.utils.core_stock_tools import (  # noqa: F401
    get_stock_data,
)
from tradingagents.agents.utils.technical_indicators_tools import (  # noqa: F401
    get_indicators,
)
from tradingagents.agents.utils.fundamental_data_tools import (  # noqa: F401
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
)
from tradingagents.agents.utils.news_data_tools import (  # noqa: F401
    get_news,
    get_insider_transactions,
    get_global_news,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


_INTERVAL_LABELS = {"15": "15-minute", "60": "1-hour", "240": "4-hour", "D": "daily"}


def build_instrument_context(ticker: str, crypto_interval: str | None = None) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    base = (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )
    if crypto_interval:
        label = _INTERVAL_LABELS.get(crypto_interval, crypto_interval)
        base += (
            f"\n\n**Primary timeframe: {label} (`{crypto_interval}`).** "
            f"Use interval=`{crypto_interval}` for your main analysis in every kline/indicator tool call. "
            "You may reference other timeframes for additional context, but your core "
            "trend analysis, signals, and recommendations MUST be based on this interval."
        )
    return base

def create_msg_delete():
    """Return a LangGraph state handler that clears all messages.

    Returns a closure compatible with LangGraph node functions. The closure
    removes all existing messages and inserts a placeholder HumanMessage
    ("Continue") required by the Anthropic API to avoid empty message lists.
    """
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility."""
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        placeholder = HumanMessage(content="Continue")
        return {"messages": removal_operations + [placeholder]}

    return delete_messages
