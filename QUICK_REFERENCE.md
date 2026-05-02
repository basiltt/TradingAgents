# TradingAgents - Quick Reference Summary

## System Overview
A multi-agent stock analysis system featuring:
- **Backend:** FastAPI + LangGraph orchestration
- **Frontend:** React + TypeScript with real-time WebSocket updates
- **Data Vendors:** Yahoo Finance (yfinance) + Alpha Vantage (pluggable)
- **LLM Support:** 9 providers (OpenAI, Anthropic, Google, xAI, DeepSeek, Qwen, GLM, Azure, Ollama)

## Entry Points

### Frontend Analysis Form
**File:** rontend/src/components/analysis/ConfigForm.tsx

Form collects:
1. **Required:** ticker, analysis_date
2. **LLM Config:** provider, backend_url, deep_think_llm, quick_think_llm
3. **Workflow:** analysts (market/social/news/fundamentals), research_depth, output_language, debate rounds
4. **Data Vendors:** core_stock_apis, technical_indicators, fundamental_data, news_data vendors

Submits to: POST /api/v1/analysis

### Backend Analysis Endpoint
**File:** ackend/routers/analysis.py

`python
@router.post("/analysis")
async def start_analysis(request: Request, body: AnalysisRequest):
    # Validates input (ticker format, date not in future, provider exists)
    # Checks concurrency (max 3 concurrent)
    # Generates UUID run_id
    # Spawns background TradingAgentsGraph task
    # Returns {"run_id": "...", "status": "running"}
`

## Analyst Agent Flow

**File:** 	radingagents/graph/setup.py

### Parallel Execution (Step 1)
Four analyst agents run in parallel:
1. **Market Analyst** - Technical analysis using get_stock_data + get_indicators
2. **Social Analyst** - Sentiment analysis using get_news
3. **News Analyst** - Events using get_news + get_global_news + get_insider_transactions
4. **Fundamentals Analyst** - Financials using get_fundamentals, balance sheet, cashflow, income statement

### Bull vs Bear Research (Step 2)
- **Bull Researcher** - Bullish case from analyst reports
- **Bear Researcher** - Bearish counterargument
- **Research Manager** - Synthesizes into structured ResearchPlan (recommendation + rationale + strategic_actions)

### Trading Decision (Step 3)
- **Trader** - Converts plan to TraderProposal (action: Buy/Hold/Sell, entry_price, stop_loss, position_sizing)

### Risk Management (Step 4)
- **Aggressive/Neutral/Conservative Debators** - Debate risk aspects
- **Portfolio Manager** - Final PortfolioDecision (rating, executive_summary, investment_thesis, price_target, time_horizon)

## Data Vendor Routing

**File:** 	radingagents/dataflows/interface.py

Configuration-driven routing:
`python
get_vendor(category, method) -> vendor_name
route_to_vendor(method, *args, **kwargs) -> result
`

Priority order:
1. Tool-level config: config["tool_vendors"]["get_stock_data"]
2. Category-level config: config["data_vendors"]["core_stock_apis"]
3. Fallback: Try next available vendor on rate limit error

Supported methods by category:
- **core_stock_apis:** get_stock_data
- **technical_indicators:** get_indicators
- **fundamental_data:** get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement
- **news_data:** get_news, get_global_news, get_insider_transactions

## Configuration Hierarchy

Resolved at runtime in order of precedence:
1. **Default** 	radingagents/default_config.py
2. **Environment Variables** TRADINGAGENTS_* + provider keys
3. **Persisted Overrides** stored in web database
4. **Request Fields** AnalysisRequest object

Example:
`python
config = DEFAULT_CONFIG
config.update(env_overrides)
config.update(db_persisted_config)
config.update(request_overrides)  # Highest priority
`

## Structured Output Schemas

All structured outputs use Pydantic models with provider-native formatting:

### ResearchPlan
`python
recommendation: PortfolioRating  # Buy/Overweight/Hold/Underweight/Sell
rationale: str                   # Summary of debate
strategic_actions: str           # Trader instructions
`

