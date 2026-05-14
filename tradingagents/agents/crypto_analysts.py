"""Crypto perpetual futures analyst agents (TASK-011).

Factory functions that mirror the stock analyst pattern but use Bybit data
tools and crypto-specific prompts.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
    get_news,
    get_global_news,
)
from tradingagents.agents.utils.signal_validation import (
    SIGNAL_SCHEMA,
    parse_signal_from_llm_output,
    validate_signal,
    extract_current_price,
)
from tradingagents.agents.utils.prompt_guard import wrap_external_data

logger = logging.getLogger(__name__)

_MAX_DEBATE_HISTORY_CHARS = 12000


def _truncate_history(text: str, max_chars: int = _MAX_DEBATE_HISTORY_CHARS) -> str:
    """Keep only the most recent portion of debate history to prevent token blowup."""
    if len(text) <= max_chars:
        return text
    truncated = text[-max_chars:]
    first_newline = truncated.find("\n")
    if first_newline != -1:
        truncated = truncated[first_newline + 1:]
    return "[earlier rounds truncated]\n" + truncated


_ANALYST_SYSTEM_PREFIX = (
    "You are a helpful AI assistant, collaborating with other assistants."
    " Use the provided tools to progress towards answering the question."
    " If you are unable to fully answer, that's OK; another assistant with different tools"
    " will help where you left off. Execute what you can to make progress."
    " If you or any other assistant has the FINAL ANALYSIS or deliverable,"
    " prefix your response with FINAL ANALYSIS so the team knows to stop."
    " You have access to the following tools: {tool_names}.\n{system_message}"
    "For your reference, the current date is {current_date}. {instrument_context}"
    "\n\n--- CURRENT PRICE DATA (use this as the reference price for your analysis) ---\n"
    "{current_price_context}"
)


def create_crypto_technical_analyst(llm, crypto_tools: list):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "technical_analyst")
        current_date = filtered.get("trade_date", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        tools = [t for t in crypto_tools if t.name in ("get_crypto_klines", "get_crypto_indicators")]
        if not tools:
            raise ValueError("No technical analysis tools found in crypto_tools")

        system_message = (
            "You are a crypto futures technical analyst. Analyze OHLCV price data and "
            "technical indicators (RSI, MACD, Bollinger Bands, EMA) for the given perpetual "
            "futures contract. Identify trends, support/resistance levels, momentum signals, "
            "and potential entry/exit zones. Include the current price and data timestamp in "
            "your report. Call get_crypto_klines first, then get_crypto_indicators. "
            "If any tool returns an [ERROR], include a **Data Quality Warning** section "
            "at the end of your report listing which data sources were unavailable."
            " Write a detailed report with a Markdown summary table at the end."

            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", _ANALYST_SYSTEM_PREFIX),
            MessagesPlaceholder(variable_name="messages"),
        ])
        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join(t.name for t in tools),
            current_date=current_date,
            instrument_context=instrument_context,
            current_price_context=price_context,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(filtered.get("messages", []))

        report = result.content or ""
        return validate_state_write({
            "messages": [result],
            "market_report": report,
            "technical_levels_summary": report,
        }, "technical_analyst")

    return node


def create_crypto_derivatives_analyst(llm, crypto_tools: list):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "derivatives_analyst")
        current_date = filtered.get("trade_date", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        # Prefer the combined derivatives tool; fall back to individual tools
        combined = [t for t in crypto_tools if t.name == "get_crypto_derivatives_data"]
        if combined:
            tools = combined
        else:
            tools = [t for t in crypto_tools if t.name in ("get_funding_rates", "get_open_interest", "get_crypto_ticker")]
        if not tools:
            raise ValueError("No derivatives tools found in crypto_tools")

        system_message = (
            "You are a crypto derivatives analyst. Analyze funding rates, open interest "
            "trends, long/short ratio, and ticker data for the given perpetual futures contract. "
            "Assess funding cost impact on position holding, OI trends as a proxy for market "
            "sentiment and potential liquidation cascades, long/short ratio for crowd positioning, "
            "multi-timeframe price changes, and current market snapshot. "
            "If any data source is unavailable, acknowledge it and continue with available data. "
            "If any tool returns an [ERROR], include a **Data Quality Warning** section "
            "at the end of your report listing which data sources were unavailable."
            " Write a detailed report with a Markdown summary table at the end."

            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", _ANALYST_SYSTEM_PREFIX),
            MessagesPlaceholder(variable_name="messages"),
        ])
        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join(t.name for t in tools),
            current_date=current_date,
            instrument_context=instrument_context,
            current_price_context=price_context,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(filtered.get("messages", []))

        report = result.content or ""
        return validate_state_write({"messages": [result], "derivatives_report": report}, "derivatives_analyst")

    return node


def create_crypto_news_analyst(llm):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "news_analyst")
        current_date = filtered.get("trade_date", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        tools = [get_news, get_global_news]

        system_message = (
            "You are a crypto news analyst. Research recent news relevant to the given "
            "cryptocurrency futures contract. Search for the coin name (e.g. 'Bitcoin', "
            "'Ethereum'), related futures/derivatives news, and broader crypto market events. "
            "Use get_news for targeted searches and get_global_news for macro context. "
            "If any tool returns an [ERROR], include a **Data Quality Warning** section "
            "at the end of your report listing which data sources were unavailable."
            " Write a comprehensive report with a Markdown summary table at the end."

            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", _ANALYST_SYSTEM_PREFIX),
            MessagesPlaceholder(variable_name="messages"),
        ])
        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join(t.name for t in tools),
            current_date=current_date,
            instrument_context=instrument_context,
            current_price_context=price_context,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(filtered.get("messages", []))

        report = result.content or ""
        return validate_state_write({"messages": [result], "news_report": report}, "news_analyst")

    return node


def create_crypto_fundamentals_analyst(llm, coingecko_tools: list):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "fundamentals_analyst")
        current_date = filtered.get("trade_date", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        tools = [t for t in coingecko_tools if t.name == "get_crypto_market_data"]
        if not tools:
            raise ValueError("No market data tool found in coingecko_tools")

        system_message = (
            "You are a crypto fundamentals analyst. Evaluate the on-chain and market "
            "fundamentals for the given cryptocurrency. Analyze market capitalization trends, "
            "circulating vs total vs max supply dynamics, fully diluted valuation, trading "
            "volume relative to market cap, ATH/ATL distance, and multi-timeframe price "
            "performance (24h, 7d, 30d, 200d, 1y). Assess tokenomics health: inflation rate "
            "(if supply is growing), concentration risk, and sector positioning. "
            "Compare to major benchmarks (BTC, ETH) where relevant. "
            "If data is unavailable, acknowledge it and continue with what you have. "
            "If any tool returns an [ERROR], include a **Data Quality Warning** section "
            "at the end of your report listing which data sources were unavailable. "
            "Write a detailed report with a Markdown summary table at the end."

            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", _ANALYST_SYSTEM_PREFIX),
            MessagesPlaceholder(variable_name="messages"),
        ])
        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join(t.name for t in tools),
            current_date=current_date,
            instrument_context=instrument_context,
            current_price_context=price_context,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(filtered.get("messages", []))

        report = result.content or ""
        return validate_state_write({"messages": [result], "crypto_fundamentals_report": report}, "fundamentals_analyst")

    return node


def create_crypto_social_analyst(llm, coingecko_tools: list):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "social_analyst")
        current_date = filtered.get("trade_date", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        community_tools = [t for t in coingecko_tools if t.name == "get_crypto_community_data"]
        tools = community_tools + [get_news]

        system_message = (
            "You are a crypto social sentiment analyst. Evaluate community engagement "
            "and social metrics for the given cryptocurrency. Analyze Twitter/X follower "
            "count and growth, Reddit subscriber count and activity (posts, comments), "
            "Telegram community size, developer activity (GitHub commits, PRs, issues), "
            "and overall sentiment (bullish vs bearish vote percentages). "
            "Use get_news to search for social media buzz, trending narratives, "
            "influencer mentions, and community sentiment around the coin. "
            "Assess whether social momentum supports or contradicts the price action. "
            "If data is unavailable, acknowledge it and continue with what you have. "
            "If any tool returns an [ERROR], include a **Data Quality Warning** section "
            "at the end of your report listing which data sources were unavailable. "
            "Write a detailed report with a Markdown summary table at the end."

            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", _ANALYST_SYSTEM_PREFIX),
            MessagesPlaceholder(variable_name="messages"),
        ])
        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join(t.name for t in tools),
            current_date=current_date,
            instrument_context=instrument_context,
            current_price_context=price_context,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(filtered.get("messages", []))

        report = result.content or ""
        return validate_state_write({"messages": [result], "sentiment_report": report}, "social_analyst")

    return node


def create_confluence_checker(llm):
    """Agent that cross-checks all analyst reports for contradictions and consensus."""

    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write
        filtered = filter_state_for_read(state, "confluence_checker")
        crypto_interval = filtered.get("crypto_interval")
        market_report = wrap_external_data(filtered.get("market_report", ""), "technical_analyst")
        news_report = wrap_external_data(filtered.get("news_report", ""), "news_analyst")
        derivatives_report = wrap_external_data(filtered.get("derivatives_report", ""), "derivatives_analyst")
        crypto_fundamentals_report = wrap_external_data(filtered.get("crypto_fundamentals_report", ""), "fundamentals_analyst")
        sentiment_report = wrap_external_data(filtered.get("sentiment_report", ""), "social_analyst")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")

        reports = ""
        if market_report:
            reports += f"\n## Technical/Market Report\n{market_report}"
        if news_report:
            reports += f"\n## News Report\n{news_report}"
        if derivatives_report:
            reports += f"\n## Derivatives Report\n{derivatives_report}"
        if crypto_fundamentals_report:
            reports += f"\n## Crypto Fundamentals Report\n{crypto_fundamentals_report}"
        if sentiment_report:
            reports += f"\n## Social Sentiment Report\n{sentiment_report}"

        tf_note = ""
        if crypto_interval:
            tf_note = (
                f"\n\nTimeframe context: The user is trading on a **{crypto_interval}** chart. "
                "Weight signals accordingly — sentiment and news matter more for short-term trades, "
                "fundamentals and on-chain metrics matter more for longer timeframes.\n"
            )

        prompt = (
            "You are a Confluence Checker. Your job is to cross-validate the analyst reports below "
            "and produce a structured consensus summary.\n\n"
            "Read each analyst report carefully and identify the directional lean from the "
            "evidence presented (bullish, bearish, or neutral).\n\n"
            f"Current price context:\n{price_context}\n"
            f"{tf_note}\n"
            f"Analyst Reports:{reports}\n\n"
            "Produce a structured summary with these sections:\n"
            "1. **ANALYST LEANS**: For each analyst, state the directional lean you inferred from their report\n"
            "2. **AGREEMENTS**: Points where 2+ analysts agree (bullish or bearish)\n"
            "3. **CONTRADICTIONS**: Points where analysts disagree — state both sides\n"
            "4. **CONSENSUS DIRECTION**: Choose exactly one:\n"
            "   - Bullish (majority of analysts lean bullish)\n"
            "   - Bearish (majority of analysts lean bearish)\n"
            "   - Neutral (no strong lean in either direction)\n"
            "   - Conflicting (analysts actively disagree)\n"
            "5. **CONSENSUS CONFIDENCE**: 1-10 based on how much the analysts agree\n"
            "6. **KEY RISK**: The single biggest risk that could invalidate the consensus\n\n"
            "IMPORTANT: If analysts contradict each other, say 'Conflicting' — do NOT force a direction. "
            "A 'Conflicting' consensus with low confidence is more valuable than a false consensus.\n\n"
            "IMPORTANT: If any analyst report contains a 'Data Quality Warning' section, reduce "
            "CONSENSUS CONFIDENCE by 1-3 points depending on how critical the missing data was. "
            "Note which analysts had incomplete data in your summary.\n\n"
            "Be concise. Focus on actionable information for a trader."
        )

        from tradingagents.agents.utils.state_filter import validate_state_write
        result = llm.invoke(prompt)
        return validate_state_write({
            "confluence_summary": result.content,
            "sender": "ConfluenceChecker",
        }, "confluence_checker")

    return node


# ---------------------------------------------------------------------------
# Crypto Bull/Bear Researchers — debate layer between Confluence and RM
# ---------------------------------------------------------------------------


def create_crypto_bull_researcher(llm):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "bull_researcher")
        investment_debate_state = filtered.get("investment_debate_state", {})
        history = _truncate_history(investment_debate_state.get("history", ""))
        bull_history = investment_debate_state.get("bull_history", "")
        current_response = investment_debate_state.get("current_response", "")


        market_report = wrap_external_data(filtered.get("market_report", ""), "technical_analyst")
        news_report = wrap_external_data(filtered.get("news_report", ""), "news_analyst")
        derivatives_report = wrap_external_data(filtered.get("derivatives_report", ""), "derivatives_analyst")
        crypto_fundamentals_report = wrap_external_data(filtered.get("crypto_fundamentals_report", ""), "fundamentals_analyst")
        sentiment_report = wrap_external_data(filtered.get("sentiment_report", ""), "social_analyst")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")

        prompt = f"""You are a Bull Researcher advocating for a long position in this crypto asset. Build an evidence-based case emphasizing upside potential, favorable market structure, and positive catalysts.

