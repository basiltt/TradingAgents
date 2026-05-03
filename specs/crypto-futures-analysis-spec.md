# Crypto Futures Analysis via Bybit — Specification

## A. Metadata

- **Feature**: Bybit Crypto Futures Analysis
- **Date**: 2026-05-03
- **Author**: Claude (AI agent)
- **Status**: Draft
- **Related user request**: Extend TradingAgents to analyze crypto futures coins via Bybit
- **Related modules**: `tradingagents/dataflows/`, `tradingagents/agents/`, `tradingagents/graph/`, `backend/`, `frontend/`
- **Version**: 1.0

## B. Discovery Summary

### Relevant files inspected
- `tradingagents/dataflows/interface.py` — vendor routing system with `VENDOR_METHODS`, `TOOLS_CATEGORIES`, `route_to_vendor()`
- `tradingagents/dataflows/config.py` — global config singleton (`set_config()`, `get_config()`)
- `tradingagents/dataflows/y_finance.py` — yfinance implementations (OHLCV, indicators, fundamentals)
- `tradingagents/dataflows/alpha_vantage.py` — Alpha Vantage implementations
- `tradingagents/agents/utils/agent_utils.py` — LangChain `@tool` decorated functions calling `route_to_vendor()`
- `tradingagents/graph/trading_graph.py` — `TradingAgentsGraph.__init__`, tool node creation, graph compilation
- `tradingagents/graph/setup.py` — `GraphSetup.setup_graph(selected_analysts)` wiring
- `tradingagents/graph/propagation.py` — `Propagator.create_initial_state(company_name, trade_date)`
- `tradingagents/default_config.py` — `DEFAULT_CONFIG` with `data_vendors`, `llm_provider`, etc.
- `backend/schemas.py` — `AnalysisRequest` Pydantic model, `TICKER_RE`, `AnalystType` enum
- `backend/services/analysis_service.py` — `_build_config()`, `_execute_graph()`
- `frontend/src/components/analysis/ConfigForm.tsx` — form with ticker, date, provider, analysts, vendors
- `frontend/src/api/client.ts` — `StartAnalysisRequest` type, `apiClient` methods
- Reference: `BossTrader/app/brokers/bybit.py` — Bybit broker with REST/WS, order placement, position management

### Existing patterns
- **Vendor routing**: Tools call `route_to_vendor(method_name, *args)` → picks vendor from config → calls vendor-specific function
- **Tool registration**: `@tool` decorated functions in `agent_utils.py`, bound to agents via `ToolNode`
- **Analyst wiring**: `GraphSetup.setup_graph(selected_analysts)` conditionally adds analyst nodes
- **Config hierarchy**: DEFAULT_CONFIG → env vars → persisted config → request overrides
- **Data functions signature**: `get_YFin_data_online(ticker, start_date, end_date)` returns CSV string

### Key constraints
- Bybit public API requires no auth for market data (kline, funding, open interest, tickers)
- Crypto tickers use format like BTCUSDT (no dots/dashes, uppercase letters + digits)
- No balance sheets, cashflow, income statements for crypto — need different analyst set
- stockstats library works with any OHLCV DataFrame — can reuse for crypto technical indicators
- The existing `TICKER_RE = r"^[A-Z0-9.\-^]{1,15}$"` already accepts crypto tickers like BTCUSDT

## C. Feature Overview

- **What**: Add a "Crypto Futures" analysis mode that uses Bybit public API to fetch crypto perpetual futures data, then runs a crypto-adapted multi-agent pipeline producing trading signals with entry/exit points, stop losses, take profits, confidence levels, and risk management
- **Why**: Users want to analyze crypto futures markets using the same multi-agent framework, with crypto-specific data (funding rates, open interest, liquidations)
- **Who**: Traders analyzing crypto perpetual futures on Bybit
- **Expected outcome**: User selects "Crypto Futures" mode, enters a symbol (e.g., BTCUSDT), and receives a comprehensive analysis including trading signals with specific price levels

## D. Business Goal

- Expand TradingAgents from stocks-only to stocks + crypto futures
- Provide actionable crypto trading signals: trade type (long/short), entry, exit, SL/TP levels
- Leverage Bybit's free public API for real-time crypto market data
- Reuse the proven multi-agent debate framework for higher-quality crypto analysis

### User Requirements (verbatim from user responses)

The user specified the following scope for crypto analysis:
1. **Technical Analysis** — OHLCV klines, indicators (RSI, MACD, Bollinger, etc.)
2. **Funding Rate Analysis** — unique to crypto futures, cost/benefit of holding positions
3. **Open Interest & Liquidations** — key crypto futures signals for market sentiment
4. **News & Sentiment** — crypto-specific news analysis
5. **Trading Signals** — the most critical output, including:
   - Trade Type (Long/Short/No Trade)
   - Entry Point (specific price or zone)
   - Exit Point (target price)
   - Number of Stop Losses and their values (1-3 levels with exact prices)
   - Number of Take Profits and their values (1-3 levels with exact prices)
   - Confidence Level (1-10)
6. **Portfolio Management** — position sizing, allocation recommendations
7. **Risk Management** — leverage limits, drawdown analysis, invalidation criteria
8. **Other important aspects** — risk/reward ratio, market structure, time horizon, liquidation levels

Additional user decisions:
- **Separate mode**: A dedicated "Crypto Futures" mode with its own UI toggle (not auto-detect)
- **Bybit API access**: Public endpoints by default (no auth required), with optional API key support for users who want higher rate limits

