# TradingAgents Codebase Discovery Report

**Generated:** 2026-05-02  
**Scope:** Multi-agent stock analysis system with Python backend and React frontend

---

## 1. OVERALL ARCHITECTURE

### High-Level Data Flow

User Request (Frontend)
    ↓
FastAPI Backend (REST + WebSocket)
    ↓
AnalysisService (Lifecycle Management)
    ↓
TradingAgentsGraph (LangGraph Orchestration)
    ↓
[Parallel Analyst Agents] → Bull/Bear Researchers → Research Manager
    ↓
Trader Agent → Risk Managers (Aggressive/Neutral/Conservative Debators)
    ↓
Portfolio Manager → Final Decision
    ↓
Report + Memory Log + Results Storage
    ↓
Frontend (Real-time WebSocket Updates + Report Display)

### Directory Structure (Main Components)

Key directories:
- tradingagents/agents/ - Multi-agent system (analysts, managers, researchers, risk_mgmt, trader, utils)
- tradingagents/dataflows/ - Data vendor abstraction (yfinance, alpha_vantage implementations)
- tradingagents/graph/ - LangGraph orchestration (trading_graph.py, setup.py, conditional_logic.py, checkpointer.py, reflection.py, propagation.py, signal_processing.py)
- tradingagents/llm_clients/ - Multi-provider LLM abstraction (factory.py, model_catalog.py, openai_client.py, anthropic_client.py, google_client.py, azure_client.py, base_client.py)
- backend/ - FastAPI application (main.py, routers/, services/, schemas.py, persistence.py, event_bus.py, ws_manager.py, callbacks.py, stream_parser.py)
- frontend/src/ - React + TypeScript (components/analysis/, components/config/, api/client.ts, hooks/)
- cli/ - CLI interface
- tests/ - Test suite (30+ files)

---

## 2. DATA PROVIDERS & VENDOR CONFIGURATION

### Supported Data Vendors

- yfinance (Yahoo Finance) - Default, free tier
- alpha_vantage (Alpha Vantage API) - Requires API key

### Configuration System

File: tradingagents/default_config.py

data_vendors configuration:
- core_stock_apis: OHLCV data (default: yfinance)
- technical_indicators: Technical analysis (default: yfinance)
- fundamental_data: Company financials (default: yfinance)
- news_data: News & insider info (default: yfinance)

tool_vendors: Tool-level override (takes precedence over categories)

### Data Vendor Abstraction

File: tradingagents/dataflows/interface.py

Routing logic:
- get_vendor(category, method=None) - checks tool-level config, falls back to category
- route_to_vendor(method, *args, **kwargs) - calls appropriate vendor impl, falls back on rate limit errors

VENDOR_METHODS maps methods to implementations by vendor:
- get_stock_data: alpha_vantage or yfinance
- get_indicators: alpha_vantage or yfinance
- get_fundamentals: alpha_vantage or yfinance
- get_balance_sheet: alpha_vantage or yfinance
- get_cashflow: alpha_vantage or yfinance
- get_income_statement: alpha_vantage or yfinance
- get_news: alpha_vantage or yfinance
- get_global_news: alpha_vantage or yfinance
- get_insider_transactions: alpha_vantage or yfinance

### Data Fetching Files

File | Vendor | Data Type
y_finance.py | Yahoo Finance | OHLCV, Fundamentals, News
yfinance_news.py | Yahoo Finance | News extraction
alpha_vantage_stock.py | Alpha Vantage | OHLCV data
alpha_vantage_indicator.py | Alpha Vantage | Technical indicators
alpha_vantage_fundamentals.py | Alpha Vantage | Company fundamentals
alpha_vantage_news.py | Alpha Vantage | News & insider data

---

## 3. LANGGRAPH TRADING GRAPH STRUCTURE

### Main Class: tradingagents/graph/trading_graph.py

TradingAgentsGraph.__init__()
- selected_analysts: ["market", "social", "news", "fundamentals"]
- debug: Boolean
- config: Configuration dict
- callbacks: Optional callback handlers

Key components:
- deep_thinking_llm - Strategic decision-making
- quick_thinking_llm - Quick analysis
- memory_log - TradingMemoryLog instance
- tool_nodes - Dict[str, ToolNode] by analyst type
- workflow - LangGraph StateGraph
- conditional_logic - Debate routing and flow control
- graph_setup - GraphSetup orchestrator

