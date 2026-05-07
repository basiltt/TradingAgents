# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        # Pin temperature for deterministic trading signals.
        # Reasoning models (o1/o3/o4-mini etc.) reject temperature — skip for those.
        deep_model = self.config["deep_think_llm"].lower()
        quick_model = self.config["quick_think_llm"].lower()
        _reasoning_prefixes = ("o1", "o3", "o4")

        def _is_reasoning(model: str) -> bool:
            return any(model.startswith(p) for p in _reasoning_prefixes)

        llm_kwargs.pop("temperature", None)

        deep_temp = {} if _is_reasoning(deep_model) else {"temperature": 0}
        quick_temp = {} if _is_reasoning(quick_model) else {"temperature": 0}

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **deep_temp,
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **quick_temp,
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        # Per-agent model overrides: {agent_key: model_id}
        self._agent_llm_cache: dict = {}
        self._agent_model_overrides: dict = self.config.get("agent_model_overrides") or {}
        self._llm_kwargs = llm_kwargs

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            agent_llm_resolver=self._get_agent_llm,
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph based on asset type
        asset_type = self.config.get("asset_type", "stock")
        workflow_mode = self.config.get("workflow_mode", "deep_analysis")

        # Create compliance + execution monitor nodes for both flows
        if workflow_mode == "quick_trade":
            compliance_node = None
            monitor_node = None
        else:
            from tradingagents.agents.compliance import (
                create_compliance_officer,
                create_execution_monitor,
            )
            compliance_node = create_compliance_officer(self._get_agent_llm("compliance_officer", self.quick_thinking_llm))
            monitor_node = create_execution_monitor(self._get_agent_llm("execution_monitor", self.quick_thinking_llm))

        if asset_type == "crypto":
            self.workflow = self._setup_crypto_workflow(
                selected_analysts, compliance_node, monitor_node, workflow_mode,
            )
        else:
            self.workflow = self.graph_setup.setup_graph(
                selected_analysts,
                compliance_officer_node=compliance_node,
                execution_monitor_node=monitor_node,
                workflow_mode=workflow_mode,
            )
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _setup_crypto_workflow(self, selected_analysts, compliance_node=None, monitor_node=None, workflow_mode="deep_analysis"):
        from tradingagents.agents.utils.crypto_agent_utils import make_crypto_tools
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        from tradingagents.agents.crypto_analysts import (
            create_crypto_technical_analyst,
            create_crypto_derivatives_analyst,
            create_crypto_news_analyst,
            create_crypto_fundamentals_analyst,
            create_crypto_social_analyst,
            create_crypto_trader,
            create_crypto_risk_bull_debater,
            create_crypto_risk_bear_debater,
            create_crypto_portfolio_manager,
            create_crypto_bull_researcher,
            create_crypto_bear_researcher,
            create_crypto_research_manager,
            create_confluence_checker,
        )
        from tradingagents.dataflows.bybit_data import BybitRateLimiter, BybitCircuitBreaker

        creds = self.config.get("exchange_credentials", {}).get("bybit", {})
        api_key = creds.get("api_key")
        api_secret = creds.get("api_secret")

        cache: dict = {}
        limiter = BybitRateLimiter()
        cb = BybitCircuitBreaker()

        # Store shared resources so _run_graph can fetch live price context
        self._crypto_shared = {
            "cache": cache, "limiter": limiter, "circuit_breaker": cb,
            "api_key": api_key, "api_secret": api_secret,
        }

        crypto_tools = make_crypto_tools(
            cache=cache, limiter=limiter, circuit_breaker=cb,
            api_key=api_key, api_secret=api_secret,
        )

        max_leverage = self.config.get("crypto_max_leverage", 20)

        analyst_nodes = {}
        tool_nodes = {}

        if "crypto_technical" in selected_analysts:
            analyst_nodes["crypto_technical"] = create_crypto_technical_analyst(
                self._get_agent_llm("crypto_technical", self.quick_thinking_llm), crypto_tools
            )
            tool_nodes["crypto_technical"] = ToolNode(
                [t for t in crypto_tools if t.name in ("get_crypto_klines", "get_crypto_indicators")]
            )

        if "crypto_derivatives" in selected_analysts:
            analyst_nodes["crypto_derivatives"] = create_crypto_derivatives_analyst(
                self._get_agent_llm("crypto_derivatives", self.quick_thinking_llm), crypto_tools
            )
            tool_nodes["crypto_derivatives"] = ToolNode(
                [t for t in crypto_tools if t.name in ("get_funding_rates", "get_open_interest", "get_crypto_ticker")]
            )

        if "crypto_news" in selected_analysts:
            analyst_nodes["crypto_news"] = create_crypto_news_analyst(
                self._get_agent_llm("crypto_news", self.quick_thinking_llm)
            )
            tool_nodes["crypto_news"] = ToolNode([get_news, get_global_news])

        coingecko_tools = make_coingecko_tools()

        if "crypto_fundamentals" in selected_analysts:
            analyst_nodes["crypto_fundamentals"] = create_crypto_fundamentals_analyst(
                self._get_agent_llm("crypto_fundamentals", self.quick_thinking_llm), coingecko_tools
            )
            tool_nodes["crypto_fundamentals"] = ToolNode(
                [t for t in coingecko_tools if t.name == "get_crypto_market_data"]
            )

        if "crypto_social" in selected_analysts:
            analyst_nodes["crypto_social"] = create_crypto_social_analyst(
                self._get_agent_llm("crypto_social", self.quick_thinking_llm), coingecko_tools
            )
            tool_nodes["crypto_social"] = ToolNode(
                [t for t in coingecko_tools if t.name == "get_crypto_community_data"] + [get_news]
            )

        trader_node = create_crypto_trader(self._get_agent_llm("trader", self.quick_thinking_llm), max_leverage=max_leverage)
        bull_debater = create_crypto_risk_bull_debater(self._get_agent_llm("bull_analyst", self.quick_thinking_llm))
        bear_debater = create_crypto_risk_bear_debater(self._get_agent_llm("bear_analyst", self.quick_thinking_llm))
        pm_node = create_crypto_portfolio_manager(self._get_agent_llm("portfolio_manager", self.deep_thinking_llm), max_leverage=max_leverage)
        confluence_node = create_confluence_checker(self._get_agent_llm("confluence_checker", self.quick_thinking_llm))

        bull_researcher = create_crypto_bull_researcher(self._get_agent_llm("bull_researcher", self.quick_thinking_llm))
        bear_researcher = create_crypto_bear_researcher(self._get_agent_llm("bear_researcher", self.quick_thinking_llm))
        research_manager = create_crypto_research_manager(self._get_agent_llm("research_manager", self.deep_thinking_llm))

        return self.graph_setup.setup_crypto_graph(
            selected_analysts=selected_analysts,
            crypto_analyst_nodes=analyst_nodes,
            crypto_tool_nodes=tool_nodes,
            crypto_trader_node=trader_node,
            crypto_bull_debater=bull_debater,
            crypto_bear_debater=bear_debater,
            crypto_portfolio_manager=pm_node,
            confluence_checker_node=confluence_node,
            crypto_bull_researcher=bull_researcher,
            crypto_bear_researcher=bear_researcher,
            crypto_research_manager=research_manager,
            compliance_officer_node=compliance_node,
            execution_monitor_node=monitor_node,
            workflow_mode=workflow_mode,
        )

    def _get_agent_llm(self, agent_key: str, default_llm):
        """Return a per-agent override LLM if configured, else the default.

        Falls back to default_llm on any creation error so a single bad
        override never crashes the entire analysis run.
        """
        model_id = self._agent_model_overrides.get(agent_key)
        if not model_id:
            return default_llm
        logger.info("Applying model override for agent '%s': %s", agent_key, model_id)
        if model_id in self._agent_llm_cache:
            return self._agent_llm_cache[model_id]

        try:
            _reasoning_prefixes = ("o1", "o3", "o4")
            is_reasoning = any(model_id.lower().startswith(p) for p in _reasoning_prefixes)
            temp = {} if is_reasoning else {"temperature": 0}

            # Only pass provider-agnostic kwargs to override clients.
            # Provider-specific keys (thinking_level, reasoning_effort, effort)
            # would break clients for different model families.
            safe_kwargs: Dict[str, Any] = {}
            if "callbacks" in self._llm_kwargs:
                safe_kwargs["callbacks"] = self._llm_kwargs["callbacks"]
            if "api_key" in self._llm_kwargs:
                safe_kwargs["api_key"] = self._llm_kwargs["api_key"]

            client = create_llm_client(
                provider=self.config["llm_provider"],
                model=model_id,
                base_url=self.config.get("backend_url"),
                **temp,
                **safe_kwargs,
            )
            llm = client.get_llm()
            self._agent_llm_cache[model_id] = llm
            return llm
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to create override LLM for agent '%s' (model=%s), "
                "falling back to default",
                agent_key, model_id, exc_info=True,
            )
            return default_llm

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if self.config.get("llm_api_key"):
            kwargs["api_key"] = self.config["llm_api_key"]

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        Returns (raw_return, alpha_return, actual_holding_days) or
        (None, None, None) if price data is unavailable (too recent, delisted,
        or network error).
        """
        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
            spy = yf.Ticker("SPY").history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(spy) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(spy) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            spy_ret = float(
                (spy["Close"].iloc[actual_days] - spy["Close"].iloc[0])
                / spy["Close"].iloc[0]
            )
            alpha = raw - spy_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s (will retry next run): %s",
                ticker, trade_date, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(ticker, entry["date"])
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(self, company_name, trade_date):
        """Run the trading agents graph for a company on a specific date.

        When ``checkpoint_enabled`` is set in config, the graph is recompiled
        with a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        self.ticker = company_name

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(company_name, trade_date)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(self, company_name, trade_date):
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state — inject memory log context for PM.
        past_context = self.memory_log.get_past_context(company_name)
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, past_context=past_context,
            asset_type=self.config.get("asset_type", "stock"),
        )

        # For crypto: fetch live price + lower-timeframe candles BEFORE agents run
        if self.config.get("asset_type") == "crypto" and hasattr(self, "_crypto_shared"):
            from tradingagents.dataflows.bybit_data import build_current_price_context
            try:
                price_ctx = build_current_price_context(company_name, **self._crypto_shared)
            except Exception as exc:
                logger.warning("Failed to fetch current price context for %s: %s", company_name, exc)
                price_ctx = f"Current price data unavailable: {exc}"
            init_agent_state["current_price_context"] = price_ctx
        else:
            init_agent_state["current_price_context"] = ""

        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            final_state = trace[-1]
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        debate = final_state.get("investment_debate_state") or {}
        risk = final_state.get("risk_debate_state") or {}

        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "crypto_fundamentals_report": final_state.get("crypto_fundamentals_report", ""),
            "investment_debate_state": {
                "bull_history": debate.get("bull_history", ""),
                "bear_history": debate.get("bear_history", ""),
                "history": debate.get("history", ""),
                "current_response": debate.get("current_response", ""),
                "judge_decision": debate.get("judge_decision", ""),
            },
            "trader_investment_decision": final_state.get("trader_investment_plan", ""),
            "risk_debate_state": {
                "aggressive_history": risk.get("aggressive_history", ""),
                "conservative_history": risk.get("conservative_history", ""),
                "neutral_history": risk.get("neutral_history", ""),
                "history": risk.get("history", ""),
                "judge_decision": risk.get("judge_decision", ""),
            },
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