## E. Current System Behavior

- Only supports stock tickers via yfinance/Alpha Vantage
- Analysts: market (technical), social (sentiment), news, fundamentals
- Fundamentals analyst uses balance sheets, cashflow, income statements — stock-specific
- Trader agent produces a general investment plan without specific entry/exit levels
- Portfolio manager makes final decision (Overweight/Underweight/etc.) — stock-oriented language
- Config has `data_vendors` with categories: `core_stock_apis`, `technical_indicators`, `fundamental_data`, `news_data`
- No concept of asset type — everything assumes stock

## F. Expected New Behavior

- New `asset_type` field: `"stock"` (default) or `"crypto"`
- When `asset_type="crypto"`:
  - Data fetched from Bybit public API (OHLCV klines, funding rates, open interest, ticker stats)
  - Technical indicators computed via stockstats on Bybit OHLCV data
  - Analysts: `crypto_technical` (OHLCV + indicators + derivatives data), `crypto_derivatives` (funding rates, OI, liquidation proxy), `crypto_news` (crypto news/sentiment)
  - Trader agent outputs a structured trading signal:
    - Trade Type: Long / Short / No Trade
    - Entry Price/Zone with reasoning
    - Exit Price (target) with reasoning
    - 1-3 Stop Loss levels with exact prices and reasoning for each
    - 1-3 Take Profit levels with exact prices and reasoning for each
    - Confidence level (1-10) with justification
    - Position size recommendation (% of portfolio)
    - Leverage recommendation (e.g., 3x-5x) with risk context
    - Risk/Reward ratio calculated from entry, SL, TP
    - Time horizon (scalp / intraday / swing / position)
  - Risk analyst debates adapted for crypto futures context (leverage, liquidation risk, funding cost, market structure, OI trends, correlation risk)
  - Portfolio manager outputs comprehensive crypto trade plan with:
    - Final trade direction with reasoning
    - Entry zone, SL levels, TP levels (all with exact prices)
    - Position sizing and max leverage
    - Risk/reward ratio and confidence score
    - Key risk factors and invalidation criteria
    - Market regime assessment and portfolio management rules
- When `asset_type="stock"`: existing behavior unchanged
- Frontend shows asset type toggle; crypto mode hides stock-specific options (fundamentals analyst, stock data vendors)
- Optional Bybit API key in config for higher rate limits

## G. Scope

### In Scope
- Bybit public REST API data fetching (klines, funding rates, open interest, tickers)
- Bybit as a new data vendor in the routing system
- Crypto-specific analyst agents (technical, derivatives, news)
- Enhanced trader/risk/portfolio manager prompts for crypto futures with specific SL/TP/entry/exit
- `asset_type` field in API request, config, and frontend
- Frontend asset type toggle with conditional form sections
- Optional Bybit API key configuration
- Crypto ticker validation

### Out of Scope
- Bybit WebSocket real-time streaming (analysis is point-in-time, not live)
- Order execution / trade placement via Bybit
- Bybit private API endpoints (account, positions, orders)
- Spot crypto analysis (futures only)
- Other exchanges (Binance, OKX, etc.)
- Backtesting or strategy automation

### Future Scope
- Multi-exchange data aggregation
- Real-time price feeds via WebSocket
- Historical backtesting of crypto signals
- Spot crypto analysis
- DeFi protocol analysis

## H. Functional Requirements