### Graph Structure: tradingagents/graph/setup.py

GraphSetup.setup_graph() creates execution flow:

1. **Analyst Nodes** (parallel execution):
   - Market Analyst (tools: get_stock_data, get_indicators)
   - Social Media Analyst (tools: get_news)
   - News Analyst (tools: get_news, get_global_news, get_insider_transactions)
   - Fundamentals Analyst (tools: get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement)

2. **Research Phase**:
   - Bull Researcher (reads analyst reports, bullish perspective)
   - Bear Researcher (reads analyst reports, bearish perspective)
   - Research Manager (structured ResearchPlan output)

3. **Trading Phase**:
   - Trader (structured TraderProposal output)

4. **Risk Management Phase**:
   - Aggressive Debator (bullish risk perspective)
   - Neutral Debator (balanced risk view)
   - Conservative Debator (bearish risk perspective)
   - Portfolio Manager (final PortfolioDecision output)

### Conditional Logic: tradingagents/graph/conditional_logic.py

Routes based on:
- Debate round limits (max_debate_rounds, max_risk_discuss_rounds)
- Recursion limit enforcement (max_recur_limit)
- Tool call routing
- Stop signal detection ("FINAL TRANSACTION PROPOSAL")

---

## 4. ANALYST TYPES & IMPLEMENTATION

File: backend/schemas.py

class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"

### Analyst Implementations

Analyst | File | Tools | Purpose
Market | agents/analysts/market_analyst.py | get_stock_data, get_indicators | Technical analysis
Social | agents/analysts/social_media_analyst.py | get_news | Social sentiment
News | agents/analysts/news_analyst.py | get_news, get_global_news, get_insider_transactions | News & insiders
Fundamentals | agents/analysts/fundamentals_analyst.py | get_fundamentals, balance sheet, cashflow, income statement | Financials

### Agent State

File: tradingagents/agents/utils/agent_states.py

class AgentState includes:
- messages: Conversation history
- trade_date: Analysis date
- company_of_interest: Ticker symbol
- market_report, social_report, news_report, fundamentals_report: Analyst outputs
- bull_research, bear_research: Researcher outputs
- investment_plan: ResearchPlan (structured)
- trader_proposal: TraderProposal (structured)
- aggressive_risk_view, neutral_risk_view, conservative_risk_view: Risk debater outputs
- final_decision: PortfolioDecision (structured)
- debate_round, risk_discuss_round, recursion_count: Flow control

---

## 5. STRUCTURED OUTPUT SCHEMAS

File: tradingagents/agents/schemas.py

### ResearchPlan (Research Manager Output)

class ResearchPlan:
    recommendation: PortfolioRating (Buy/Overweight/Hold/Underweight/Sell)
    rationale: str (Key points from both sides + final reasoning)
    strategic_actions: str (Concrete steps for trader)

### TraderProposal (Trader Output)

class TraderProposal:
    action: TraderAction (Buy/Hold/Sell)
    reasoning: str (Case for this action, 2-4 sentences)
    entry_price: Optional[float] (Entry target)
    stop_loss: Optional[float] (Stop-loss level)
    position_sizing: Optional[str] (e.g., "5% of portfolio")

### PortfolioDecision (Portfolio Manager Output)

class PortfolioDecision:
    rating: PortfolioRating (Final position rating)
    executive_summary: str (Action plan, 2-4 sentences)
    investment_thesis: str (Detailed reasoning)
    price_target: Optional[float] (Target price)
    time_horizon: Optional[str] (e.g., "3-6 months")

Note: Structured output uses provider-native formatting:
- OpenAI/xAI: json_schema
- Google/Gemini: response_schema
- Anthropic: Tool-use mode

---

## 6. CONFIGURATION SYSTEM

File: tradingagents/default_config.py

Key configuration keys:
- llm_provider: LLM provider (openai, anthropic, google, xai, deepseek, qwen, glm, azure, ollama)
- deep_think_llm: Deep reasoning model
- quick_think_llm: Quick analysis model
- output_language: Report language
- max_debate_rounds: Bull/bear debate iterations
- max_risk_discuss_rounds: Risk debater iterations
- checkpoint_enabled: Resume capability
- data_vendors: Vendor routing by category
- backend_url: Custom LLM backend URL
- google_thinking_level, openai_reasoning_effort, anthropic_effort: Provider-specific thinking config

