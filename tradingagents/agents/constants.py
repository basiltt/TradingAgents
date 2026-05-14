"""State key constants and per-role information barrier allowlists.

No imports from agent modules — this module is a leaf dependency.
"""


class ReportKeys:
    MARKET = "market_report"
    DERIVATIVES = "derivatives_report"
    NEWS = "news_report"
    FUNDAMENTALS = "crypto_fundamentals_report"
    SENTIMENT = "sentiment_report"
    CONFLUENCE = "confluence_summary"
    INVESTMENT_PLAN = "investment_plan"
    TRADER_PLAN = "trader_investment_plan"
    RISK_MANAGER = "risk_manager_result"
    RISK_VERDICT = "_risk_manager_verdict"
    COMPLIANCE = "compliance_result"
    FINAL_DECISION = "final_trade_decision"
    TECHNICAL_LEVELS = "technical_levels_summary"
    MICROSTRUCTURE = "market_microstructure"
    PM_SIGNAL = "_pm_signal_data"
    TRADER_SIGNAL = "_trader_signal_data"
    EXECUTION_NOTES = "execution_notes"


READABLE_KEYS: dict[str, list[str]] = {
    "technical_analyst": [
        "messages", "trade_date", "company_of_interest",
        "crypto_interval", "current_price_context",
    ],
    "derivatives_analyst": [
        "messages", "trade_date", "company_of_interest",
        "crypto_interval", "current_price_context",
    ],
    "news_analyst": [
        "messages", "trade_date", "company_of_interest",
        "crypto_interval", "current_price_context",
    ],
    "fundamentals_analyst": [
        "messages", "trade_date", "company_of_interest",
        "crypto_interval", "current_price_context",
    ],
    "social_analyst": [
        "messages", "trade_date", "company_of_interest",
        "crypto_interval", "current_price_context",
    ],
    "confluence_checker": [
        "market_report", "derivatives_report", "news_report",
        "crypto_fundamentals_report", "sentiment_report",
        "current_price_context", "crypto_interval",
    ],
    "bull_researcher": [
        "market_report", "derivatives_report", "news_report",
        "crypto_fundamentals_report", "sentiment_report",
        "current_price_context", "investment_debate_state",
    ],
    "bear_researcher": [
        "market_report", "derivatives_report", "news_report",
        "crypto_fundamentals_report", "sentiment_report",
        "current_price_context", "investment_debate_state",
    ],
    "research_manager": [
        "company_of_interest", "crypto_interval",
        "investment_debate_state", "confluence_summary",
    ],
    "trader": [
        "company_of_interest", "crypto_interval",
        "current_price_context", "investment_plan",
        "technical_levels_summary",
    ],
    "compliance_officer": [
        "company_of_interest", "crypto_interval",
        "trader_investment_plan", "current_price_context",
        "max_leverage",
    ],
    "risk_manager": [
        "company_of_interest", "crypto_interval",
        "trader_investment_plan", "current_price_context",
        "max_leverage", "market_microstructure",
    ],
    "risk_bull_debater": [
        "trader_investment_plan", "current_price_context",
        "crypto_interval", "risk_debate_state",
        "market_microstructure",
    ],
    "risk_bear_debater": [
        "trader_investment_plan", "current_price_context",
        "crypto_interval", "risk_debate_state",
        "market_microstructure",
    ],
    "portfolio_manager": [
        "company_of_interest", "crypto_interval",
        "current_price_context", "investment_plan",
        "trader_investment_plan", "risk_debate_state",
        "past_context", "max_leverage", "risk_manager_result",
    ],
    "execution_monitor": [
        "company_of_interest", "crypto_interval",
        "final_trade_decision", "current_price_context",
    ],
}

WRITABLE_KEYS: dict[str, list[str]] = {
    "technical_analyst": ["market_report", "technical_levels_summary", "market_microstructure"],
    "derivatives_analyst": ["derivatives_report"],
    "news_analyst": ["news_report"],
    "fundamentals_analyst": ["crypto_fundamentals_report"],
    "social_analyst": ["sentiment_report"],
    "confluence_checker": ["confluence_summary"],
    "bull_researcher": ["investment_debate_state"],
    "bear_researcher": ["investment_debate_state"],
    "research_manager": ["investment_plan"],
    "trader": ["trader_investment_plan"],
    "compliance_officer": ["compliance_result"],
    "risk_manager": ["risk_manager_result", "_risk_manager_verdict"],
    "risk_bull_debater": ["risk_debate_state"],
    "risk_bear_debater": ["risk_debate_state"],
    "portfolio_manager": ["final_trade_decision", "_pm_signal_data"],
    "execution_monitor": ["execution_notes"],
}