```
FR-001: The system must accept an `asset_type` parameter ("stock" or "crypto") in the analysis request.
FR-002: When asset_type="crypto", the system must fetch OHLCV kline data from Bybit public API (/v5/market/kline, category=linear).
FR-003: When asset_type="crypto", the system must fetch historical funding rates from Bybit (/v5/market/funding/history).
FR-004: When asset_type="crypto", the system must fetch open interest data from Bybit (/v5/market/open-interest, category=linear).
FR-005: When asset_type="crypto", the system must fetch 24h ticker statistics from Bybit (/v5/market/tickers, category=linear).
FR-006: The system must compute technical indicators (RSI, MACD, Bollinger Bands, EMA, etc.) from Bybit OHLCV data using the existing stockstats library.
FR-007: When asset_type="crypto", the system must use crypto-specific analyst agents: crypto_technical, crypto_derivatives, crypto_news.
FR-008: The crypto trader agent must output a structured trading signal including:
  - Trade Type: Long / Short / No Trade
  - Entry Price: specific price or price zone (e.g., "$67,200 - $67,500")
  - Exit Price: target price for taking full profit
  - Stop Losses: 1-3 stop loss levels with exact prices and reasoning (e.g., SL1: $66,800 — below recent swing low, SL2: $66,200 — below key support)
  - Take Profits: 1-3 take profit levels with exact prices and reasoning (e.g., TP1: $68,500 — resistance level, TP2: $69,800 — previous high)
  - Confidence Level: 1-10 scale with justification
  - Position Size: recommended % of portfolio to allocate
  - Leverage Recommendation: suggested leverage (e.g., 3x-5x) with risk context
  - Risk/Reward Ratio: calculated from entry, SL, and TP levels
  - Time Horizon: expected trade duration (scalp/intraday/swing/position)
FR-009: The crypto risk debate agents must consider:
  - Funding rate impact (cost of holding position, positive/negative funding)
  - Liquidation risk at recommended leverage (exact liquidation price)
  - Open interest trends (increasing/decreasing OI and what it signals)
  - Market volatility (ATR-based, historical vol, implied vol if available)
  - Correlation with BTC (for altcoins — beta risk)
  - Market structure analysis (trend, range, breakout, breakdown)
  - Whale/smart money flow indicators (large OI changes, funding rate extremes)
  - Max drawdown scenarios at recommended leverage
FR-010: The crypto portfolio manager must output a comprehensive final trade decision including:
  - Final Trade Direction: Long / Short / No Trade with clear reasoning
  - Entry Zone: specific price range for entry
  - Stop Loss Levels: final recommended SL levels (1-3) with exact prices
  - Take Profit Levels: final recommended TP levels (1-3) with exact prices
  - Position Sizing: % of portfolio, dollar amount guidance
  - Maximum Leverage: hard cap on leverage with reasoning
  - Risk/Reward Ratio: final calculated R:R
  - Overall Confidence Score: 1-10 with detailed justification
  - Key Risk Factors: top 3 risks that could invalidate the trade
  - Invalidation Criteria: specific conditions that would cancel the trade setup
  - Market Regime Assessment: trending/ranging/volatile and implications
  - Portfolio Management Rules: when to add to position, when to reduce, trailing stop strategy
FR-011: When asset_type="stock", existing behavior must be completely unchanged.
FR-012: The frontend must show an asset type toggle (Stock / Crypto Futures) at the top of the analysis form.
FR-013: When crypto mode is selected, the frontend must show crypto-relevant analysts and hide stock-specific options (fundamentals analyst, stock data vendor categories).
FR-014: The system must support optional Bybit API key and secret in the configuration for higher rate limits.
FR-015: The system must validate crypto symbols (e.g., BTCUSDT) and reject invalid formats.
FR-016: Crypto news analysis must use the existing news tools with crypto-adapted prompts (e.g., searching for "Bitcoin" or the coin name). Crypto-specific news APIs are deferred to future scope.
FR-017: When the requested date range exceeds a single Bybit API page (200 records), the system must paginate to retrieve the full range up to a configurable maximum (default 1000 candles). Pagination must have an explicit max-iterations guard (5 pages, since 5 × 200 = 1000) to prevent infinite loops.
FR-018: The system must validate crypto symbols using a strict regex `^[A-Z0-9]{2,20}$` when asset_type="crypto", rejecting symbols with dots, dashes, or carets.
FR-019: The trader agent's output must conform to a defined JSON schema with typed fields (trade_type: string, entry_price: float, exit_price: float, stop_losses: array of {level: int, price: float, reasoning: string}, take_profits: array of {level: int, price: float, reasoning: string}, confidence: int, position_size_pct: float, leverage: float, risk_reward_ratio: float, time_horizon: string). The LLM must be prompted with structured output instructions.
FR-020: The system must validate the trader agent's signal for internal consistency: for Long trades SL prices < entry price < TP prices; for Short trades TP prices < entry price < SL prices; confidence in [1,10]; leverage in [1, max_leverage_cap]. Invalid signals are retried once; if still invalid, output is flagged with a warning. Note: `entry_price` in the JSON schema (FR-019) is a single float — the "zone" concept from FR-008 is captured in the reasoning text, not as separate fields.
FR-021: The system must use a default kline interval of "60" (1 hour) with a lookback of 200 candles. The interval must be configurable via the analysis request (options: "15" for 15m, "60" for 1h, "240" for 4h, "D" for daily).
FR-022: The system must include a configurable `max_leverage` parameter (default 20) that caps any LLM-recommended leverage.
FR-023: The final report must include the timestamp of the last price data used and the current price at report generation time, so the trader can assess signal freshness.
FR-024: When the trader agent outputs "No Trade", the signal fields (entry, exit, SL, TP, leverage) may be null/omitted. The dashboard must display "No Trade Recommended" with the reasoning.
FR-025: Independent Bybit API calls within the same analyst must be issued concurrently (using a bounded `ThreadPoolExecutor(max_workers=5)` created per analyst invocation and shut down after) to keep data gathering under 30 seconds. Note: the 30s target is for typical cases; worst-case pagination (5 pages × 40s) may exceed this — the target applies to the common 200-candle lookback.
```

## I. Non-Functional Requirements

```
NFR-001: Bybit API calls must timeout after 30 seconds per request.
NFR-002: Bybit API calls must include retry with exponential backoff (max 3 retries) for transient failures (429, 5xx).
NFR-003: Bybit API keys must never be logged or exposed in API responses.
NFR-004: The crypto analysis pipeline must complete within the existing 30-minute wall timeout.
NFR-005: Bybit data functions must cache results for the same symbol/interval/date within a single analysis run to avoid redundant API calls.
NFR-006: The system must implement an application-level rate limiter (token bucket) for outbound Bybit API calls, shared across concurrent analyses, capped at 80 requests per 5 seconds (33% headroom below Bybit's 120/5s public limit, for retry bursts). Implementation: a module-level singleton `BybitRateLimiter` in `bybit_data.py` using `threading.Lock` and a token bucket algorithm. All Bybit HTTP calls go through `limiter.acquire()` before sending. `acquire()` blocks with a 10s timeout (separate from the 30s HTTP timeout — worst-case per call is 40s total) and raises on timeout. Retries DO consume rate-limit tokens (accounted for in the 33% headroom). Note: single-worker uvicorn deployment assumed (as per start.bat); multi-worker deployments need an external rate limiter. Worst-case concurrency: 3 analyses × 5 endpoints = 15 concurrent calls, well within budget.
NFR-007: All new code must follow existing codebase patterns (vendor routing, @tool decorators, agent prompt structure).
NFR-008: Run-scoped caching: Bybit data functions use per-endpoint cache keys: klines → `("klines", symbol, interval, start, end)`, funding → `("funding", symbol, start, end)`, OI → `("oi", symbol, interval, start, end)`, ticker → `("ticker", symbol)` (no time component — run scope guarantees freshness), indicators → `("indicators", symbol, interval, start, end)`. Cache dict created per analysis run; goes out of scope when `_execute_graph` returns (GC eligible). Indicators cache prevents repeated stockstats recomputation.
```

