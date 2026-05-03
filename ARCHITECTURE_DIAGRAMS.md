# TradingAgents Architecture Diagram

## System Architecture Overview

`
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React + TypeScript)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ConfigForm.tsx                    AnalysisDashboard.tsx                    │
│  ┌──────────────────┐             ┌────────────────────┐                   │
│  │ • Ticker input   │             │ • Agent status     │                   │
│  │ • Date picker    │             │ • Progress bar     │                   │
│  │ • Provider sel.  │             │ • Live messages    │                   │
│  │ • Analyst types  │─ submit ─→  │ • Report panel     │ ← WebSocket       │
│  │ • Data vendors   │             │ • Final decision   │   updates         │
│  │ • Settings save  │             │ • Download report  │                   │
│  └──────────────────┘             └────────────────────┘                   │
│          ↓ (localStorage)                                                    │
│    useAnalysisWebSocket.ts                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
                         POST /api/v1/analysis
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BACKEND API (FastAPI)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  analysis_router.py        config_router.py                                 │
│  ┌──────────────────────┐  ┌──────────────────┐                           │
│  │ POST /analysis       │  │ GET /config      │                           │
│  │ GET /analysis        │  │ PATCH /config    │                           │
│  │ GET /{run_id}        │  │ Models, Memory   │                           │
│  │ GET /{run_id}/report │  │ Checkpoints      │                           │
│  └──────────────────────┘  └──────────────────┘                           │
│            ↓                                                                 │
│    AnalysisService                    ConfigService                         │
│    ┌────────────────────────────┐     ┌──────────────────┐                │
│    │ Concurrency control        │     │ Merge config:    │                │
│    │ (max 3 concurrent)         │     │ defaults +       │                │
│    │ Timeout enforcement        │     │ env vars +       │                │
│    │ (30/35 min)                │     │ persisted +      │                │
│    │ Event broadcasting         │     │ request          │                │
│    │ DB persistence             │     └──────────────────┘                │
│    └────────────────────────────┘                                          │
│            ↓                                                                 │
│    ┌────────────────────────────────────────────────────────────┐          │
│    │ Spawn async task: _run_analysis()                         │          │
│    └────────────────────────────────────────────────────────────┘          │
│                         ↓                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│              LANGGRAPH TRADING GRAPH (tradingagents.graph)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STEP 1: PARALLEL ANALYST EXECUTION                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Market     │  │    Social    │  │     News     │  │ Fundamentals │  │
│  │   Analyst    │  │   Analyst    │  │   Analyst    │  │   Analyst    │  │
│  │ (indicators) │  │  (sentiment) │  │  (events)    │  │ (financials) │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
│         ↓                                                         ↓         │
│   Tool calls:               Tool calls:                    Tool calls:      │
│   • get_stock_data          • get_news                      • get_fundamentals
│   • get_indicators                                          • get_balance_sheet
│   ↓                         ↓                               • get_cashflow
│   tool_nodes[market]        tool_nodes[social]             • get_income_statement
│   ↓                         ↓                               ↓                 │
│  market_report            social_report                fundamentals_report  │
│                                                                              │
│  STEP 2: RESEARCH PHASE                                                     │
│  ┌──────────────────────┐  ┌──────────────────────┐                       │
│  │  Bull Researcher     │  │  Bear Researcher     │                       │
│  │  (bullish case)      │  │  (bearish case)      │                       │
│  └──────────────────────┘  └──────────────────────┘                       │
│         ↓ reads analyst reports ↓                                          │
│  ┌──────────────────────────────────────┐                                 │
│  │   Research Manager (deep LLM)        │                                 │
│  │   Produces: ResearchPlan (struct)    │                                 │
│  │   • recommendation                   │                                 │
│  │   • rationale                        │                                 │
│  │   • strategic_actions                │                                 │
│  └──────────────────────────────────────┘                                 │
│         ↓                                                                   │
│                                                                              │
│  STEP 3: TRADING DECISION                                                   │
│  ┌──────────────────────────────────────┐                                 │
│  │   Trader (quick LLM)                 │                                 │
│  │   Produces: TraderProposal (struct)  │                                 │
│  │   • action (Buy/Hold/Sell)           │                                 │
│  │   • reasoning                        │                                 │
│  │   • entry_price                      │                                 │
│  │   • stop_loss                        │                                 │
│  │   • position_sizing                  │                                 │
│  └──────────────────────────────────────┘                                 │
│         ↓                                                                   │
│                                                                              │
│  STEP 4: RISK MANAGEMENT                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                     │
│  │  Aggressive  │  │   Neutral    │  │ Conservative │                     │
│  │  Debator     │  │  Debator     │  │  Debator     │                     │
│  │ (bullish)    │  │ (balanced)   │  │ (bearish)    │                     │
│  └──────────────┘  └──────────────┘  └──────────────┘                     │
│         ↓ debate ↓                        ↓                               │
│  ┌──────────────────────────────────────┐                                 │
│  │   Portfolio Manager (deep LLM)       │                                 │
│  │   Produces: PortfolioDecision (str)  │                                 │
│  │   • rating                           │                                 │
│  │   • executive_summary                │                                 │
│  │   • investment_thesis                │                                 │
│  │   • price_target                     │                                 │
│  │   • time_horizon                     │                                 │
│  └──────────────────────────────────────┘                                 │
│         ↓                                                                   │
│    final_decision                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│         DATA VENDOR ABSTRACTION LAYER (tradingagents.dataflows)             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  route_to_vendor(method, *args, **kwargs)                                  │
│         ↓                                                                   │
│  Check config: tool_vendors[method] OR data_vendors[category]              │
│         ↓                                                                   │
│  Try primary vendor, fallback to others on rate limit                       │
│         ↓                                ↓                                 │
│    ┌──────────────────┐           ┌──────────────────┐                   │
│    │  Yahoo Finance   │           │  Alpha Vantage   │                   │
│    │  (yfinance)      │           │                  │                   │
│    │                  │           │  • API key req   │                   │
│    │ • OHLCV data     │           │  • Rate limits   │                   │
│    │ • Indicators     │           │  • Extended data │                   │
│    │ • Fundamentals   │           │                  │                   │
│    │ • News           │           │  • get_stock     │                   │
│    └──────────────────┘           │  • get_indicator │                   │
│         ↓                          │  • get_*_data    │                   │
│    Cached CSV/JSON                 └──────────────────┘                   │
│    (if cache hit)                       ↓                                 │
│                                    API Response                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     STREAM PROCESSING & PERSISTENCE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LangGraph stream output                                                    │
│         ↓                                                                   │
│  StreamParser.parse_stream_chunk()                                          │
│         ↓ converts chunks to ↓                                             │
│  AgentStatusEvent, ProgressEvent, SectionEvent                             │
│         ↓                                                                   │
│  EventBus.emit(event_type, data)                                           │
│         ↓                                                                   │
│  ┌──────────────────────────────┐                                         │
│  │   WebSocket Broadcast        │ ──→ AnalysisDashboard (real-time)      │
│  │   (to all connected clients) │                                         │
│  └──────────────────────────────┘                                         │
│         ↓                                                                   │
│  AnalysisDB (SQLite)                                                        │
│  ┌──────────────────────────────┐                                         │
│  │ runs table:                  │                                         │
│  │ • run_id (PK)                │                                         │
│  │ • ticker, analysis_date      │                                         │
│  │ • status, config, timestamps │                                         │
│  │                              │                                         │
│  │ report_sections table:       │                                         │
│  │ • run_id, section, content   │                                         │
│  │ Sections: market_report,     │                                         │
│  │          news_report,        │                                         │
│  │          investment_plan,    │                                         │
│  │          trader_proposal,    │                                         │
│  │          final_decision,     │                                         │
│  │          _snapshot (JSON)    │                                         │
│  └──────────────────────────────┘                                         │
│         ↓                                                                   │
│  Memory Log (markdown file)                                                 │
│  ┌──────────────────────────────┐                                         │
│  │ ## TICKER YYYY-MM-DD         │                                         │
│  │ - **Decision:** Buy           │                                         │
│  │ - **Status:** Pending         │                                         │
│  │ - **Reasoning:** ...          │                                         │
│  │                              │                                         │
│  │ (On next run: auto-resolve)  │                                         │
│  │ - **Status:** Resolved        │                                         │
│  │ - **Outcome:** Raw +3%, Alpha │                                         │
│  │ - **Reflection:** ...         │                                         │
│  └──────────────────────────────┘                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RESPONSE BACK TO FRONTEND                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  GET /api/v1/analysis/{run_id}/report                                       │
│         ↓                                                                   │
│  Markdown report (market_report + news_report + ... + final_decision)       │
│         ↓                                                                   │
│  Frontend displays in ReportPanel.tsx                                       │
│                                                                              │
│  GET /api/v1/analysis/{run_id}/snapshot                                     │
│         ↓                                                                   │
│  JSON final_decision (PortfolioDecision serialized)                         │
│         ↓                                                                   │
│  Frontend can parse and display structured fields                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
`

