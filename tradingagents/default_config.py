import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings (overridable via env vars)
    "llm_provider": os.getenv("TRADINGAGENTS_LLM_PROVIDER", "openai"),
    "deep_think_llm": os.getenv("TRADINGAGENTS_DEEP_THINK_LLM", "gpt-5.4"),
    "quick_think_llm": os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-5.4-mini"),
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": os.getenv("TRADINGAGENTS_BACKEND_URL", None),
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Maximum concurrent LLM API calls (0 = unlimited).
    # Users on pay-as-you-go plans can leave this at 0.
    "llm_max_concurrent": 0,
    # Minimum milliseconds between consecutive LLM API calls (0 = no spacing).
    "llm_min_spacing_ms": 0,
    # Debate and discussion settings
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
    "max_recur_limit": 100,
    # Asset type: "stock" (default) or "crypto"
    "asset_type": "stock",
    # Default analysts for quick_trade mode (user-configurable).
    # Full analysis uses all available analysts; quick_trade uses this subset.
    "quick_trade_analysts": {
        "crypto": ["crypto_technical", "crypto_derivatives", "crypto_news"],
        "stock": ["market", "news"],
    },
    # Crypto-specific settings
    "crypto_interval": "60",
    "crypto_max_leverage": 20,
    "exchange_credentials": {
        "bybit": {
            "api_key": os.getenv("BYBIT_API_KEY") or None,
            "api_secret": os.getenv("BYBIT_API_SECRET") or None,
        },
    },
    # TA Pre-Filter: run technical analysis before LLM calls (crypto only)
    "ta_prefilter_enabled": False,
    "ta_prefilter_threshold": 40,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