## J. User Flows

### Primary Flow — Crypto Futures Analysis
1. User navigates to "New Analysis" page
2. User selects "Crypto Futures" from the asset type toggle
3. Form updates to show crypto-relevant fields (symbol, date, analysts)
4. User enters symbol (e.g., "BTCUSDT") and analysis date
5. User optionally selects analysts: crypto_technical, crypto_derivatives, crypto_news
6. User clicks "Start Analysis"
7. System validates input (valid crypto symbol, date not in future)
8. System starts analysis → redirects to dashboard
9. Dashboard shows real-time progress (agents running, messages, stats)
10. Analysis completes → report shows trading signal with entry/exit/SL/TP/confidence

### Alternate Flow — With API Key
1. User goes to Config page
2. User enters Bybit API key and secret
3. Config saved
4. When running crypto analysis, system uses API key for Bybit requests

### Failure Flow — Bybit API Unreachable
1. User starts crypto analysis
2. System attempts to fetch data from Bybit API
3. All 3 retry attempts fail (timeout or 5xx)
4. Analysis fails with error "Bybit API unavailable — please try again later"
5. Dashboard shows failed status with error message

### Failure Flow — Partial Data Failure (Non-Critical Endpoint)
1. User starts crypto analysis
2. OHLCV klines fetch succeeds (critical), but funding rate or OI endpoint fails (non-critical)
3. Analysis continues with available data; agents note missing data in their reports
4. Final report includes a caveat about incomplete data

**Critical vs non-critical endpoints:** Klines (OHLCV) is critical — if it fails, analysis terminates. Funding rates, open interest, and ticker stats are non-critical — analysis continues without them.

### Failure Flow — Invalid Symbol / No Data
1. User enters invalid symbol (e.g., "INVALID")
2. Bybit klines API returns error or empty data
3. System reports "No data available for symbol" error
4. Analysis terminates with failed status and error message

## K. API Requirements

### Modified: GET /api/v1/analysis (list)
**Query parameter changes:**
- Add optional `asset_type` filter parameter (e.g., `?asset_type=crypto`) to filter analysis runs by type

### Modified: POST /api/v1/analysis
**Request body changes:**
- Add `asset_type: Optional[str]` — "stock" (default) or "crypto"
- Add `interval: Optional[str]` — kline interval for crypto: "15", "60" (default), "240", "D"

**Frontend `StartAnalysisRequest` type must also add `asset_type` and `interval` fields.**

**Validation (Pydantic `model_validator`):**
- `asset_type` must be "stock" or "crypto"
- When asset_type="crypto", `analysts` values must be from `CryptoAnalystType`: crypto_technical, crypto_derivatives, crypto_news
- When asset_type="crypto", `data_vendors` is ignored (Bybit is the only vendor)
- When asset_type="crypto", ticker must match `^[A-Z0-9]{2,20}$` (no dots/dashes/carets)
- When asset_type="stock" (or omitted), existing `AnalystType` enum and `TICKER_RE` apply
- Cross-field validation uses a Pydantic `model_validator(mode="after")` that checks `asset_type` and dispatches to the appropriate ticker regex and analyst enum. This replaces per-field validators that cannot access sibling fields.
- When `asset_type="crypto"`, `interval` must be one of `["15", "60", "240", "D"]`; otherwise return 422. When `asset_type="stock"`, `interval` is ignored.

### Modified: GET /api/v1/analysis/{run_id}
**Response changes:**
- Include `asset_type` and `interval` fields in the run details response so the frontend can adapt rendering without local state assumptions

### Modified: GET /api/v1/config
**Response changes:**
- Include `exchange_credentials.bybit` always present with shape: `{ "api_key": string | null, "api_secret_configured": boolean }` (masked, first 4 chars + "***" for api_key; if key <= 4 chars, mask entirely as "***")

### Modified: PATCH /api/v1/config
**Request body changes:**
- Accept `exchange_credentials.bybit.api_key` and `exchange_credentials.bybit.api_secret` in overrides

## L. UI/UX Requirements

### ConfigForm.tsx changes
- Add asset type toggle at the top: "Stock" | "Crypto Futures" (use `role="radiogroup"` with `role="radio"` children and `aria-checked` for accessibility)
- **Mode toggle resets form fields**: switching asset type clears ticker, resets analysts to mode defaults, and resets interval to default. This prevents submitting stock tickers in crypto mode or vice versa.
- When "Crypto Futures" selected:
  - Ticker input placeholder changes to "e.g., BTCUSDT"
  - Ticker label changes to "Symbol"
  - Analysts checkboxes show: crypto_technical, crypto_derivatives, crypto_news
  - Data vendors section hidden (Bybit is implicit)
  - Fundamentals-related options hidden
  - Kline interval selector: `[{label: "15m", value: "15"}, {label: "1h", value: "60"}, {label: "4h", value: "240"}, {label: "Daily", value: "D"}]`
- When "Stock" selected: existing behavior unchanged