## Data Flow (Detailed Timeline)

`
T=0s    User fills ConfigForm.tsx and submits
        ├─ ticker: "AAPL"
        ├─ analysis_date: "2024-01-15"
        ├─ provider: "anthropic"
        ├─ analysts: ["market", "news", "fundamentals"]
        └─ data_vendors: {"core_stock_apis": "yfinance"}

T=0.5s  POST /api/v1/analysis arrives at FastAPI
        ├─ AnalysisRequest validated by Pydantic
        ├─ Generate run_id: "550e8400-e29b-41d4-a716-446655440000"
        ├─ Insert into DB: runs table (status="running")
        └─ Return 201 {"run_id": "550e8400...", "status": "running"}

T=1s    Frontend polls GET /api/v1/analysis/{run_id}
        └─ Response: {"status": "running", ...}

T=1.5s  Background task starts: TradingAgentsGraph.run(ticker, date)
        ├─ Initialize LLM clients (deep=claude-opus-4.6, quick=claude-sonnet-4.6)
        ├─ Load config into dataflows/config.py
        └─ Begin StateGraph execution

T=2s    Parallel analysts execute (StateGraph concurrent execution)
        ├─ Market Analyst calls:
        │  ├─ get_stock_data("AAPL", "2024-01-01", "2024-01-15")
        │  │  └─ route_to_vendor → yfinance → CSV returned
        │  └─ get_indicators("AAPL", "macd,rsi", "2024-01-15", 30)
        │     └─ route_to_vendor → yfinance → Indicator analysis
        │
        ├─ News Analyst calls:
        │  ├─ get_news("AAPL", days_back=30)
        │  ├─ get_global_news("AAPL", days_back=30)
        │  └─ get_insider_transactions("AAPL", limit=10)
        │
        └─ Fundamentals Analyst calls:
           ├─ get_fundamentals("AAPL")
           ├─ get_balance_sheet("AAPL")
           ├─ get_cashflow("AAPL")
           └─ get_income_statement("AAPL")

T=4s    StreamParser captures tool execution
        ├─ Emits AgentStatusEvent("Market Analyst", "tools_market", "running")
        ├─ Broadcasts via EventBus.emit()
        └─ WebSocket sends to AnalysisDashboard

T=4s    AnalysisDashboard.tsx updates
        ├─ AgentStatusTable shows: "Market Analyst: running"
        └─ User sees real-time progress

T=6s    Analysts complete their reports
        ├─ market_report: "Technical analysis shows..."
        ├─ social_report: "Sentiment is..."
        ├─ news_report: "Recent events..."
        └─ fundamentals_report: "Valuation metrics..."

T=7s    Bull & Bear Researchers synthesize
        ├─ Bull Researcher: "The stock is undervalued..."
        ├─ Bear Researcher: "However, recent macro headwinds..."
        └─ Stream updates broadcast

T=9s    Research Manager (deep LLM)
        ├─ Input: all reports + debate
        ├─ Structured output schema enabled
        ├─ Output: ResearchPlan {
        │    recommendation: "Overweight",
        │    rationale: "...",
        │    strategic_actions: "..."
        │  }
        └─ Stream: "investment_plan" section recorded

T=11s   Trader (quick LLM)
        ├─ Input: ResearchPlan + all reports
        ├─ Output: TraderProposal {
        │    action: "Buy",
        │    reasoning: "...",
        │    entry_price: 185.50,
        │    stop_loss: 182.00,
        │    position_sizing: "2% of portfolio"
        │  }
        └─ Stream: "trader_proposal" section recorded

T=13s   Risk Debators (quick LLM x3)
        ├─ Aggressive: "Upside to ..."
        ├─ Neutral: "Fair value range..."
        ├─ Conservative: "Downside risks..."
        └─ Streams broadcast

T=16s   Portfolio Manager (deep LLM)
        ├─ Input: all prior analysis + risk views
        ├─ Structured output schema enabled
        ├─ Output: PortfolioDecision {
        │    rating: "Overweight",
        │    executive_summary: "...",
        │    investment_thesis: "...",
        │    price_target: 192.00,
        │    time_horizon: "6-12 months"
        │  }
        └─ Stream: "final_decision" section + "_snapshot" JSON recorded

T=17s   All sections written to DB (report_sections table)
        ├─ market_report
        ├─ news_report
        ├─ fundamentals_report
        ├─ investment_plan
        ├─ trader_proposal
        ├─ final_decision
        └─ _snapshot (JSON)

T=18s   Update runs table
        ├─ status = "completed"
        ├─ completed_at = ISO timestamp
        └─ Report available for download

T=18s   EventBus broadcasts completion event
        └─ WebSocket sends: {"type": "complete", "status": "completed"}

T=18s   Frontend receives completion
        ├─ AnalysisDashboard shows "Complete"
        ├─ ReportPanel displays full markdown report
        ├─ Can download report: report-550e8400-....md
        └─ Can view snapshot: final decision JSON

T=19s   Memory log updated (on next analysis of same ticker)
        ├─ Previous pending entry for AAPL 2024-01-08 resolved
        ├─ Fetch price data: AAPL on 2024-01-08 → 2024-01-15
        ├─ Calculate raw_return: +2.3%
        ├─ Calculate alpha: +0.8% (vs SPY)
        ├─ Generate reflection: "Our call was correct but underestimated..."
        └─ Mark AAPL 2024-01-08 as Resolved in memory log
`