### Request-Level Overrides

File: backend/schemas.py

class AnalysisRequest:
    ticker: str (required)
    analysis_date: str (required, YYYY-MM-DD, not in future)
    provider: Optional[str] (override)
    deep_think_llm: Optional[str]
    quick_think_llm: Optional[str]
    backend_url: Optional[str]
    analysts: Optional[List[AnalystType]]
    research_depth: Optional[int] (1-5)
    output_language: Optional[str]
    data_vendors: Optional[Dict[str, str]]

---

## 7. FRONTEND ANALYSIS FORM

File: frontend/src/components/analysis/ConfigForm.tsx

### Form Fields

FormValues interface:
- ticker: string (regex: ^[A-Z0-9.\-^]{1,15}$)
- analysis_date: string (ISO date)
- provider: string (LLM provider selection)
- backend_url: string (custom backend URL)
- deep_think_llm, quick_think_llm: string (model selectors)
- analysts: string[] (checkboxes for market/social/news/fundamentals)
- research_depth: number (1-5 slider)
- output_language: string (dropdown)
- max_debate_rounds, max_risk_discuss_rounds, max_recur_limit: number
- checkpoint_enabled: boolean
- data_vendor_core, data_vendor_technical, data_vendor_fundamental, data_vendor_news: string

### Features

- Settings persistence (localStorage under "tradingagents_settings")
- Dynamic model catalog fetched per provider
- Connectivity check indicator
- Collapsible advanced sections (LLM, Workflow, Data Vendors)
- Real-time validation + error display
- Submit button with loading state

---

## 8. API SCHEMAS & ENDPOINTS

File: backend/schemas.py

### Request/Response Models

- AnalysisRequest - Input validation
- AnalysisCreateResponse - Returns run_id + status
- AnalysisResponse - Full run metadata
- AnalysisListItem, AnalysisListResponse - Paginated results
- ConfigResponse - Merged config view (defaults, overrides, resolved)
- ConfigUpdateRequest - Config override payload
- MemoryEntry, MemoryListResponse - Memory management
- CheckpointResponse - Checkpoint status
- ErrorResponse - Error details with code

### API Endpoints

POST /api/v1/analysis - Start analysis (returns run_id)
GET /api/v1/analysis - List analyses (paginated, filterable by ticker/status/date)
GET /api/v1/analysis/{run_id} - Get analysis metadata
GET /api/v1/analysis/{run_id}/report - Download markdown report
GET /api/v1/analysis/{run_id}/snapshot - Get final decision JSON
DELETE /api/v1/analysis/{run_id} - Delete analysis
PATCH /api/v1/analysis/{run_id}/cancel - Cancel running analysis
GET /api/v1/config - Get current config
PATCH /api/v1/config - Update config overrides
GET /api/v1/models - Get model catalog by provider
GET /api/v1/memory - List memory log entries
PATCH /api/v1/memory - Resolve/update memory entry
GET /api/v1/checkpoints/{ticker}/{date} - Get checkpoint status
DELETE /api/v1/checkpoints/{ticker}/{date} - Delete checkpoint
WS /ws/{run_id} - WebSocket for real-time updates

---

## 9. LLM PROVIDER CATALOG

File: tradingagents/llm_clients/model_catalog.py

### Supported Providers

openai: GPT-5.4, GPT-5.2, GPT-4.1, GPT-5.4-mini, GPT-5.4-nano (quick/deep modes)
anthropic: Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 (quick/deep modes)
google: Gemini 3.1 Pro, Gemini 3 Flash, Gemini 2.5 Pro/Flash (quick/deep modes)
xai: Grok 4, Grok 4.1, Grok 4 Fast (quick/deep modes)
deepseek: DeepSeek V4, V3.2 (quick/deep modes, reasoning support)
qwen: Qwen 3.x, Qwen Plus (quick/deep modes)
glm: GLM-5.x, GLM-4.7 (quick/deep modes)
ollama: Local models (Qwen3, GPT-OSS, GLM-4.7-Flash)

### Client Implementations