### Analysis Dashboard — Crypto Signal Rendering
- The existing `ReportPanel` renders the portfolio manager's markdown output via `react-markdown`. The structured trading signal (FR-019 JSON) is embedded within the markdown report text — the LLM formats it as a readable section with tables/headers. No separate structured signal card is needed at this stage.
- For "No Trade" output (FR-024): the report will contain a "No Trade Recommended" section with reasoning. The existing markdown rendering handles this.
- Future enhancement: a dedicated signal card component parsing the JSON schema for visual presentation (SL/TP ladder, confidence gauge). This is deferred — the markdown report is the MVP delivery.

### Config page — Bybit credentials section
- Add "Bybit API (Optional)" section below existing settings:
  - **API Key** text input: after save, displays masked value (e.g., "AbC1***") as read-only. Click "Edit" to clear and enter new value. Never pre-filled with full key from backend.
  - **API Secret** password input: always masked, never returned from API
  - **Status indicator**: "Configured" / "Not configured" badge based on `api_secret_configured` boolean from GET /config
  - **Validation**: if user provides key without secret (or vice versa), show inline error "Both API Key and API Secret are required". Disable Save until both filled or both empty.
  - **Remove** button: clears both key and secret (PATCH with null values)
  - **Save** button: saves both fields via PATCH /config with `exchange_credentials.bybit` payload

### Analysis Dashboard
- No changes needed — existing dashboard handles all event types generically

## M. Backend Requirements

### New files
- `tradingagents/dataflows/bybit_data.py` — Bybit public API data fetching functions:
  - `get_bybit_klines(symbol, interval, start_time, end_time)` → CSV OHLCV string (internally paginates up to 1000 candles)
  - `get_bybit_funding_rates(symbol, start_time, end_time)` → formatted string
  - `get_bybit_open_interest(symbol, interval, start_time, end_time)` → formatted string
  - `get_bybit_ticker(symbol)` → formatted string with 24h stats
  - `get_bybit_indicators(symbol, interval, start_time, end_time)` → technical indicators string (internally calls `get_bybit_klines` cache-first, then computes via stockstats — self-sufficient regardless of tool invocation order)
  - All functions use `requests` with parameterized query params (no string interpolation)
  - Internal pagination: `get_bybit_klines` loops until all candles fetched (max 1000 configurable). Cursor strategy: set `end = min(previous_page_timestamps) - 1` for next request (Bybit returns descending order). Loop terminates when: (a) returned rows < 200, (b) 5 iterations reached, or (c) total candles >= max.
  - Run-scoped caching: functions accept optional `cache: dict` param; key = `(symbol, interval, start, end)`; cache dict created per analysis run in `_execute_graph` and bound into tool functions via `functools.partial` before constructing the `ToolNode` (not passed through LangGraph state, since `@tool` functions cannot access graph state fields)

- `tradingagents/agents/utils/crypto_agent_utils.py` — Crypto-specific `@tool` functions (separate from stock tools):
  - `get_crypto_klines`, `get_crypto_indicators`, `get_funding_rates`, `get_open_interest`, `get_crypto_ticker`
  - These call bybit_data.py directly (no vendor routing — Bybit is the only vendor for crypto)

- `tradingagents/agents/crypto_analysts.py` — Crypto analyst agent functions (note: stocks define analysts inline in `setup.py`, but crypto warrants its own module due to larger scope — 3 specialized analysts with crypto-specific prompts):
  - `crypto_technical_analyst(state)` — uses klines + indicators tools
  - `crypto_derivatives_analyst(state)` — uses funding rates + OI + ticker tools
  - `crypto_news_analyst(state)` — uses existing news tools with crypto context prompt

### Modified files
- `tradingagents/dataflows/interface.py`:
  - NO changes to existing VENDOR_METHODS or TOOLS_CATEGORIES (stock routing untouched)
  - Add "bybit" to `VENDOR_LIST` for informational purposes only

- `tradingagents/agents/utils/agent_utils.py`:
  - NO changes (stock tools unchanged)

- `tradingagents/graph/trading_graph.py`:
  - Add factory/strategy pattern: `_create_crypto_tool_nodes()` method alongside `_create_tool_nodes()`
  - Constructor checks `config.get("asset_type", "stock")` and delegates to appropriate tool node creator
  - Crypto tool nodes use tools from `crypto_agent_utils.py`

- `tradingagents/graph/setup.py`:
  - `GraphSetup` accepts tool nodes and analyst functions via constructor (already does)
  - Add crypto analyst wiring when crypto analysts are selected
  - Crypto analyst names: `crypto_technical`, `crypto_derivatives`, `crypto_news`

- `tradingagents/graph/propagation.py`:
  - `create_initial_state()` — add `asset_type` to state dict

- `tradingagents/default_config.py`:
  - Add `asset_type: "stock"` default
  - Add `crypto_interval: "60"` default (1h klines)
  - Add `crypto_max_leverage: 20` default
  - Add credentials under structured key: `"exchange_credentials": {"bybit": {"api_key": None, "api_secret": None}}`
  - Env var mapping: `BYBIT_API_KEY`, `BYBIT_API_SECRET`

- `backend/schemas.py`:
  - Add `asset_type` to `AnalysisRequest`
  - Add `CryptoAnalystType` enum: crypto_technical, crypto_derivatives, crypto_news
  - Update `AnalystType` or add separate validation for crypto analysts

- `backend/persistence.py`:
  - Add `asset_type` to `insert_run()` INSERT column list
  - Add migration `(2, 'ALTER TABLE ...')` to `_MIGRATIONS` list