Key points to focus on:
- Upside Potential: Highlight favorable funding rates, bullish OI trends, strong volume, and positive technical setups.
- Fundamental Strengths: Emphasize tokenomics health, growing adoption, developer activity, and strong community engagement.
- Positive Catalysts: Use recent news, social sentiment momentum, and macro tailwinds as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data, showing why the bull case holds merit.
- Intellectual Honesty: If the data does not support a bullish case, acknowledge that rather than fabricating arguments.

Resources available:
Market/Technical report: {market_report}
Social sentiment report: {sentiment_report}
News report: {news_report}
Derivatives report: {derivatives_report}
Crypto fundamentals report: {crypto_fundamentals_report}
Current price data: {price_context}
Debate history: {history}
Last bear argument: {current_response}

Present the evidence-based bull case for this asset."""

        response = llm.invoke(prompt)
        argument = f"Bull Analyst: {response.content}"

        new_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return validate_state_write({"investment_debate_state": new_state}, "bull_researcher")

    return node


def create_crypto_bear_researcher(llm):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "bear_researcher")
        investment_debate_state = filtered.get("investment_debate_state", {})
        history = _truncate_history(investment_debate_state.get("history", ""))
        bear_history = investment_debate_state.get("bear_history", "")
        current_response = investment_debate_state.get("current_response", "")


        market_report = wrap_external_data(filtered.get("market_report", ""), "technical_analyst")
        news_report = wrap_external_data(filtered.get("news_report", ""), "news_analyst")
        derivatives_report = wrap_external_data(filtered.get("derivatives_report", ""), "derivatives_analyst")
        crypto_fundamentals_report = wrap_external_data(filtered.get("crypto_fundamentals_report", ""), "fundamentals_analyst")
        sentiment_report = wrap_external_data(filtered.get("sentiment_report", ""), "social_analyst")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")

        prompt = f"""You are a Bear Researcher making the case against a long position in this crypto asset. Present an evidence-based argument emphasizing downside risks, structural weaknesses, and negative indicators.