### TraderProposal
`python
action: TraderAction             # Buy/Hold/Sell
reasoning: str                   # 2-4 sentence case
entry_price: Optional[float]     # Entry target
stop_loss: Optional[float]       # Stop-loss level
position_sizing: Optional[str]   # e.g., "5% of portfolio"
`

### PortfolioDecision
`python
rating: PortfolioRating          # Final rating
executive_summary: str           # 2-4 sentence action plan
investment_thesis: str           # Detailed reasoning
price_target: Optional[float]    # Target price
time_horizon: Optional[str]      # e.g., "3-6 months"
`

## LLM Providers

**File:** 	radingagents/llm_clients/model_catalog.py

All providers offer "quick" and "deep" thinking modes:

`
OpenAI:        GPT-5.4 (frontier), GPT-5.2, GPT-4.1, GPT-5.4-mini
Anthropic:     Claude Opus 4.6, Sonnet 4.6, Haiku 4.5
Google:        Gemini 3.1 Pro, Gemini 3 Flash, Gemini 2.5 Pro/Flash
xAI:           Grok 4, Grok 4.1, Grok 4 Fast
DeepSeek:      V4 Pro, V3.2 (with extended thinking)
Qwen:          3.6 Plus, 3.5 Plus/Flash
GLM:           5.1, 5, 4.7
Azure:         Any Azure-deployed model
Ollama:        Local inference (Qwen, GPT-OSS, GLM-4.7-Flash)
`

Provider-specific thinking config:
- OpenAI: easoning_effort (low/medium/high)
- Anthropic: ffort (low/medium/high)
- Google: 	hinking_level (high/minimal)

## Backend Architecture

### Concurrency Control
- Max concurrent analyses: 3 (configurable)
- Wall timeout: 30 minutes
- Hard timeout: 35 minutes
- Zombie thread tracking: max 3

### Persistence
**File:** ackend/persistence.py

SQLite database with two tables:
- **runs:** analysis metadata (run_id, ticker, status, config, timestamps)
- **report_sections:** report content by section (market_report, news_report, investment_plan, final_decision, etc.)

### Real-time Streaming
**File:** ackend/event_bus.py + ackend/stream_parser.py

1. LangGraph emits stream chunks
2. StreamParser converts to typed events (AgentStatusEvent, ProgressEvent, SectionEvent)
3. EventBus broadcasts to WebSocket clients
4. AnalysisDashboard.tsx renders real-time updates

## API Endpoints Summary

`
POST   /api/v1/analysis                    - Start analysis → run_id
GET    /api/v1/analysis                    - List (paginated, filterable)
GET    /api/v1/analysis/{run_id}           - Get metadata
GET    /api/v1/analysis/{run_id}/report    - Download markdown report
GET    /api/v1/analysis/{run_id}/snapshot  - Get final decision JSON
DELETE /api/v1/analysis/{run_id}           - Delete analysis
PATCH  /api/v1/analysis/{run_id}/cancel    - Cancel running analysis

GET    /api/v1/config                      - Get current config
PATCH  /api/v1/config                      - Update config

GET    /api/v1/models                      - Get model options by provider
GET    /api/v1/memory                      - List memory entries
GET    /api/v1/checkpoints/{ticker}/{date} - Checkpoint status

WS     /ws/{run_id}                        - Real-time updates
`

## Memory & Learning

**File:** 	radingagents/agents/utils/memory.py

Markdown-based memory log tracks decisions:
`markdown
## APPL 2024-01-15
- **Decision:** Buy
- **Confidence:** High
- **Status:** Pending (awaiting outcome)
- **Reasoning:** [rationale]

---

## APPL 2024-01-08
- **Decision:** Hold
- **Confidence:** Medium
- **Status:** Resolved
- **Outcome:** Raw +3.2%, Alpha +1.5%
- **Reflection:** [LLM-generated lesson]
`

Auto-resolution on next run:
1. Fetch price data for pending entry
2. Calculate raw return and alpha (vs SPY)
3. Generate LLM reflection
4. Mark as resolved

## Testing

**Location:** 	ests/ (30+ files)

