# TradingAgents Backend API & Frontend Discovery Report

## 1. Bybit Coin/Ticker Listing

### Current Implementation
Location: tradingagents/dataflows/bybit_data.py (lines 130-200)

Functions Available:
- **_fetch_valid_symbols()** (lines 138-167): Fetches all valid linear perpetual symbols from Bybit
  - Uses Bybit V5 API: https://api.bybit.com/v5/market/instruments-info
  - Category: "linear" (perpetual futures)
  - Pagination with cursor (limit 1000/page)
  - Returns set of symbols (e.g., "BTCUSDT", "ETHUSDT")

- **get_valid_symbols()** (lines 170-182): Cached wrapper with 1-hour TTL
  - Thread-safe with global lock
  - Cache TTL: 3600 seconds

- **normalize_bybit_symbol(symbol)** (lines 190-200):
  - Validates against cached list
  - Auto-prefixes with "1000" for low-price tokens

Key Details:
- Rate Limiter: Token bucket (80 capacity, 16 tokens/sec)
- Circuit Breaker: 3 failure threshold
- Session: Singleton HTTP session
- NO HTTP ENDPOINT YET - symbols only fetched internally

What's Missing:
- No GET /api/v1/symbols or /api/v1/tickers endpoint
- No frontend component for browsing tickers
- No watchlist/favorites

---

## 2. Analysis Creation & Parallel Handling

### POST /api/v1/analysis
Location: backend/routers/analysis.py (lines 36-55)

Request Schema (AnalysisRequest):
- ticker: str (required, validated regex)
- analysis_date: str (required, YYYY-MM-DD, not future)
- asset_type: Optional[str] = "stock" or "crypto"
- interval: Optional[str] = required for crypto ("15", "60", "240", "D")
- provider: Optional[str] = LLM provider
- deep_think_llm: Optional[str] = model ID
- quick_think_llm: Optional[str] = model ID
- analysts: Optional[List[str]] = analyst types
- research_depth: Optional[int] = 1-5
- output_language: Optional[str]
- data_vendors: Optional[Dict[str, str]]

Response:
- run_id: str (UUID)
- status: "running"

### Concurrency Control
Location: backend/services/analysis_service.py (lines 26-29, 48-86)

Limits:
- MAX_CONCURRENT = 10 (max simultaneous analyses)
- MAX_ZOMBIES = 3
- WALL_TIMEOUT = 30 min
- HARD_TIMEOUT = 35 min

How it works:
1. Active runs tracking via Dict
2. Async lock for concurrent checks
3. Per-run threading.Event() for cancellation
4. ConcurrencyLimitError if limits exceeded (HTTP 429)

Database: analysis_runs table
- run_id, ticker, analysis_date, status, config, started_at, completed_at, asset_type
- Indices: (ticker, date), (status, started_at DESC), (asset_type, started_at DESC)

---

## 3. Frontend Analysis Form & Routes

### Route: /analysis/new
Location: frontend/src/routes/route-tree.tsx (lines 24-29)
Renders ConfigForm component

### ConfigForm Component
Location: frontend/src/components/analysis/ConfigForm.tsx (~750 lines)

Form Fields:
1. Asset Type: Toggle (Stock vs Crypto)
2. Ticker Input:
   - Stock regex: ^[A-Z0-9.\-^]{1,15}$
   - Crypto regex: ^[A-Z0-9]{2,20}$
   - Auto-uppercase
   - PLAIN TEXT ONLY - NO SUGGESTIONS

3. Analysis Date: HTML date picker (max today)
4. LLM Provider: Dropdown (env default)
5. Deep/Quick Models: Conditional dropdown or text
6. Research Depth: Slider 1-5 (stock only)
7. Output Language: Presets + custom
8. Data Sources: Category dropdowns (stock only)

Form Persistence:
- LocalStorage key: "tradingagents_settings"
- Auto-loaded on mount

Current Issues:
- No autocomplete for ticker
- No suggestions from Bybit
- No quick access to favorites/recent
- User must know valid tickers

---

## 4. Watchlist/Groups/Favorites

Current State: DOES NOT EXIST

- No watchlist table
- No API endpoints
- No frontend UI
- No storage mechanism

Opportunity: Could add table:
  watchlist (id, ticker, asset_type, group_name, created_at, last_used_at)

---

## 5. Frontend API Client

Location: frontend/src/api/client.ts (~250 lines)

Base Configuration:
- BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ""
- DEFAULT_TIMEOUT = 30 seconds
- CSRF header: X-Requested-With: XMLHttpRequest

Main Methods:
- listAnalyses(params?, signal?)
- startAnalysis(body)
- getAnalysis(runId, signal?)
- cancelAnalysis(runId)
- deleteAnalysis(runId)
- deleteAllAnalyses()
- getReport(runId, signal?)
- getSnapshot(runId, signal?)
- getConfig(signal?)
- updateConfig(overrides)
- getMemory(params?, signal?)
- getCheckpoint(ticker, date, signal?)
- deleteAllCheckpoints()
- deleteTickerCheckpoints(ticker)

Types:
- type AssetType = "stock" | "crypto"
- type CryptoInterval = "15" | "60" | "240" | "D"
- interface StartAnalysisRequest
- interface AnalysisListItem
- interface AnalysisSnapshot

---

## 6. Backend Router Structure

All routes use /api/v1/ prefix

Analysis Routes:
- POST /analysis
- GET /analysis (with filters)
- GET /analysis/{run_id}
- POST /analysis/{run_id}/cancel
- DELETE /analysis/{run_id}
- DELETE /analysis
- GET /analysis/{run_id}/report
- GET /analysis/{run_id}/snapshot

Other Routes:
- GET /config, PATCH /config
- GET /models/{provider}, GET /providers
- GET /memory
- GET /checkpoints, DELETE /checkpoints/{ticker}
- WS /ws (live stream)
- GET /health

---

## 7. Database Schema (v3)

analysis_runs table:
- run_id (PK)
- ticker, analysis_date, status, config, started_at, completed_at, error
- asset_type (stock or crypto)
- instance_id

report_sections table:
- id (PK), run_id (FK), section, content, created_at

Indices for performance optimization

---

## Summary Table

| Feature | Exists | Location |
|---------|--------|----------|
| Bybit symbol fetch | YES | tradingagents/dataflows/bybit_data.py |
| Bybit HTTP endpoint | NO | - |
| Analysis creation | YES | backend/routers/analysis.py |
| Concurrency control | YES | backend/services/analysis_service.py |
| ConfigForm | YES | frontend/src/components/analysis/ConfigForm.tsx |
| Ticker autocomplete | NO | - |
| Watchlist/favorites | NO | - |
| Ticker suggestions | NO | - |

Strong Foundation:
- Bybit integration with symbol caching built
- Multi-agent analysis with concurrency
- Web backend with security (CSRF, CSP)
- React frontend with state management

Key Gaps:
- No ticker discovery in UI
- No watchlist feature
- Manual ticker entry required

Opportunity: Implement watchlist + autocomplete using existing Bybit infrastructure