Provider | File | Special Args
OpenAI | openai_client.py | reasoning_effort (low/medium/high)
Anthropic | anthropic_client.py | effort (low/medium/high) for extended thinking
Google | google_client.py | thinking_level (high/minimal)
Azure | azure_client.py | azure_endpoint, api_version
Others | openai_client.py (compatible APIs) | Standard LLM interface

---

## 10. BACKEND ARCHITECTURE DETAILS

### Analysis Service Lifecycle

File: backend/services/analysis_service.py

class AnalysisService:
    async def start_analysis(request):
        1. Check concurrency (max 3 concurrent)
        2. Generate UUID run_id
        3. Build resolved config
        4. Insert DB record with "running" status
        5. Spawn async task (30min wall, 35min hard timeout)
        6. Return run_id immediately
    
    async def _run_analysis(run_id, request, config):
        1. Initialize TradingAgentsGraph with config
        2. Invoke graph.run(ticker, date)
        3. Stream results to WebSocket via event_bus.emit()
        4. Parse stream chunks into agent_status, progress, sections
        5. Save sections to DB (market_report, news_report, ..., final_decision)
        6. Update DB run record to "completed" or "failed"

Concurrency Control:
- Max concurrent: 3 (configurable)
- Wall timeout: 30 min
- Hard timeout: 35 min
- Zombie thread tracking: max 3

### Persistence Layer

File: backend/persistence.py

class AnalysisDB (SQLite):
    runs table: (run_id, ticker, analysis_date, status, config, started_at, completed_at, error)
    report_sections table: (run_id, section, content)
    
    Sections: market_report, social_report, news_report, fundamentals_report,
              bull_research, bear_research, investment_plan, trader_proposal,
              risk_views, final_decision, _snapshot (JSON)

---

## 11. MEMORY & LEARNING

### Memory Log

File: tradingagents/agents/utils/memory.py

class TradingMemoryLog:
    get_pending_entries() - Returns entries awaiting outcome (< 5 days old)
    record_decision(ticker, date, decision, confidence, reasoning) - New entry
    resolve_entry(ticker, date, raw_return, alpha_return, reflection) - Update with outcome
    rotate_if_needed() - Prune oldest resolved if > max_entries

### Reflection System

File: tradingagents/graph/reflection.py

class Reflector:
    reflect_on_final_decision(final_decision, raw_return, alpha_return)
    - Uses LLM to generate lesson learned from outcome
    - Returns reflection text for memory log

---

## 12. TEST STRUCTURE

Location: tests/ (30+ test files)

### Backend Tests (pytest)

tests/backend/
- conftest.py - Shared fixtures
- test_main.py - App initialization
- test_schemas.py - Pydantic validation
- test_persistence.py - Database layer
- test_event_bus.py - Event broadcasting
- test_ws_manager.py - WebSocket management
- test_callbacks.py - LangGraph callbacks
- test_stream_parser.py - Stream parsing logic
- test_analysis_service.py - Analysis lifecycle
- test_analysis_router.py - API endpoints
- test_router_*.py - Router-specific tests
- test_config_service.py - Config merging
- test_memory_service.py - Memory log access
- test_validators.py - Input validation

### Integration Tests

tests/
- conftest.py - Shared fixtures
- test_checkpoint_resume.py - Checkpoint/resume flow
- test_deepseek_reasoning.py - DeepSeek extended thinking
- test_google_api_key.py - Google provider integration
- test_memory_log.py - Memory log functionality
- test_model_validation.py - Model catalog validation
- test_safe_ticker_component.py - Ticker sanitization
- test_signal_processing.py - Signal extraction
- test_structured_agents.py - Structured output validation
- test_ticker_symbol_handling.py - Multi-exchange tickers

---

## 13. KEY UTILITIES

### Agent Utils

File: tradingagents/agents/utils/agent_utils.py

Exported tools:
- get_stock_data(symbol, start_date, end_date) - Returns CSV OHLCV
- get_indicators(symbol, indicator, curr_date, look_back_days) - Technical analysis
- get_fundamentals(symbol) - P/E, PEG, market cap, etc.
- get_balance_sheet(symbol) - Assets, liabilities, equity
- get_cashflow(symbol) - Operating, investing, financing CF
- get_income_statement(symbol) - Revenue, EBIT, net income
- get_news(symbol, days_back) - News articles
- get_global_news(symbol, days_back) - Global news
- get_insider_transactions(symbol, limit) - Insider trades

