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
)

logger = logging.getLogger(__name__)

_ANALYST_SYSTEM_PREFIX = (
    "You are a helpful AI assistant, collaborating with other assistants."
    " Use the provided tools to progress towards answering the question."
    " If you are unable to fully answer, that's OK; another assistant with different tools"
    " will help where you left off. Execute what you can to make progress."
    " If you or any other assistant has the FINAL ANALYSIS or deliverable,"
    " prefix your response with FINAL ANALYSIS so the team knows to stop."
    " You have access to the following tools: {tool_names}.\n{system_message}"
    "For your reference, the current date is {current_date}. {instrument_context}"
)


def create_crypto_technical_analyst(llm, crypto_tools: list):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        tools = [t for t in crypto_tools if t.name in ("get_crypto_klines", "get_crypto_indicators")]
        assert tools, "No technical analysis tools found in crypto_tools"

        system_message = (
            "You are a crypto futures technical analyst. Analyze OHLCV price data and "
            "technical indicators (RSI, MACD, Bollinger Bands, EMA) for the given perpetual "
            "futures contract. Identify trends, support/resistance levels, momentum signals, "
            "and potential entry/exit zones. Include the current price and data timestamp in "
            "your report. Call get_crypto_klines first, then get_crypto_indicators."
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
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = result.content if not result.tool_calls else ""
        return {"messages": [result], "market_report": report}

    return node


def create_crypto_derivatives_analyst(llm, crypto_tools: list):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        tools = [t for t in crypto_tools if t.name in ("get_funding_rates", "get_open_interest", "get_crypto_ticker")]
        assert tools, "No derivatives tools found in crypto_tools"

        system_message = (
            "You are a crypto derivatives analyst. Analyze funding rates, open interest "
            "trends, and ticker data for the given perpetual futures contract. Assess "
            "funding cost impact on position holding, OI trends as a proxy for market "
            "sentiment and potential liquidation cascades, and current market snapshot. "
            "If any data source is unavailable, acknowledge it and continue with available data."
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
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = result.content if not result.tool_calls else ""
        return {"messages": [result], "fundamentals_report": report}

    return node


def create_crypto_news_analyst(llm):
    def node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        tools = [get_news, get_global_news]

        system_message = (
            "You are a crypto news analyst. Research recent news relevant to the given "
            "cryptocurrency futures contract. Search for the coin name (e.g. 'Bitcoin', "
            "'Ethereum'), related futures/derivatives news, and broader crypto market events. "
            "Use get_news for targeted searches and get_global_news for macro context. "
            "Write a comprehensive report with a Markdown summary table at the end."
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
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = result.content if not result.tool_calls else ""
        return {"messages": [result], "news_report": report}

    return node


def create_crypto_trader(llm, max_leverage: int = 20):
    signal_schema_str = json.dumps(SIGNAL_SCHEMA, indent=2)

    def node(state):
        company = state["company_of_interest"]
        instrument_context = build_instrument_context(company)
        investment_plan = state["investment_plan"]

        base_prompt = (
            f"You are a crypto futures trader. Based on the analyst reports and research plan, "
            f"produce a structured trading signal for {company}. {instrument_context}\n\n"
            f"You MUST output a JSON object matching this schema:\n{signal_schema_str}\n\n"
            f"Research plan: {investment_plan}\n\n"
            f"Output ONLY the JSON inside a ```json``` code block."
        )

        messages = [{"role": "user", "content": base_prompt}]
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

            ok, errors = validate_signal(parsed, max_leverage=max_leverage)
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
        trader_decision = state["trader_investment_plan"]
        market_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        bear_response = risk_debate_state.get("current_conservative_response", "")

        prompt = (
            f"As the Bullish Risk Analyst for crypto futures, argue in favor of the "
            f"trader's position. Consider leverage management, funding rate costs, and "
            f"liquidation risk — but emphasize upside potential and risk-reward ratio.\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"Market report: {market_report}\n"
            f"News report: {news_report}\n"
            f"Derivatives report: {fundamentals_report}\n"
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
        trader_decision = state["trader_investment_plan"]
        market_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        bull_response = risk_debate_state.get("current_aggressive_response", "")

        prompt = (
            f"As the Bearish Risk Analyst for crypto futures, critically examine the "
            f"trader's position. Focus on liquidation risk at the proposed leverage, "
            f"funding rate costs eroding profits, exchange counterparty risk, and "
            f"market volatility.\n\n"
            f"Trader's decision: {trader_decision}\n"
            f"Market report: {market_report}\n"
            f"News report: {news_report}\n"
            f"Derivatives report: {fundamentals_report}\n"
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
        history = state["risk_debate_state"]["history"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]
        risk_debate_state = state["risk_debate_state"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions:\n{past_context}\n" if past_context else ""
        )

        prompt = (
            f"As the Crypto Futures Portfolio Manager, synthesize the risk debate and "
            f"deliver the final trading decision.\n\n"
            f"{instrument_context}\n\n"
            f"Max allowed leverage: {max_leverage}x\n\n"
            f"Research plan: {research_plan}\n"
            f"Trader's signal: {trader_plan}\n"
            f"{lessons_line}"
            f"Risk debate history:\n{history}\n\n"
            f"Provide your final decision: approve/modify/reject the trade with specific "
            f"position sizing and leverage recommendation.{get_language_instruction()}"
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