Coverage includes:
- Backend routers, services, persistence, events, WebSocket
- Pydantic schema validation
- Stream parsing, callbacks, config merging
- Integration: checkpoints, DeepSeek reasoning, provider tests
- Agent: structured output, memory log, ticker handling

## File Paths - Key Components

Core Agent System:
- Analysts: 	radingagents/agents/analysts/*.py (4 analyst types)
- Managers: 	radingagents/agents/managers/*.py (research + portfolio managers)
- Researchers: 	radingagents/agents/researchers/*.py (bull + bear researchers)
- Risk Mgmt: 	radingagents/agents/risk_mgmt/*.py (3 debator types)
- Trader: 	radingagents/agents/trader/trader.py
- Utils: 	radingagents/agents/utils/*.py (tools, memory, state definitions)

Data Fetching:
- Interface: 	radingagents/dataflows/interface.py (routing layer)
- Yahoo Finance: 	radingagents/dataflows/y_finance.py + yfinance_news.py
- Alpha Vantage: 	radingagents/dataflows/alpha_vantage*.py (5 modules)
- Config: 	radingagents/dataflows/config.py (data vendor config management)

Graph Orchestration:
- Main: 	radingagents/graph/trading_graph.py
- Setup: 	radingagents/graph/setup.py
- Routing: 	radingagents/graph/conditional_logic.py
- Checkpointing: 	radingagents/graph/checkpointer.py
- Learning: 	radingagents/graph/reflection.py

LLM Clients:
- Factory: 	radingagents/llm_clients/factory.py
- Catalog: 	radingagents/llm_clients/model_catalog.py
- OpenAI: 	radingagents/llm_clients/openai_client.py
- Anthropic: 	radingagents/llm_clients/anthropic_client.py
- Google: 	radingagents/llm_clients/google_client.py

Backend API:
- Main app: ackend/main.py (FastAPI + middleware)
- Routers: ackend/routers/*.py (6 routers: analysis, config, models, memory, checkpoints, ws)
- Services: ackend/services/*.py (analysis lifecycle, config merging, memory access)
- Schemas: ackend/schemas.py (Pydantic validation)
- Persistence: ackend/persistence.py (SQLite abstraction)

Frontend:
- Main form: rontend/src/components/analysis/ConfigForm.tsx
- Dashboard: rontend/src/components/analysis/AnalysisDashboard.tsx
- API client: rontend/src/api/client.ts
- WebSocket hook: rontend/src/hooks/useAnalysisWebSocket.ts

## Default Configuration

**File:** 	radingagents/default_config.py

`python
DEFAULT_CONFIG = {
    "project_dir": auto-detected,
    "results_dir": ~/.tradingagents/logs,
    "data_cache_dir": ~/.tradingagents/cache,
    "memory_log_path": ~/.tradingagents/memory/trading_memory.md,
    
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "backend_url": None,
    
    "checkpoint_enabled": False,
    "output_language": "English",
    
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    },
    "tool_vendors": {},  # Tool-level overrides
}
`

## Quick Start Reference

1. **Form Submission:**
   - Fill ConfigForm.tsx with ticker, date, provider, analysts selection
   - Optional: Override LLM models, data vendors, language, debate settings
   - Submit → POST /api/v1/analysis

2. **Backend Processing:**
   - Validate input (Pydantic schemas)
   - Check concurrency limit
   - Spawn TradingAgentsGraph task
   - Return run_id immediately

3. **Agent Execution:**
   - Parallel analysts fetch data via route_to_vendor()
   - Bull/bear researchers synthesize reports
   - Research manager produces structured ResearchPlan
   - Trader produces structured TraderProposal
   - Risk debaters discuss
   - Portfolio manager produces final PortfolioDecision

4. **Real-time Updates:**
   - Stream parser converts LangGraph chunks to events
   - EventBus broadcasts via WebSocket
   - Frontend AnalysisDashboard renders progress

5. **Completion:**
   - Report saved to DB (report_sections table)
   - Memory log updated with decision
   - WebSocket closes
   - Frontend shows final report

---
**End of Quick Reference**