## Request Configuration Hierarchy

`
┌────────────────────────────────┐
│ 1. DEFAULT_CONFIG              │ (Lowest priority)
│    tradingagents/              │
│    default_config.py           │
│                                │
│  llm_provider="openai"         │
│  data_vendors:                 │
│    core_stock_apis="yfinance"  │
│  ...                           │
└────────────────────────────────┘
           ↑ merge
┌────────────────────────────────┐
│ 2. ENVIRONMENT VARIABLES       │
│                                │
│  TRADINGAGENTS_LLM_PROVIDER    │
│  TRADINGAGENTS_DEEP_THINK_LLM  │
│  OPENAI_API_KEY                │
│  ALPHA_VANTAGE_API_KEY         │
│  ...                           │
└────────────────────────────────┘
           ↑ merge
┌────────────────────────────────┐
│ 3. DATABASE (Persisted         │
│    Config overrides)           │
│                                │
│  UPDATE config_overrides       │
│  SET llm_provider="anthropic"  │
│  ...                           │
└────────────────────────────────┘
           ↑ merge
┌────────────────────────────────┐
│ 4. REQUEST (Highest priority)  │
│                                │
│  AnalysisRequest {             │
│    provider: "google",         │
│    analysts: ["market"],       │
│    data_vendors: {...},        │
│    ...                         │
│  }                             │
└────────────────────────────────┘
           ↓
┌────────────────────────────────┐
│ RESOLVED CONFIG                │ (Used for analysis)
│                                │
│  llm_provider="google"         │
│  (from request override)       │
│  data_vendors: {...}           │
│  (merged from all levels)      │
│  ...                           │
└────────────────────────────────┘
`

## LLM Provider Selection Flow

`
User selects provider in ConfigForm.tsx
         ↓
GET /api/v1/models?provider=anthropic
         ↓
models_router.py: get_known_models()
         ↓
model_catalog.py: MODEL_OPTIONS["anthropic"]
         ↓
Returns {
  "quick": [
    ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
    ("Claude Haiku 4.5", "claude-haiku-4-5"),
    ...
  ],
  "deep": [
    ("Claude Opus 4.6", "claude-opus-4-6"),
    ("Claude Opus 4.5", "claude-opus-4-5"),
    ...
  ]
}
         ↓
Frontend populates dropdown menus
         ↓
User selects: deep_think_llm="claude-opus-4.6"
              quick_think_llm="claude-sonnet-4-6"
         ↓
Form submission includes these in AnalysisRequest
         ↓
AnalysisService._build_config()
         ↓
create_llm_client(
    provider="anthropic",
    model="claude-opus-4-6",
    base_url=config.get("backend_url"),
    effort="high"  # if config["anthropic_effort"]
)
         ↓
anthropic_client.py: AnthropicClient()
         ↓
Initialize Anthropic SDK with API key
         ↓
LLM ready for TradingAgentsGraph
`

---

**Architecture Documentation Complete**