- `backend/services/analysis_service.py`:
  - `_build_config()` — pass `asset_type` to config
  - `_execute_graph()` — pass asset_type when creating graph

## N. Database/Data Requirements

### Migration V2: Add `asset_type` column
- Add `asset_type TEXT NOT NULL DEFAULT 'stock'` column to `analysis_runs` table
- Backfill: all existing rows get `'stock'` (the default handles this)
- Migration SQL: `ALTER TABLE analysis_runs ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))`
- Register as `(2, '<SQL>')` in the `_MIGRATIONS` list in `backend/persistence.py` (single-statement migration; additional DDL goes in separate migration tuples)
- Migrations run automatically on startup via `_apply_migrations()` — no manual step needed
- SQLite does not support `CHECK` constraints well, so ticker format validation is enforced at the application layer (Pydantic model_validator) not in the database
- Index: not needed initially — `asset_type` has only 2 values (low cardinality)

### INSERT statement update
- `backend/persistence.py` `insert_run()` must be updated to include `asset_type` in the INSERT column list, parameterized from the run config

### Rollback strategy
- The `asset_type` column with `DEFAULT 'stock'` is backward-compatible: old code ignores the extra column (uses `SELECT *` with `dict(row)` access)
- If full rollback needed, the column can remain in place permanently — old code is unaffected
- SQLite < 3.35 cannot DROP COLUMN; no table recreation is needed since the column is harmless

### `recover_orphans` update
- Remove the previously planned `instance_id` filter — `instance_id` is regenerated on every startup so filtering by it would be a no-op. The existing orphan recovery (marking all `status='running'` as failed) remains correct for single-instance deployments. Multi-instance orphan handling is out of scope.

## O. Integration Requirements

### Bybit Public REST API
- Base URL: `https://api.bybit.com`
- No authentication required for market data endpoints
- Optional: HMAC-SHA256 signed requests when API key configured (for higher rate limits)
- Rate limit: 120 requests per 5 seconds (public)
- Retry: exponential backoff on 429/5xx, max 3 retries
- Timeout: 30s per request
- Endpoints used:
  - `GET /v5/market/kline` — OHLCV (params: category=linear, symbol, interval, start, end, limit)
  - `GET /v5/market/funding/history` — Funding rates (params: category=linear, symbol, startTime, endTime, limit)
  - `GET /v5/market/open-interest` — OI (params: category=linear, symbol, intervalTime, startTime, endTime)
  - `GET /v5/market/tickers` — 24h stats (params: category=linear, symbol)

## P. Security Requirements

- Bybit API key/secret must be sourced from environment variables (`BYBIT_API_KEY`, `BYBIT_API_SECRET`) or the config PATCH endpoint
- `bybit_api_secret` must NEVER be returned by GET /api/v1/config — only indicate whether it is set (boolean `bybit_api_secret_configured: true/false`)
- `bybit_api_key` returned masked (first 4 chars + "***") in GET /api/v1/config
- API keys masked in all API responses (existing `mask_secrets` utility)
- API keys and secrets never logged — logging must scrub `api_key`, `api_secret`, `sign`, `timestamp` params from logged URLs
- HMAC signing must follow Bybit's official spec: include `timestamp` param (within 5000ms window), `sign` param, `api_key` param. The `api_secret` MUST only be used locally for HMAC computation and MUST NEVER be transmitted in any request parameter, header, or body.
- Credential PATCH atomicity: both `api_key` and `api_secret` must be provided together (or both set to null for removal). Reject partial updates with 422.
- Crypto symbol validation: use strict regex `^[A-Z0-9]{2,20}$` for crypto mode (no dots, dashes, or carets)
- All Bybit API calls must use parameterized query strings (not string interpolation) to prevent injection
- Log scrubbing: sensitive params (`api_key`, `api_secret`, `sign`, `timestamp`) must be stripped from URLs BEFORE constructing log messages (not as post-hoc filter). Exception messages containing URLs must be sanitized before logging. Disable urllib3 DEBUG logging for the Bybit session.
- Rate limiter and caching: cache hits do NOT consume rate-limit tokens; tokens are only consumed for actual outbound HTTP requests.
- Config endpoints follow existing auth pattern (localhost-only in dev; document threat model for multi-user deployments)
- Bybit API secrets stored via PATCH /config are persisted in the existing config store (same as other config overrides). For this dev/single-user deployment, plaintext storage matches the existing pattern (other API keys like OPENAI_API_KEY are also stored the same way). Production deployments should use environment variables only.
- Input validation: crypto symbol format, date validation (same as stock). `interval` is ignored when `asset_type="stock"`.

## Q. Performance Requirements

- Bybit API calls: <2s average per endpoint (public API is fast)
- Total data gathering phase: <30s for all crypto data tools
- Cache within run: same symbol/interval/date combination returns cached result
- No impact on stock analysis performance

## R. Logging, Monitoring, and Observability

- Log Bybit API calls at DEBUG level (URL, params, response time)
- Log Bybit API errors at WARNING/ERROR level
- Log crypto analyst agent invocations (same pattern as stock analysts)
- Do NOT log API keys or secrets

## S. Edge Cases