Key points to focus on:
- Downside Risks: Highlight unfavorable funding rates, declining OI, bearish technical patterns, and liquidation risks.
- Fundamental Weaknesses: Emphasize tokenomics concerns (inflation, concentration), declining developer activity, or weak community metrics.
- Negative Catalysts: Use adverse news, regulatory threats, declining social sentiment, or macro headwinds.
- Bull Counterpoints: Critically analyze the bull argument with specific data, exposing over-optimistic assumptions.
- Intellectual Honesty: If the data genuinely supports a bullish case, acknowledge that rather than manufacturing bearish arguments.

Resources available:
Market/Technical report: {market_report}
Social sentiment report: {sentiment_report}
News report: {news_report}
Derivatives report: {derivatives_report}
Crypto fundamentals report: {crypto_fundamentals_report}
Current price data: {price_context}
Debate history: {history}
Last bull argument: {current_response}

Present the evidence-based bear case for this asset."""

        response = llm.invoke(prompt)
        argument = f"Bear Analyst: {response.content}"

        new_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return validate_state_write({"investment_debate_state": new_state}, "bear_researcher")

    return node


# ---------------------------------------------------------------------------
# Crypto Research Manager — judges the bull/bear debate
# ---------------------------------------------------------------------------


def create_crypto_research_manager(llm):
    from tradingagents.agents.schemas import ResearchPlan, render_research_plan
    from tradingagents.agents.utils.agent_utils import build_instrument_context
    from tradingagents.agents.utils.structured import (
        bind_structured,
        invoke_structured_or_freetext,
    )

    structured_llm = bind_structured(llm, ResearchPlan, "Crypto Research Manager")

    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read
        filtered = filter_state_for_read(state, "research_manager")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(filtered.get("company_of_interest", ""), crypto_interval)
        investment_debate_state = filtered.get("investment_debate_state", {})
        history = _truncate_history(investment_debate_state.get("history", ""))

        prompt = f"""As the Crypto Research Manager and debate facilitator, critically evaluate the bull/bear debate and deliver a clear, actionable investment plan for the crypto trader.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance based on the weight of evidence. Hold is a fully valid recommendation when the evidence is balanced or insufficient — not a last resort.

