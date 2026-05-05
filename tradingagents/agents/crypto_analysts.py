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

logger = logging.getLogger(__name__)

_ANALYST_VERDICT_BLOCK = (
    "\n\nAt the END of your report, you MUST include a structured verdict block:\n"
    "```\n"
    "VERDICT: NEUTRAL | BULLISH | BEARISH\n"
    "SCORE: <1-10> (1=strongly bearish, 5=neutral, 10=strongly bullish)\n"
    "KEY_FACTOR: <one-sentence reason for your verdict>\n"
    "```\n"
    "This verdict is critical — downstream agents depend on it for decision-making."
)

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
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
        tools = [t for t in crypto_tools if t.name in ("get_crypto_klines", "get_crypto_indicators")]
        if not tools:
            raise ValueError("No technical analysis tools found in crypto_tools")

        system_message = (
            "You are a crypto futures technical analyst. Analyze OHLCV price data and "
            "technical indicators (RSI, MACD, Bollinger Bands, EMA) for the given perpetual "
            "futures contract. Identify trends, support/resistance levels, momentum signals, "
            "and potential entry/exit zones. Include the current price and data timestamp in "
            "your report. Call get_crypto_klines first, then get_crypto_indicators."
            " Write a detailed report with a Markdown summary table at the end."
            + _ANALYST_VERDICT_BLOCK
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
        result = chain.invoke(state["messages"])

        report = result.content or ""
        return {"messages": [result], "market_report": report}

    return node


def create_crypto_derivatives_analyst(llm, crypto_tools: list):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
        tools = [t for t in crypto_tools if t.name in ("get_funding_rates", "get_open_interest", "get_crypto_ticker")]
        if not tools:
            raise ValueError("No derivatives tools found in crypto_tools")

        system_message = (
            "You are a crypto derivatives analyst. Analyze funding rates, open interest "
            "trends, and ticker data for the given perpetual futures contract. Assess "
            "funding cost impact on position holding, OI trends as a proxy for market "
            "sentiment and potential liquidation cascades, and current market snapshot. "
            "If any data source is unavailable, acknowledge it and continue with available data."
            " Write a detailed report with a Markdown summary table at the end."
            + _ANALYST_VERDICT_BLOCK
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
        result = chain.invoke(state["messages"])

        report = result.content or ""
        return {"messages": [result], "fundamentals_report": report}

    return node


def create_crypto_news_analyst(llm):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
        tools = [get_news, get_global_news]

        system_message = (
            "You are a crypto news analyst. Research recent news relevant to the given "
            "cryptocurrency futures contract. Search for the coin name (e.g. 'Bitcoin', "
            "'Ethereum'), related futures/derivatives news, and broader crypto market events. "
            "Use get_news for targeted searches and get_global_news for macro context. "
            "Write a comprehensive report with a Markdown summary table at the end."
            + _ANALYST_VERDICT_BLOCK
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
        result = chain.invoke(state["messages"])

        report = result.content or ""
        return {"messages": [result], "news_report": report}

    return node


def create_crypto_fundamentals_analyst(llm, coingecko_tools: list):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
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
            "Write a detailed report with a Markdown summary table at the end."
            + _ANALYST_VERDICT_BLOCK
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
        result = chain.invoke(state["messages"])

        report = result.content or ""
        return {"messages": [result], "crypto_fundamentals_report": report}

    return node


def create_crypto_social_analyst(llm, coingecko_tools: list):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
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
            "Write a detailed report with a Markdown summary table at the end."
            + _ANALYST_VERDICT_BLOCK
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
        result = chain.invoke(state["messages"])

        report = result.content or ""
        return {"messages": [result], "sentiment_report": report}

    return node


def create_confluence_checker(llm):
    """Agent that cross-checks all analyst reports for contradictions and consensus."""

    def node(state):
        market_report = state.get("market_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        crypto_fundamentals_report = state.get("crypto_fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        price_context = state.get("current_price_context", "")

        reports = ""
        if market_report:
            reports += f"\n## Technical/Market Report\n{market_report}"
        if news_report:
            reports += f"\n## News Report\n{news_report}"
        if fundamentals_report:
            reports += f"\n## Derivatives Report\n{fundamentals_report}"
        if crypto_fundamentals_report:
            reports += f"\n## Crypto Fundamentals Report\n{crypto_fundamentals_report}"
        if sentiment_report:
            reports += f"\n## Social Sentiment Report\n{sentiment_report}"

        prompt = (
            "You are a Confluence Checker. Your job is to cross-validate the analyst reports below "
            "and produce a structured consensus summary.\n\n"
            "Each analyst report ends with a VERDICT block (BULLISH/BEARISH/NEUTRAL + SCORE 1-10). "
            "Use these verdicts as the primary input — they represent each analyst's bottom-line view.\n\n"
            f"Current price context:\n{price_context}\n\n"
            f"Analyst Reports:{reports}\n\n"
            "Produce a structured summary with these sections:\n"
            "1. **VERDICT TALLY**: List each analyst's verdict and score in a table\n"
            "2. **AGREEMENTS**: Points where 2+ analysts agree (bullish or bearish)\n"
            "3. **CONTRADICTIONS**: Points where analysts disagree — state both sides\n"
            "4. **CONSENSUS DIRECTION**: Choose exactly one based on the weighted verdicts:\n"
            "   - Bullish (majority of analysts scored >= 6)\n"
            "   - Bearish (majority of analysts scored <= 4)\n"
            "   - Neutral (scores cluster around 5, no strong lean)\n"
            "   - Conflicting (analysts actively disagree — e.g. one scored >= 7 while another scored <= 3)\n"
            "5. **CONSENSUS CONFIDENCE**: 1-10 based on how much the analysts agree\n"
            "6. **KEY RISK**: The single biggest risk that could invalidate the consensus\n\n"
            "IMPORTANT: If analysts contradict each other, say 'Conflicting' — do NOT force a direction. "
            "A 'Conflicting' consensus with low confidence is more valuable than a false consensus.\n\n"
            "Be concise. Focus on actionable information for a trader."
        )

        result = llm.invoke(prompt)
        return {
            "confluence_summary": result.content,
            "sender": "ConfluenceChecker",
        }

    return node


def create_crypto_trader(llm, max_leverage: int = 20):
    signal_schema_str = json.dumps(SIGNAL_SCHEMA, indent=2)

    def node(state):
        company = state["company_of_interest"]
        instrument_context = build_instrument_context(company)
        price_context = state.get("current_price_context", "")
        investment_plan = state.get("investment_plan", "")
        market_report = state.get("market_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        crypto_fundamentals_report = state.get("crypto_fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        confluence_summary = state.get("confluence_summary", "")

        analyst_context = ""
        if market_report:
            analyst_context += f"\n\n## Market/Technical Report\n{market_report}"
        if news_report:
            analyst_context += f"\n\n## News Report\n{news_report}"
        if fundamentals_report:
            analyst_context += f"\n\n## Fundamentals/Derivatives Report\n{fundamentals_report}"
        if crypto_fundamentals_report:
            analyst_context += f"\n\n## Crypto Fundamentals Report\n{crypto_fundamentals_report}"
        if sentiment_report:
            analyst_context += f"\n\n## Social Sentiment Report\n{sentiment_report}"

        confluence_section = f"\n\n## Confluence Analysis\n{confluence_summary}" if confluence_summary else ""

        base_prompt = (
            f"You are a crypto futures trader analyzing {company}. {instrument_context}\n\n"
            f"IMPORTANT — CURRENT PRICE DATA (base your entry/SL/TP on this):\n{price_context}\n\n"
            f"HOW TO READ ANALYST REPORTS:\n"
            f"Each analyst report ends with a VERDICT block containing their direction "
            f"(BULLISH/BEARISH/NEUTRAL) and a score (1-10). Use these as your primary inputs:\n"
            f"- If 3+ analysts agree AND no analyst actively contradicts (opposite direction with score >= 6), lean that way\n"
            f"- If analysts are split, contradicting, or mostly NEUTRAL, consider No Trade\n"
            f"- The confluence summary tallies these verdicts — use it as a quick reference\n\n"
            f"DECISION RULES:\n"
            f"- Evaluate the data objectively. If the evidence clearly supports a direction, output the corresponding signal. "
            f"If the evidence is genuinely conflicting or insufficient, output 'No Trade'.\n"
            f"- Both trading and not trading are valid outcomes — choose based on the data, not caution.\n\n"
            f"PRICE ANCHORING RULES (mandatory when trading):\n"
            f"- Your entry_price MUST be within 2% of the current last-traded price.\n"
            f"- You must provide at least 1 stop_loss and at least 1 take_profit.\n"
            f"- Each stop_loss must be at least 0.3% away from entry.\n"
            f"- Each take_profit must be at least 0.5% away from entry.\n"
            f"- Stop-loss must not exceed 10% from entry (leveraged futures constraint).\n"
            f"- Risk:reward ratio must be at least 0.5 (TP distance >= half of SL distance).\n"
            f"- Leverage above 10x requires confidence >= 5.\n\n"
            f"CONFIDENCE CALIBRATION (1-10 scale):\n"
            f"- 1-3: Conflicting or insufficient data\n"
            f"- 4-5: Mixed signals with slight directional lean\n"
            f"- 6-7: Multiple aligned signals with minor concerns\n"
            f"- 8-9: Strong multi-timeframe alignment, clear trend + volume confirmation\n"
            f"- 10: Exceptional — rarely appropriate\n\n"
            f"You MUST output a JSON object matching this schema:\n{signal_schema_str}\n\n"
            f"Research plan: {investment_plan}"
            f"{analyst_context}"
            f"{confluence_section}\n\n"
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
                return {
                    "messages": [AIMessage(content=result.content)],
                    "trader_investment_plan": "Error: Could not parse trading signal from LLM output.",
                    "sender": "CryptoTrader",
                }

            ok, errors = validate_signal(parsed, max_leverage=max_leverage, current_price=current_price)
            if ok:
                return {
                    "messages": [AIMessage(content=result.content)],
                    "trader_investment_plan": json.dumps(parsed, indent=2),
                    "sender": "CryptoTrader",
                }

            if attempt < max_attempts - 1:
                messages.append({"role": "assistant", "content": result.content})
                messages.append({"role": "user", "content": f"Signal validation failed: {'; '.join(errors)}. Fix the issues and output the corrected JSON."})
                continue

        return {
            "messages": [AIMessage(content=result.content)],
            "trader_investment_plan": f"Error: Invalid signal after {max_attempts} attempts. Errors: {'; '.join(errors)}",
            "sender": "CryptoTrader",
        }

    return node


def create_crypto_risk_bull_debater(llm):
    def node(state):
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        trader_decision = state.get("trader_investment_plan", "")
        market_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        crypto_fundamentals_report = state.get("crypto_fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        price_context = state.get("current_price_context", "")
        bear_response = risk_debate_state.get("current_conservative_response", "")

        extra_context = ""
        if crypto_fundamentals_report:
            extra_context += f"\nCrypto fundamentals report: {crypto_fundamentals_report}\n"
        if sentiment_report:
            extra_context += f"\nSocial sentiment report: {sentiment_report}\n"

        prompt = (
            f"As the Bullish Risk Analyst for crypto futures, your role is to identify "
            f"upside opportunity in the current market using evidence from the reports.\n\n"
            f"- If the trader proposes a Long/Short: argue in favor, emphasizing upside "
            f"potential, favorable risk-reward, and supportive conditions.\n"
            f"- If the trader proposes 'No Trade': challenge that decision — argue that "
            f"there IS a tradeable opportunity being missed.\n\n"
            f"You must be intellectually honest — if the data does not support "
            f"a bullish case, acknowledge weaknesses rather than fabricating arguments.\n\n"
            f"CURRENT PRICE DATA:\n{price_context}\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"Market report: {market_report}\n"
            f"News report: {news_report}\n"
            f"Derivatives report: {fundamentals_report}\n"
            f"{extra_context}"
            f"Debate history: {history}\n"
            f"Bear analyst's last response: {bear_response}\n\n"
            f"Counter the bear's arguments with evidence."
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

        return {"risk_debate_state": new_state}

    return node


def create_crypto_risk_bear_debater(llm):
    def node(state):
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        trader_decision = state.get("trader_investment_plan", "")
        market_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        crypto_fundamentals_report = state.get("crypto_fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        price_context = state.get("current_price_context", "")
        bull_response = risk_debate_state.get("current_aggressive_response", "")

        extra_context = ""
        if crypto_fundamentals_report:
            extra_context += f"\nCrypto fundamentals report: {crypto_fundamentals_report}\n"
        if sentiment_report:
            extra_context += f"\nSocial sentiment report: {sentiment_report}\n"

        prompt = (
            f"As the Bearish Risk Analyst for crypto futures, identify specific downside "
            f"risks using DATA from the reports — cite numbers, levels, and indicators.\n\n"
            f"- If the trader proposes a Long/Short: argue against using specific evidence "
            f"(e.g. resistance levels, declining volume, negative funding rates, bearish divergence).\n"
            f"- If the trader proposes 'No Trade': support that caution with specific data "
            f"points showing why conditions are too uncertain.\n\n"
            f"RULES:\n"
            f"- Every claim must reference a specific data point from the reports.\n"
            f"- Do NOT use generic fear language ('crash', 'catastrophic', 'wipeout') — "
            f"instead quantify the risk (e.g. 'support at $X, if broken targets $Y = Z% downside').\n"
            f"- Be intellectually honest — if the data strongly supports "
            f"a trade, acknowledge strengths before presenting risks.\n\n"
            f"CURRENT PRICE DATA:\n{price_context}\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"Market report: {market_report}\n"
            f"News report: {news_report}\n"
            f"Derivatives report: {fundamentals_report}\n"
            f"{extra_context}"
            f"Debate history: {history}\n"
            f"Bull analyst's last response: {bull_response}\n\n"
            f"Counter the bull's arguments with evidence of downside risks."
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

        return {"risk_debate_state": new_state}

    return node


def create_crypto_portfolio_manager(llm, max_leverage: int = 20):
    def node(state):
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "")
        history = state["risk_debate_state"]["history"]
        research_plan = state.get("investment_plan", "")
        trader_plan = state.get("trader_investment_plan", "")
        risk_debate_state = state["risk_debate_state"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions:\n{past_context}\n" if past_context else ""
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
            f"Trader's proposed direction: {trader_plan.split(chr(10))[0] if trader_plan else 'None'}\n"
            f"{lessons_line}"
            f"Risk debate history:\n{history}\n\n"
            f"Provide your final decision: REJECT (no trade) / MODIFY (with changes) / APPROVE (as-is). "
            f"Include specific position sizing and leverage recommendation if approving/modifying."
            f"{get_language_instruction()}"
        )

        response = llm.invoke(prompt)
        final_decision = response.content

        new_risk_debate_state = {
            "judge_decision": final_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_decision,
        }

    return node