- **Delisted/invalid symbol**: Bybit returns retCode != 0 → agent receives "No data available" → analysis continues with available data
- **Symbol with no funding data**: New perpetuals may have limited history → agent handles empty data gracefully
- **Weekend/holiday**: Crypto markets are 24/7 so date is always valid
- **Very new coin**: Limited historical data → analysis notes data limitations
- **Bybit API downtime**: Retry 3x, then fail gracefully with error message
- **Large date range**: Bybit limits results to 200 per request page → pagination needed for ranges exceeding 200 candles (up to 1000 app limit)
- **Concurrent crypto analyses**: Same concurrency limits as stock (max 3)
- **Rate limiter timeout**: If `acquire()` raises due to 10s timeout, the data function propagates the error as a transient failure, triggering retry logic (NFR-002). If all retries also timeout at the rate limiter, treat as non-critical endpoint failure.

## T. Testing Requirements

### Unit tests — Bybit data layer
- Bybit data fetching functions: mock HTTP responses for klines, funding, OI, ticker
- Bybit error handling: mock `retCode: 10001` response, verify function returns user-friendly error (not raw JSON)
- Pagination: (1) multi-page assembly (3 pages), (2) guard stops at 5 iterations, (3) empty last page
- Retry/backoff: mock 429 → verify 3 retries with increasing delay → graceful failure; mock 5xx → successful retry on 2nd attempt
- Crypto indicator computation from OHLCV DataFrame via stockstats

### Unit tests — Caching
- Second call with same params returns cached result without HTTP call
- Different params cause fresh HTTP call
- Cache not shared across analysis runs
- Cache hits do not consume rate-limit tokens
- Indicator cache: repeated indicator calls skip stockstats recomputation

### Unit tests — Rate limiter
- Token bucket refill behavior
- Blocking when exhausted, timeout exception after 10s
- Thread safety under concurrent access (multi-threaded test)

### Unit tests — Signal validation (FR-020)
- Valid Long signal passes: SL < entry < TP, confidence in [1,10], leverage <= cap
- Valid Short signal passes: TP < entry < SL
- Invalid Long rejected: SL > entry
- Confidence outside [1,10] rejected
- Leverage exceeding max_leverage_cap rejected
- Invalid signal retried once then flagged with warning
- "No Trade" signal with null price fields passes validation

### Unit tests — Security
- `bybit_api_secret` never returned by GET /config
- API key masked in responses (first 4 chars + "***")
- Log scrubbing strips sensitive params from URLs before logging
- HMAC signing produces correct signature per Bybit spec
- PATCH rejects partial credential updates (key without secret) with 422

### Unit tests — Schema validation
- Crypto symbol: valid (BTCUSDT, ETHUSDT), invalid ("BTC.USDT", "btcusdt", "", "A", >20 chars, "BTC-USDT", "BTC^USDT")
- model_validator: crypto analysts rejected in stock mode, stock analysts rejected in crypto mode
- interval ignored in stock mode

### Unit tests — Crypto analyst agents
- Crypto analyst prompts verify correct tool binding
- Crypto news analyst uses existing news tools with crypto context

### Integration tests
- Crypto analysis request through API → validates request accepted, run created with asset_type="crypto"
- End-to-end signal validation (with mocked LLM): verify final output contains all FR-008 fields and passes FR-020 validation
- Stock analysis completely unaffected (AC-003, AC-013)

### Frontend tests
- Automated component test (React Testing Library): render ConfigForm, toggle to crypto, assert crypto analysts shown and stock options hidden
- Manual verification scenarios: (1) toggle to crypto hides fundamentals analyst, shows crypto analysts, (2) toggle back restores stock options, (3) crypto analysts appear correctly, (4) mode toggle resets form fields, (5) interval selector visible in crypto mode only

## U. Acceptance Criteria

```
AC-001: Given asset_type="crypto" and symbol="BTCUSDT", when analysis starts, then Bybit API is called for OHLCV data and results include kline data.
AC-002: Given a crypto analysis, when the trader agent produces output, then it includes ALL FR-008 fields: trade type, entry price, exit price, at least 1 SL with price, at least 1 TP with price, confidence level, position size %, leverage recommendation, risk/reward ratio, and time horizon.
AC-003: Given asset_type="stock", when analysis runs, then behavior is identical to before this feature.
AC-004: Given the frontend in crypto mode, when user views the form, then stock-specific options (fundamentals analyst, stock data vendors) are hidden, and crypto analysts (crypto_technical, crypto_derivatives, crypto_news) are shown.
AC-005: Given optional Bybit API key in config, when crypto analysis runs, then signed requests are used for Bybit API calls.
AC-006: Given an invalid crypto symbol, when analysis runs, then the system fails gracefully with an appropriate error message.
AC-007: Given a crypto analysis completes, when user views the dashboard, then the report shows the portfolio manager's full output including: trade direction, entry zone, SL levels, TP levels, max leverage, confidence score, key risk factors, invalidation criteria, and market regime assessment.
AC-008: Given a crypto analysis, when the risk debate agents produce output, then it addresses at minimum: funding rate impact, liquidation risk at recommended leverage, and open interest trend analysis.
AC-009: Given a date range exceeding 200 klines, when the system fetches Bybit data, then it paginates to retrieve the full range (up to 1000 candles).
AC-010: Given Bybit API is unreachable, when analysis runs, then the system retries 3 times with backoff and fails gracefully with "Bybit API unavailable" error.
AC-011: Given the trader outputs "No Trade", when user views dashboard, then "No Trade Recommended" is displayed with reasoning and signal price fields are omitted.
AC-012: Given NO Bybit API key configured, when crypto analysis runs, then unsigned requests are used and analysis succeeds normally.
AC-013: Given the existing stock test suite, when crypto feature is merged, then all stock tests pass unchanged.
AC-014: Given the trader's signal output, when validated, then SL < entry < TP (for Long), confidence in [1,10], leverage <= max_leverage_cap.
AC-015: Given asset_type="crypto", when the derivatives analyst runs, then Bybit funding rate API is called and results include funding rate history.
AC-016: Given asset_type="crypto", when the derivatives analyst runs, then Bybit open interest API is called and results include OI data.
AC-017: Given asset_type="crypto", when the technical analyst runs, then Bybit ticker API is called and results include 24h statistics.
AC-018: Given asset_type="crypto", when the technical analyst runs, then technical indicators (RSI, MACD, Bollinger) are computed from OHLCV data.
AC-019: Given a crypto analysis with default 200-candle lookback, when data gathering executes, then the total data gathering phase completes within 30 seconds.
```