---

**Debate History:**
{history}"""

        investment_plan, _ = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Crypto Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        from tradingagents.agents.utils.state_filter import validate_state_write
        return validate_state_write({
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }, "research_manager")

    return node


def create_crypto_trader(llm, max_leverage: int = 20):
    signal_schema_str = json.dumps(SIGNAL_SCHEMA, indent=2)

    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "trader")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        raw_investment_plan = filtered.get("investment_plan", "")
        investment_plan = wrap_external_data(raw_investment_plan, "research_manager")
        technical_levels = wrap_external_data(filtered.get("technical_levels_summary", "Not available"), "technical_analyst")

        if not raw_investment_plan or not raw_investment_plan.strip():
            logger.warning(
                "CryptoTrader: no investment_plan received for %s; "
                "defaulting to No Trade.",
                company,
            )
            no_trade_signal = {
                "trade_type": "No Trade",
                "confidence": 1,
                "reasoning": "No investment plan received from Research Manager. Cannot determine direction.",
            }
            return validate_state_write({
                "messages": [AIMessage(content=json.dumps(no_trade_signal, indent=2))],
                "trader_investment_plan": json.dumps(no_trade_signal, indent=2),
                "sender": "CryptoTrader",
            }, "trader")

        base_prompt = (
            f"You are a crypto futures execution trader for {company}. {instrument_context}\n\n"
            f"The directional decision has ALREADY been made by the Research Manager. "
            f"Your job is to translate their investment plan into precise execution levels.\n\n"
            f"## Research Manager's Investment Plan\n{investment_plan}\n\n"
            f"## Technical Levels Summary\n{technical_levels}\n\n"
            f"IMPORTANT — CURRENT PRICE DATA (base your entry/SL/TP on this):\n{price_context}\n\n"
            f"EXECUTION RULES:\n"
            f"- If the RM recommends Buy or Overweight, output a Long signal\n"
            f"- If the RM recommends Sell or Underweight, output a Short signal\n"
            f"- If the RM recommends Hold, output 'No Trade'\n"
            f"- Do NOT override the RM's direction — focus on execution levels only\n\n"
            f"PRICE ANCHORING RULES (mandatory when trading):\n"
            f"- Your entry_price MUST be within 2% of the current last-traded price.\n"
            f"- You must provide at least 1 stop_loss and at least 1 take_profit.\n"
            f"- Each stop_loss must be at least 0.3% away from entry.\n"
            f"- Each take_profit must be at least 0.5% away from entry.\n"
            f"- Stop-loss must not exceed 10% from entry (leveraged futures constraint).\n"
            f"- Risk:reward ratio must be at least 0.5 (TP distance >= half of SL distance).\n"
            f"- Leverage above 10x requires confidence >= 5.\n\n"
            f"CONFIDENCE CALIBRATION (1-10 scale):\n"
            f"- 1-3: Weak conviction from RM, conservative sizing\n"
            f"- 4-5: Moderate conviction, standard sizing\n"
            f"- 6-7: Strong conviction, can size up\n"
            f"- 8-9: Very strong conviction across all signals\n"
            f"- 10: Exceptional — rarely appropriate\n\n"
            f"You MUST output a JSON object matching this schema:\n{signal_schema_str}\n\n"
            f"Output ONLY the JSON inside a ```json``` code block."
        )

        messages = [{"role": "user", "content": base_prompt}]
        current_price = extract_current_price(price_context)
        max_attempts = 2

        for attempt in range(max_attempts):
            result = llm.invoke(messages)
            parsed = parse_signal_from_llm_output(result.content)

            if not parsed:
                if attempt < max_attempts - 1:
                    messages.append({"role": "assistant", "content": result.content})
                    messages.append({"role": "user", "content": "Failed to parse JSON. Please output ONLY a JSON object in a ```json``` block."})
                    continue
                logger.warning(
                    "CryptoTrader: could not parse signal for %s after %d attempts — defaulting to No Trade.",
                    company, max_attempts,
                )
                no_trade = {
                    "trade_type": "No Trade",
                    "confidence": 1,
                    "reasoning": "Signal parse failure after retries. Cannot produce a valid execution plan.",
                }
                return validate_state_write({
                    "messages": [AIMessage(content=json.dumps(no_trade, indent=2))],
                    "trader_investment_plan": json.dumps(no_trade, indent=2),
                    "sender": "CryptoTrader",
                }, "trader")

            ok, errors = validate_signal(parsed, max_leverage=max_leverage, current_price=current_price)
            if ok:
                return validate_state_write({
                    "messages": [AIMessage(content=result.content)],
                    "trader_investment_plan": json.dumps(parsed, indent=2),
                    "sender": "CryptoTrader",
                }, "trader")

            if attempt < max_attempts - 1:
                messages.append({"role": "assistant", "content": result.content})
                messages.append({"role": "user", "content": f"Signal validation failed: {'; '.join(errors)}. Fix the issues and output the corrected JSON."})
                continue

        logger.warning(
            "CryptoTrader: signal validation failed for %s after %d attempts — defaulting to No Trade. Errors: %s",
            company, max_attempts, "; ".join(errors),
        )
        no_trade = {
            "trade_type": "No Trade",
            "confidence": 1,
            "reasoning": f"Signal validation failed after {max_attempts} attempts: {'; '.join(errors)}",
        }
        return validate_state_write({
            "messages": [AIMessage(content=json.dumps(no_trade, indent=2))],
            "trader_investment_plan": json.dumps(no_trade, indent=2),
            "sender": "CryptoTrader",
        }, "trader")

    return node


def create_crypto_risk_bull_debater(llm):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "risk_bull_debater")
        risk_debate_state = filtered.get("risk_debate_state", {})
        history = _truncate_history(risk_debate_state.get("history", ""))
        trader_decision = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        market_microstructure = filtered.get("market_microstructure", "")
        bear_response = risk_debate_state.get("current_conservative_response", "")

        micro_context = ""
        if market_microstructure:
            micro_context = f"\nMarket microstructure data: {wrap_external_data(str(market_microstructure), 'market_microstructure')}\n"

        prompt = (
            f"As the Bullish Risk Analyst for crypto futures, your role is to identify "
            f"upside opportunity in the current market using evidence from the reports.\n\n"
            f"- Present the strongest evidence-based case for why this trade has favorable "
            f"risk-reward, citing specific data points from the reports.\n"
            f"- If the data genuinely does not support a bullish case, acknowledge that "
            f"honestly rather than fabricating arguments.\n"
            f"- Your job is to stress-test the bear's concerns, not to force a trade.\n\n"
            f"CURRENT PRICE DATA:\n{price_context}\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"{micro_context}"
            f"Debate history: {history}\n"
            f"Bear analyst's last response: {bear_response}\n\n"
            f"Present the evidence-based bull case."
        )

        response = llm.invoke(prompt)
        argument = f"Bull Analyst: {response.content}"

        new_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", "") + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Bull",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state["count"] + 1,
        }

        return validate_state_write({"risk_debate_state": new_state}, "risk_bull_debater")

    return node


def create_crypto_risk_bear_debater(llm):
    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "risk_bear_debater")
        risk_debate_state = filtered.get("risk_debate_state", {})
        history = _truncate_history(risk_debate_state.get("history", ""))
        trader_decision = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        market_microstructure = filtered.get("market_microstructure", "")
        bull_response = risk_debate_state.get("current_aggressive_response", "")

        micro_context = ""
        if market_microstructure:
            micro_context = f"\nMarket microstructure data: {wrap_external_data(str(market_microstructure), 'market_microstructure')}\n"

        prompt = (
            f"As the Bearish Risk Analyst for crypto futures, identify specific downside "
            f"risks using DATA from the reports — cite numbers, levels, and indicators.\n\n"
            f"- Present the strongest evidence-based case for why this trade carries "
            f"unfavorable risk (e.g. resistance levels, declining volume, negative funding rates).\n"
            f"- If the data genuinely supports the trade, acknowledge that honestly "
            f"rather than manufacturing bearish arguments.\n"
            f"- Your job is to stress-test the bull's optimism, not to force a no-trade.\n\n"
            f"RULES:\n"
            f"- Every claim must reference a specific data point from the reports.\n"
            f"- Do NOT use generic fear language ('crash', 'catastrophic', 'wipeout') — "
            f"instead quantify the risk (e.g. 'support at $X, if broken targets $Y = Z% downside').\n"
            f"- Be intellectually honest — if the data strongly supports "
            f"a trade, acknowledge strengths before presenting risks.\n\n"
            f"CURRENT PRICE DATA:\n{price_context}\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"{micro_context}"
            f"Debate history: {history}\n"
            f"Bull analyst's last response: {bull_response}\n\n"
            f"Present the evidence-based bear case."
        )

        response = llm.invoke(prompt)
        argument = f"Bear Analyst: {response.content}"

        new_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", "") + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Bear",
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state["count"] + 1,
        }

        return validate_state_write({"risk_debate_state": new_state}, "risk_bear_debater")

    return node


def create_crypto_portfolio_manager(llm, max_leverage: int = 20):
    from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
    from tradingagents.agents.utils.structured import bind_structured, invoke_structured_or_freetext

    structured_llm = bind_structured(llm, PortfolioDecision, "Crypto PM")

    def node(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "portfolio_manager")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        risk_debate_state = filtered.get("risk_debate_state", {})
        history = _truncate_history(risk_debate_state.get("history", ""))
        research_plan = wrap_external_data(filtered.get("investment_plan", ""), "research_manager")
        trader_plan = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        risk_manager_result = wrap_external_data(filtered.get("risk_manager_result", ""), "risk_manager")

        past_context = wrap_external_data(filtered.get("past_context", ""), "past_context")
        lessons_line = (
            f"- Lessons from prior decisions:\n{past_context}\n" if past_context else ""
        )
        risk_manager_line = (
            f"- Risk Manager assessment:\n{risk_manager_result}\n" if risk_manager_result else ""
        )

        prompt = (
            f"As the Crypto Futures Portfolio Manager, synthesize the risk debate and "
            f"deliver the final trading decision.\n\n"
            f"{instrument_context}\n\n"
            f"CURRENT PRICE DATA (use as reference for entry/SL/TP levels):\n{price_context}\n\n"
            f"Max allowed leverage: {max_leverage}x\n\n"
            f"DECISION FRAMEWORK:\n"
            f"- Evaluate the trade objectively based on the bull/bear debate and market data.\n"
            f"- REJECT if the evidence is genuinely insufficient or the risk is clearly unfavorable.\n"
            f"- MODIFY to adjust risk parameters (leverage, stops) when the direction is sound but sizing needs work.\n"
            f"- APPROVE if the data and debate support the trade with acceptable risk.\n"
            f"- Past trade results are context, not predictive — treat each trade independently.\n\n"
            f"Research plan: {research_plan}\n"
            f"Trader's proposal:\n{trader_plan}\n"
            f"{lessons_line}{risk_manager_line}"
            f"Risk debate history:\n{history}\n\n"
            f"Provide your final decision: REJECT (no trade) / MODIFY (with changes) / APPROVE (as-is). "
            f"Include specific position sizing and leverage recommendation if approving/modifying."
            f"{get_language_instruction()}"
        )

        final_decision, decision_obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Crypto PM",
        )

        new_risk_debate_state = {
            "judge_decision": final_decision,
            "history": risk_debate_state.get("history", ""),
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "count": risk_debate_state.get("count", 0),
        }

        return validate_state_write({
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_decision,
            "_pm_signal_data": decision_obj,
        }, "portfolio_manager")

    return node