Helper functions:
- get_language_instruction() - Returns language prompt instruction
- build_instrument_context(ticker) - Builds ticker description
- create_msg_delete() - Clears conversation messages

### Dataflow Utils

File: tradingagents/dataflows/utils.py

- safe_ticker_component(ticker) - Sanitize for file paths
- yf_retry(func, max_retries=3) - Retry with exponential backoff
- load_ohlcv(ticker, start_date, end_date) - Load OHLCV data
- filter_financials_by_date(...) - Date-filtered financial data

---

## 14. ENVIRONMENT VARIABLES

### Required (depending on provider)

OPENAI_API_KEY - OpenAI provider
ANTHROPIC_API_KEY - Anthropic provider
GOOGLE_API_KEY - Google provider
XAI_API_KEY - xAI (Grok) provider
DEEPSEEK_API_KEY - DeepSeek provider
DASHSCOPE_API_KEY - Qwen provider
ZHIPU_API_KEY - GLM provider
OPENROUTER_API_KEY - OpenRouter provider
AZURE_OPENAI_API_KEY - Azure provider
ALPHA_VANTAGE_API_KEY - Alpha Vantage data vendor

### Configuration (Optional)

TRADINGAGENTS_RESULTS_DIR - Results storage path (default: ~/.tradingagents/logs)
TRADINGAGENTS_CACHE_DIR - Cache directory (default: ~/.tradingagents/cache)
TRADINGAGENTS_MEMORY_LOG_PATH - Memory log file (default: ~/.tradingagents/memory/trading_memory.md)
TRADINGAGENTS_LLM_PROVIDER - Default provider (default: openai)
TRADINGAGENTS_DEEP_THINK_LLM - Deep model (default: gpt-5.4)
TRADINGAGENTS_QUICK_THINK_LLM - Quick model (default: gpt-5.4-mini)
TRADINGAGENTS_BACKEND_URL - Custom backend URL (default: None)

### Backend/Web Configuration

WEB_CORS_ORIGIN - CORS origin (default: http://localhost:5177)
WEB_CSP_CONNECT_SRC - CSP connect-src (default: 'self' ws://localhost:8877)
TRADINGAGENTS_WEB_DB_PATH - Web DB path (default: ~/.tradingagents/cache/web_runs.db)

---

## 15. KEY TAKEAWAYS

### Architecture Highlights

1. Multi-Layered Agent System: Analysts → Researchers → Manager → Trader → Risk Debaters → Portfolio Manager
2. Pluggable Data Vendors: Route via abstraction layer (yfinance or Alpha Vantage)
3. Multi-Provider LLM Support: 9 providers with structured output support
4. Real-Time Frontend: React + WebSocket for live agent status
5. Structured Output: Pydantic schemas with provider-native formatting
6. Memory & Learning: Auto-resolve pending entries with outcomes + LLM reflection
7. Checkpoint/Resume: Optional state persistence for fault tolerance
8. Concurrency Control: Max 3 concurrent, 30min wall timeout
9. Comprehensive Testing: 30+ test files covering backend APIs and integration

### Data Flow

Form Input (ConfigForm.tsx)
  ↓ POST /api/v1/analysis
AnalysisService.start_analysis()
  ↓ spawn async task
TradingAgentsGraph.run()
  ↓ LangGraph StateGraph execution
Parallel Analysts + Researchers + Managers + Risk Debaters
  ↓ Tool calls
Data Vendor (yfinance or Alpha Vantage)
  ↓ Results streamed
Stream Parser (backend/stream_parser.py)
  ↓ Events emitted
EventBus (broadcast to WebSocket)
  ↓ Real-time updates
AnalysisDashboard.tsx
  ↓ on completion
Report saved to DB + memory updated

### Configuration Hierarchy

1. Default Config (tradingagents/default_config.py) - lowest priority
2. Environment Variables (TRADINGAGENTS_*)
3. Persisted Config (backend/services/config_service.py)
4. Request Overrides (AnalysisRequest fields) - highest priority
→ Resolved Config (used for this analysis)

---

**Report Complete**