## V. Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Bybit API rate limiting during analysis | Medium | Medium | Cache responses within run, add retry with backoff |
| Bybit API changes or deprecation | Low | Low | Abstract behind vendor interface, easy to swap |
| Crypto news quality (not crypto-specific) | Medium | Medium | Use general news tools with crypto-focused prompts initially |
| LLM hallucinating specific price levels | Medium | High | Provide current price data to agents, prompt for evidence-based levels |
| stockstats incompatibility with crypto OHLCV | Low | Low | stockstats works with any OHLCV DataFrame |

## W. Assumptions

```
A-001:
Assumption: Bybit public API endpoints are stable and free to use without authentication for market data.
Risk level: Low
Reason: Bybit's public API has been stable for years, documented at bybit-exchange.github.io.
Impact if incorrect: Would need to require API keys or use alternative data source.

A-002:
Assumption: The existing stockstats library can compute technical indicators from Bybit OHLCV data.
Risk level: Low
Reason: stockstats works with any pandas DataFrame with open/high/low/close/volume columns.
Impact if incorrect: Would need a different indicator library.

A-003:
Assumption: Crypto symbols on Bybit use the format SYMBOLUSDT (e.g., BTCUSDT, ETHUSDT) for linear perpetuals.
Risk level: Low
Reason: This is Bybit's standard naming convention for linear contracts.
Impact if incorrect: Would need symbol format mapping.

A-004:
Assumption: The LLM can produce actionable trading signals (entry/exit/SL/TP) when given sufficient market data.
Risk level: Medium
Reason: Quality depends on LLM reasoning and data quality.
Impact if incorrect: Signals may be too generic; would need structured output enforcement.
```

## X. Open Questions

```
Q-001:
Question: Should crypto news use existing yfinance/Alpha Vantage news (searching for "Bitcoin" etc.) or integrate a crypto-specific news API?
Why it matters: Crypto-specific news (CoinTelegraph, The Block) may be more relevant than general financial news.
Recommended default: Start with existing news tools using crypto-adapted prompts; add crypto news API later.
Impact if unanswered: News quality may be lower for crypto initially.

Q-002:
Question: Should the analysis date for crypto default to "today" since crypto markets are 24/7?
Why it matters: Unlike stocks, there's no concept of "last trading day" for crypto.
Recommended default: Keep the date picker but default it to today for crypto.
Impact if unanswered: Minor UX friction.
```

## Y. Traceability Matrix

| Requirement | Spec Section | Files Affected | Tests | Acceptance Criteria |
|-------------|-------------|----------------|-------|-------------------|
| FR-001 | F, K | schemas.py, analysis_service.py, default_config.py | Unit, Integration | AC-003 |
| FR-002 | F, M | bybit_data.py, interface.py | Unit | AC-001 |
| FR-003 | F, M | bybit_data.py | Unit | AC-015 |
| FR-004 | F, M | bybit_data.py | Unit | AC-016 |
| FR-005 | F, M | bybit_data.py | Unit | AC-017 |
| FR-006 | F, M | bybit_data.py | Unit | AC-018 |
| FR-007 | F, M | crypto_analysts.py, setup.py | Unit | AC-001 |
| FR-008 | F, M | agent prompts, graph setup | Unit | AC-002, AC-007 |
| FR-009 | F, M | risk agent prompts | Unit | AC-007 |
| FR-010 | F, M | portfolio manager prompts | Unit | AC-007 |
| FR-011 | F | All modified files | Integration | AC-003 |
| FR-012 | L | ConfigForm.tsx | Manual | AC-004 |
| FR-013 | L | ConfigForm.tsx | Manual | AC-004 |
| FR-014 | K, P | config_service.py, default_config.py | Unit | AC-005 |
| FR-015 | K, S | schemas.py | Unit | AC-006 |
| FR-016 | F, M | crypto_analysts.py | Unit | AC-001 |
| FR-017 | F, M | bybit_data.py | Unit | AC-009 |
| FR-018 | F, K | schemas.py | Unit | AC-006 |
| FR-019 | F, M | agent prompts, graph setup | Unit | AC-002 |
| FR-020 | F, M | graph setup, signal validation | Unit | AC-014 |
| FR-021 | F, K | default_config.py, schemas.py, ConfigForm.tsx | Unit, Manual | AC-001 |
| FR-022 | F, M | default_config.py, signal validation | Unit | AC-014 |
| FR-023 | F, M | agent prompts, bybit_data.py | Unit | AC-007 |
| FR-024 | F, L | agent prompts, ReportPanel.tsx | Unit, Manual | AC-011 |
| FR-025 | F, M | bybit_data.py, crypto_agent_utils.py | Unit | AC-001 |

