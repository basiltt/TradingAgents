# Bybit Crypto Futures Analysis — Implementation Plan

## A. Metadata

- **Plan name**: Bybit Crypto Futures Analysis
- **Date**: 2026-05-03
- **Author**: Claude (AI agent)
- **Status**: Draft
- **Spec file**: `specs/crypto-futures-analysis-spec.md`
- **Version**: 1.0

## B. Planning Summary

- **What**: Add crypto futures analysis via Bybit public API alongside existing stock analysis
- **Why**: Users want crypto futures signals (entry/SL/TP/leverage) using the multi-agent framework
- **Approach**: Add Bybit data layer → crypto tools → crypto analysts → graph wiring → backend API changes → frontend toggle → tests
- **Key files**: `bybit_data.py` (new), `crypto_agent_utils.py` (new), `crypto_analysts.py` (new), `schemas.py`, `default_config.py`, `trading_graph.py`, `setup.py`, `ConfigForm.tsx`, `persistence.py`
- **Key risks**: LLM signal quality, Bybit API rate limits, cache/concurrency complexity
- **Assumptions**: Bybit public API stable, stockstats works with crypto OHLCV, single-worker deployment
- **V1 Limitations (out of scope)**: Order execution, live price streaming, multi-exchange support, alerts/notifications, backtesting, multi-timeframe analysis (single interval per run), portfolio tracking. Multi-timeframe is a future enhancement — V1 uses one interval to keep the data layer and caching simple.
- **Cancel**: Crypto analysis inherits existing cancel mechanism (POST /analysis/{run_id}/cancel). No new cancel logic needed.

## C. Source Specification Reference

- **Spec path**: `specs/crypto-futures-analysis-spec.md`
- **Spec version**: 1.0 (post-review)
- **Requirement IDs**: FR-001 through FR-025, NFR-001 through NFR-008, AC-001 through AC-019

## D. Implementation Strategy

- **Overall approach**: Bottom-up — data layer first, then tools, then agents, then graph wiring, then backend API, then frontend, then integration tests
- **Architecture alignment**: Follows existing patterns — `@tool` decorators, agent functions, `ToolNode` binding, vendor-style data functions
- **Existing patterns reused**: `ToolNode` creation, `GraphSetup.setup_graph()`, Pydantic schemas, React Query, WebSocket state
- **New patterns**: `functools.partial` for cache binding, module-level rate limiter singleton, `model_validator` for cross-field validation
- **Dependency order**: Data layer → Tools → Analysts → Graph → Backend → Frontend
- **Phases**: 5 phases, each independently testable and committable

### Architecture Decisions (from spec review — Decided Log)

- **D-002/D-003 — Crypto tools call Bybit directly, NOT via `route_to_vendor()`**: The existing `VENDOR_METHODS` in `interface.py` is stock-specific (yfinance, polygon, etc.). Crypto tools live in `crypto_agent_utils.py` and call `bybit_data.py` functions directly. This avoids polluting the stock vendor abstraction. If future crypto exchanges are added, a `route_to_crypto_vendor()` can be introduced then.
- **D-026 — Cache binding via `functools.partial`, not LangGraph state**: `@tool` functions cannot access graph state. Cache dict is created per-graph instantiation and bound into tools via `functools.partial`.
- **D-027 — `get_bybit_indicators` internally calls `get_bybit_klines` cache-first**: Indicators are self-sufficient; callers don't need to pre-fetch klines.

### Threading Model

- **Rate limiter uses `threading.Condition`** — acquire() checks token availability; if insufficient, releases the lock via `Condition.wait(timeout)` to avoid convoy effect. Other threads can check and acquire tokens while one thread waits for refill. All Bybit HTTP calls happen in worker threads (via `asyncio.to_thread()`), not the async event loop.
- **Cache dict is a plain `dict`** — safe because LangGraph executes analyst nodes sequentially within a single graph run. Parallel node execution within a single run is not used. Each run gets its own cache dict, so cross-run concurrency is not an issue. Max expected size: ~4 intervals x 2 entries (klines + indicators) x ~100KB = <1MB per run — no LRU needed.

## E. Phase Breakdown

### Phase 1: Bybit Data Layer + Rate Limiter + Tests
**Goal**: Standalone Bybit API client with caching, rate limiting, pagination, retry
**Scope**: FR-002 through FR-006, FR-017, FR-021, FR-025, NFR-001 through NFR-008
**Files**: Create `tradingagents/dataflows/bybit_data.py`, create `tests/test_bybit_data.py`
**Completion**: All Bybit data functions work with mock HTTP, rate limiter tested, pagination tested

### Phase 2: Crypto Tools + Analysts + Signal Validation
**Goal**: LangChain `@tool` functions, crypto analyst agents, signal validation logic
**Scope**: FR-007, FR-008, FR-009, FR-010, FR-019, FR-020, FR-022, FR-024
**Files**: Create `tradingagents/agents/utils/crypto_agent_utils.py`, create `tradingagents/agents/crypto_analysts.py`, create `tradingagents/agents/utils/signal_validation.py`, create tests
**Completion**: Tools callable, analysts produce output, signal validation works

### Phase 3: Graph Wiring + Config + Backend API
**Goal**: Wire crypto analysts into LangGraph, add asset_type to config/API, DB migration
**Scope**: FR-001, FR-011, FR-012 (backend), FR-014, FR-015, FR-018, FR-023
**Files**: Modify `trading_graph.py`, `setup.py`, `propagation.py`, `default_config.py`, `schemas.py`, `persistence.py`, `analysis_service.py`, `analysis.py` router
**Completion**: Crypto analysis request accepted and routed through crypto pipeline

### Phase 4: Frontend Changes
**Goal**: Asset type toggle, crypto form fields, Bybit credentials UI, interval selector
**Scope**: FR-012, FR-013, FR-024 (dashboard), L section UI reqs
**Files**: Modify `ConfigForm.tsx`, `client.ts`, config page components
**Completion**: Frontend shows crypto mode, submits crypto analysis requests

### Phase 5: Integration Tests + Manual Verification
**Goal**: End-to-end validation, stock regression, signal schema validation
**Scope**: AC-001 through AC-019, integration tests, manual verification
**Files**: Create integration tests, update existing test suites
**Completion**: All ACs pass, stock tests unaffected

## F. Task Breakdown

### Phase 1 Tasks

```
TASK-001: Create BybitRateLimiter singleton
Requirements: NFR-006
Description: Create `tradingagents/dataflows/bybit_data.py` with module-level `BybitRateLimiter` class using threading.Condition and token bucket algorithm. 80 tokens per 5s window, gradual refill at 16 tokens/second. acquire() releases lock during sleep via Condition.wait() to avoid convoy effect. Blocks up to 10s total, raises TimeoutError. Configure `requests.Session` with timeout=(5, 30) — 5s connect, 30s read. Mount `HTTPAdapter(pool_connections=1, pool_maxsize=5, max_retries=0)` for `https://` to ensure connection reuse to `api.bybit.com` across concurrent threads (retries handled at application level, not urllib3). Session is module-level singleton (thread-safe by urllib3 design).
Files: Create `tradingagents/dataflows/bybit_data.py`
Tests: Unit tests — token refill (gradual, 16/s), blocking, 10s timeout, thread safety, concurrent contention (spawn 10 threads each calling acquire(); assert total acquired == 10; assert elapsed > bucket_capacity/refill_rate proves blocking occurred; assert no token over-issuance via atomic counter)
Worst-case budget (3 concurrent runs): 3 runs x ~8 HTTP calls each = 24 calls burst. At 16 tokens/s refill, all complete within ~2s. With max pagination (3 runs x 5 kline pages + 3 non-critical each = 24 calls), fits within 10s acquire timeout.
Logging: emit logger.warning when acquire() blocks > 1s. Log each retry attempt with status code and backoff duration.
Also add a `BybitCircuitBreaker` class (simple consecutive-failure counter, not a full library): trips after 3 consecutive HTTP failures (connection error, timeout, 5xx). Once tripped, immediately raises `BybitUnavailableError` for subsequent calls, preventing wasted 45s deadline waits across multiple analyst nodes. Resets on N consecutive successes (N=1). Thread-safe via threading.Lock. **Per-graph-run instance** (passed alongside cache dict via functools.partial binding, NOT module-level singleton) — this ensures Run A's success doesn't reset Run B's tripped breaker.
Verification: `pytest tests/test_bybit_data.py -k rate_limiter`
AC: N/A (internal component)

TASK-002: Create get_bybit_klines with pagination
Requirements: FR-002, FR-017, FR-021, NFR-001, NFR-002, NFR-005
Description: In `bybit_data.py`, add `get_bybit_klines(symbol, interval, start_time, end_time, cache=None)` that:
  - First, create a private helper `_bybit_request(endpoint, params, cache_key, cache, deadline)` that encapsulates: cache lookup, rate limiter acquire (skip on cache hit), HTTP GET with remaining deadline as timeout, retry with exponential backoff on 429/5xx (max 3 retries), deadline check before each retry, retCode validation, response parsing. All public data functions (klines, funding, OI, ticker) call this helper.
  - Calls GET /v5/market/kline with category=linear, parameterized query params
  - Paginates: set end = min(prev_page_timestamps) - 1, terminate when rows < 200 or 5 iterations or >= max candles or min(timestamps) unchanged from previous page (dedup guard). Collect rows into a list and join once at the end (`"\n".join(rows)`) — do NOT use incremental string concatenation.
  - Retry with exponential backoff on 429/5xx (max 3 retries), but abort retries if cumulative wall time exceeds 45s per tool call
  - 30s HTTP timeout per request (via Session timeout=(5,30) from TASK-001)
  - Enforce via monotonic deadline: `deadline = time.monotonic() + 45` checked before each pagination iteration AND retry. ALL HTTP requests (not just the final one) use `min(configured_timeout, deadline - now)` as their timeout. Retry loops check `deadline - now > 0` before attempting. This prevents deadline overrun on any request in the chain.
  - Rate limiter acquire() before each HTTP call (cache hits skip acquire)
  - Cache key: ("klines", symbol, interval, start, end)
  - Returns CSV string of OHLCV data (matching existing yfinance pattern)
  - On retCode != 0: raise descriptive error
Files: Modify `tradingagents/dataflows/bybit_data.py`
Tests: Mock HTTP → verify single page, multi-page (3 pages), guard at 5, dedup guard (mock identical timestamps across 2 consecutive pages → assert pagination terminates without hitting iteration cap), retCode error, retry on 429, cache hit skips HTTP, malformed JSON response (non-JSON body, missing retCode, missing result.list), deadline enforcement (mock slow responses exceeding 45s cumulative → assert pagination aborts)
Verification: `pytest tests/test_bybit_data.py -k klines`
AC: AC-001, AC-009

TASK-003: Create get_bybit_funding_rates
Requirements: FR-003, NFR-001, NFR-002, NFR-005
Description: Add `get_bybit_funding_rates(symbol, start_time, end_time, cache=None)` to `bybit_data.py`.
  - Calls GET /v5/market/funding/history with category=linear
  - Cache key: ("funding", symbol, start, end)
  - Returns formatted string with funding rate history
  - Same retry/timeout/rate-limiter pattern as klines
Files: Modify `tradingagents/dataflows/bybit_data.py`
Tests: Mock HTTP → verify normal response, empty response, error response, malformed JSON response
Verification: `pytest tests/test_bybit_data.py -k funding`
AC: AC-015

TASK-004: Create get_bybit_open_interest
Requirements: FR-004, NFR-001, NFR-002, NFR-005
Description: Add `get_bybit_open_interest(symbol, interval, start_time, end_time, cache=None)` to `bybit_data.py`.
  - Calls GET /v5/market/open-interest with category=linear
  - Cache key: ("oi", symbol, interval, start, end)
  - Returns formatted string with OI data
Files: Modify `tradingagents/dataflows/bybit_data.py`
Tests: Mock HTTP → verify normal, empty, error, malformed JSON
Verification: `pytest tests/test_bybit_data.py -k open_interest`
AC: AC-016

TASK-005: Create get_bybit_ticker
Requirements: FR-005, NFR-001, NFR-002, NFR-005
Description: Add `get_bybit_ticker(symbol, cache=None)` to `bybit_data.py`.
  - Calls GET /v5/market/tickers with category=linear
  - Cache key: ("ticker", symbol) — no time component. **V1 accepted limitation**: ticker data may be up to 2-5 minutes stale within a single graph run (fetched once early, served from cache for all subsequent tool calls). This is acceptable because (a) the LLM report is advisory, not auto-executed, and (b) adding TTL would complicate cache logic for marginal accuracy gain. Document in final report that prices are point-in-time snapshots.
  - Returns formatted string with 24h stats (price, volume, funding, OI, etc.)
Files: Modify `tradingagents/dataflows/bybit_data.py`
Tests: Mock HTTP → verify normal, error, malformed JSON
Verification: `pytest tests/test_bybit_data.py -k ticker`
AC: AC-017

TASK-006: Create get_bybit_indicators
Requirements: FR-006, NFR-008
Description: Add `get_bybit_indicators(symbol, interval, start_time, end_time, cache=None)` to `bybit_data.py`.
  - Internally calls get_bybit_klines (cache-first) for self-sufficiency
  - Parses CSV to DataFrame, computes RSI, MACD, Bollinger, EMA via stockstats
  - Cache key: ("indicators", symbol, interval, start, end)
  - Returns formatted string of indicator values
Files: Modify `tradingagents/dataflows/bybit_data.py`
Tests: Mock klines → verify indicators computed, verify cache prevents recomputation
Verification: `pytest tests/test_bybit_data.py -k indicators`
AC: AC-018

TASK-007: Add HMAC signing support (optional)
Requirements: FR-014, NFR-003
Description: Add `_sign_request(params, api_key, api_secret)` helper to `bybit_data.py`.
  - Adds timestamp, api_key, recv_window=5000 to params, computes HMAC-SHA256 sign. **Critical**: timestamp MUST be generated AFTER rate limiter acquisition (immediately before HTTP send), not before — otherwise a 10s rate limiter wait can cause recv_window expiry on the server side.
  - api_secret NEVER transmitted, only used for local computation
  - All data functions accept optional api_key/api_secret params; if provided, requests are signed
  - Log scrubbing: strip api_key, api_secret, sign, timestamp from URLs BEFORE logging
Files: Modify `tradingagents/dataflows/bybit_data.py`
Dependencies: TASK-001 (uses rate limiter for signed requests)
Tests: Verify HMAC signature correctness, verify api_secret never in request params, verify log scrubbing, verify secret not leaked in error messages or tracebacks
Verification: `pytest tests/test_bybit_data.py -k hmac`
AC: AC-005, AC-012

TASK-008: Create comprehensive Phase 1 test file
Requirements: All Phase 1 NFRs and FRs
Description: Create `tests/test_bybit_data.py` with all unit tests from Section T of the spec.
Files: Create `tests/test_bybit_data.py`
Tests: Rate limiter (incl. concurrent contention, spurious wakeup safety, combined deadline+rate-limiter interaction: acquire takes 3s, deadline has 2s remaining → verify TimeoutError from deadline not from limiter), klines pagination, funding, OI, ticker, indicators, HMAC, retry, caching, error handling, malformed JSON responses, tool 30s timeout verification (mock slow response → verify TimeoutError), log scrubbing (capture logging output during credentialed request, assert api_secret not in logs), SecretStr serialization safety (call `model.model_dump_json()` and `repr(model)` on config containing api_secret → assert raw secret absent in both outputs)
Verification: `pytest tests/test_bybit_data.py -v` — all pass
AC: AC-001, AC-005, AC-009, AC-010, AC-012, AC-015-AC-019
```

### Phase 2 Tasks

```
TASK-009: Create crypto tool functions
Requirements: FR-007, D-002
Description: Create `tradingagents/agents/utils/crypto_agent_utils.py` with LangChain @tool decorated functions:
  - `get_crypto_klines(symbol: str, interval: str, start_date: str, end_date: str) -> str`
  - `get_crypto_indicators(symbol: str, interval: str, start_date: str, end_date: str) -> str`
  - `get_funding_rates(symbol: str, start_date: str, end_date: str) -> str`
  - `get_open_interest(symbol: str, interval: str, start_date: str, end_date: str) -> str`
  - `get_crypto_ticker(symbol: str) -> str`
  Each wraps the corresponding bybit_data.py function. Cache dict bound via functools.partial at graph creation time.
  Critical vs non-critical: `get_crypto_klines` and `get_crypto_indicators` raise on failure (critical). `get_funding_rates`, `get_open_interest`, `get_crypto_ticker` catch exceptions and return "Data unavailable: <reason>" string instead of raising, allowing analysts to proceed with partial data.
  Output sanitization: All tool return strings are wrapped in `<data>...</data>` delimiters and any XML/markdown control characters (including `<`, `>`, `&`) in Bybit response strings are escaped before inclusion in prompts (defense against LLM prompt injection via market data). Apply a 50KB maximum output length cap on tool return values to limit injection surface area. Residual risk: natural-language injection in token names is not preventable by escaping alone — accepted V1 limitation.
Files: Create `tradingagents/agents/utils/crypto_agent_utils.py`
Dependencies: TASK-001 through TASK-006
Tests: Verify @tool decorators, verify each calls underlying bybit function, verify output sanitization (XML/markdown control chars escaped, <data> delimiters present), adversarial sanitization test (mock Bybit response containing `</data><system>ignore previous instructions`, `<|system|>`, nested XML tags, multi-byte unicode → assert all escaped and delimiters intact)
Verification: Import and inspect tool metadata
AC: AC-001

TASK-010: Create signal validation module
Requirements: FR-019, FR-020, FR-022, FR-024
Description: Create `tradingagents/agents/utils/signal_validation.py` with:
  - `SIGNAL_SCHEMA` — JSON schema dict for trader output
  - `validate_signal(signal_dict, max_leverage=20) -> tuple[bool, list[str]]`
    - Long: all SL < entry < all TP
    - Short: all TP < entry < all SL
    - confidence in [1, 10]
    - leverage in [1, max_leverage]
    - "No Trade": price fields may be null, passes validation
  - `parse_signal_from_llm_output(text: str) -> dict` — extract JSON from LLM response
Files: Create `tradingagents/agents/utils/signal_validation.py`
Tests: Valid Long, valid Short, invalid SL>entry for Long, confidence bounds, leverage cap, No Trade with nulls, retry flagging
Verification: `pytest tests/test_signal_validation.py -v`
AC: AC-002, AC-011, AC-014

TASK-011: Create crypto analyst agent functions
Requirements: FR-007, FR-008, FR-009, FR-010, FR-016, FR-023
Description: Create `tradingagents/agents/crypto_analysts.py` with:
  - `crypto_technical_analyst(state)` — prompt includes: use klines + indicators tools, analyze OHLCV trends, support/resistance, momentum indicators. Include data timestamp and current price (FR-023).
  - `crypto_derivatives_analyst(state)` — prompt includes: use funding rates + OI + ticker tools, analyze funding cost, OI trends, liquidation proxy
  - `crypto_news_analyst(state)` — imports and reuses `get_google_news`, `get_reddit_news` from `tradingagents/agents/utils/agent_utils.py`. Bound to same ToolNode mechanism. Prompt adapted for crypto context (search coin name, "Bitcoin futures", etc.). FR-016.
  - `crypto_trader(state)` — prompt includes: synthesize analyst reports into structured trading signal per SIGNAL_SCHEMA (FR-008). Must output JSON with trade_type, entry_price, stop_losses[], take_profits[], confidence, leverage. Invokes `validate_signal()` on output; if invalid, retry once with validation errors in prompt.
  - `crypto_risk_bull_debater(state)` and `crypto_risk_bear_debater(state)` — prompts adapted for crypto futures risk (liquidation risk, funding cost, leverage risk). FR-009.
  - `crypto_portfolio_manager(state)` — prompt adapted for futures position sizing, max leverage from config. FR-010.
  Each returns updated state with agent report.
Files: Create `tradingagents/agents/crypto_analysts.py`
Dependencies: TASK-009, TASK-010
Tests: Verify tool binding (news tools imported from agent_utils), verify prompts reference correct tools, verify state update, verify trader prompt includes SIGNAL_SCHEMA.
  test_crypto_trader_retry_on_invalid_signal: mock LLM returns invalid signal first, valid second; assert two LLM calls.
  test_crypto_trader_retry_exhausted: mock LLM returns invalid both times; assert error report in state (not exception).
  test_derivatives_analyst_with_unavailable_funding: bind tool returning "Data unavailable: timeout"; assert analyst report acknowledges missing data.
Verification: Import and check function signatures
AC: AC-001, AC-002, AC-007, AC-008

TASK-012: Create Phase 2 test files
Requirements: All Phase 2 FRs
Description: Create `tests/test_crypto_agent_utils.py`, `tests/test_signal_validation.py`, `tests/test_crypto_analysts.py`
Files: Create test files
Tests: All signal validation cases, tool decorator verification, analyst prompt verification
Verification: `pytest tests/test_signal_validation.py tests/test_crypto_agent_utils.py -v` — all pass
AC: AC-002, AC-011, AC-014
```

### Phase 3 Tasks

```
TASK-013: Update DEFAULT_CONFIG
Requirements: FR-001, FR-014, FR-021, FR-022, D-004, D-013, D-015
Description: Modify `tradingagents/default_config.py`:
  - Add "asset_type": "stock"
  - Add "crypto_interval": "60"
  - Add "crypto_max_leverage": 20
  - Add "exchange_credentials": {"bybit": {"api_key": None, "api_secret": None}}
  - **SecretStr boundary**: `api_secret` must be wrapped in Pydantic `SecretStr` at the PATCH handler boundary (before storing in config dict). `bybit_data.py` calls `.get_secret_value()` only at HMAC computation time. This ensures `repr(config)` and `str(config)` never expose the raw secret.
  - Add env var mapping: BYBIT_API_KEY → exchange_credentials.bybit.api_key, BYBIT_API_SECRET → exchange_credentials.bybit.api_secret. **Both paths** (env var and PATCH) must wrap api_secret in SecretStr before storing in config dict — the wrapping happens at ingestion, not just at the PATCH boundary.
Files: Modify `tradingagents/default_config.py`
Tests: Verify defaults present, verify env var mapping (key+secret set, partial set treated as incomplete, empty string treated as None, env var vs PATCH precedence)
Verification: Import and check DEFAULT_CONFIG
AC: AC-003 (stock unchanged)

TASK-014: Update Pydantic schemas
Requirements: FR-001, FR-015, FR-018, D-005
Description: Modify `backend/schemas.py`:
  - Add `CryptoAnalystType` enum: crypto_technical, crypto_derivatives, crypto_news (separate enum from existing `AnalystType`)
  - Add `CRYPTO_TICKER_RE = re.compile(r"^[A-Z0-9]{2,20}$")` alongside existing `TICKER_RE`
  - Add `asset_type: Optional[str] = "stock"` to AnalysisRequest
  - Add `interval: Optional[str] = None` to AnalysisRequest
  - `analysts` field type: keep as `Optional[List[str]] = None` (plain strings, not union enum). A `model_validator` enforces allowed values per asset_type: crypto requests accept only CryptoAnalystType values, stock requests accept only AnalystType values. This avoids Pydantic v2 `oneOf` OpenAPI schema breakage from union enums and maintains backward compatibility.
  - Add model_validator(mode="after"):
    - If asset_type="crypto": validate ticker against `CRYPTO_TICKER_RE`, validate analysts against CryptoAnalystType, validate interval in ["15","60","240","D"], interval required (not None)
    - If asset_type="stock": validate ticker against existing `TICKER_RE`, validate analysts against AnalystType, interval ignored
Files: Modify `backend/schemas.py`
Tests: Valid crypto request, invalid crypto symbol, stock analysts in crypto mode rejected, invalid interval
Verification: `pytest tests/test_schemas.py -v`
AC: AC-003, AC-006

TASK-015: Database migration V2
Requirements: FR-001, D-025
Description: Modify `backend/persistence.py`:
  - Add migration tuple: `(2, "ALTER TABLE analysis_runs ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))")`
  - Add index: `(3, "CREATE INDEX IF NOT EXISTS idx_runs_asset_type_started ON analysis_runs(asset_type, started_at DESC)")`
  - Update `insert_run()` to include `asset_type` in INSERT column list (uses DEFAULT 'stock' for stock requests — no explicit value needed)
  - Update `list_runs()` to accept optional `asset_type` filter parameter — MUST use parameterized query (`WHERE asset_type = ?`), never string interpolation
  - Each migration runs in its own `BEGIN IMMEDIATE` / `COMMIT` transaction with version updated atomically after success. If V2 succeeds but V3 fails, version=2 is committed and V3 retries on next startup. **Requires refactoring `_apply_migrations()`**: existing code uses single `BEGIN EXCLUSIVE` wrapping ALL pending migrations. Refactor to loop: for each pending migration → `BEGIN IMMEDIATE` → execute SQL → `PRAGMA user_version = N` → `COMMIT`. This replaces the current single-transaction approach.
  - Note: SQLite ALTER TABLE ADD COLUMN with NOT NULL DEFAULT is metadata-only (instant) on SQLite 3.37+. On 3.35-3.36 it performs a table rewrite under exclusive lock. Since this is a single-user desktop app with small tables, the rewrite is acceptable but add a startup assertion `sqlite3.sqlite_version_info >= (3, 35, 0)` and log a warning if < 3.37.
Files: Modify `backend/persistence.py`
Tests: Verify migration runs on fresh DB, verify INSERT stores asset_type, verify filter, verify parameterized query (test with malicious asset_type value), test_migration_partial_failure (V2 succeeds, simulate V3 failure, assert version=2, re-run, assert V3 succeeds and version=3)
Verification: Run migration, inspect schema
AC: AC-003

TASK-016: Wire crypto graph pipeline
Requirements: FR-007, FR-011, D-002, D-026, D-027
Description: Modify `tradingagents/graph/trading_graph.py`:
  - In `__init__`, check `config.get("asset_type", "stock")` — this is per-instantiation branching, NOT runtime.
    Each analysis request creates a NEW TradingAgentsGraph instance with the appropriate asset_type.
  - If "crypto": create cache dict (plain dict, one per instance), use functools.partial to bind cache into
    each crypto tool function, create ToolNode with bound crypto tools, pass crypto analyst functions to GraphSetup.
    The resulting graph contains ONLY crypto nodes — no stock analyst nodes are present.
  - If "stock": existing behavior unchanged — no crypto nodes, no cache dict, no Bybit imports.
  Modify `tradingagents/graph/setup.py`:
  - Add separate `setup_crypto_graph()` method (NOT conditional in existing `setup_graph()` — keep stock path untouched). `TradingAgentsGraph.__init__` dispatches to the correct setup method based on `asset_type`:
    Crypto graph has 3 analyst nodes (crypto_technical, crypto_derivatives, crypto_news) instead of 4 stock analysts.
    Researcher, trader, risk debaters, portfolio manager nodes reuse existing logic with crypto-aware prompts.
    The aggregation/debate nodes must gather analyst reports by iterating the analyst list (parameterized), NOT hardcoded to 4 reports. Crypto state has 3 report slots; debate prompts must enumerate only the reports present. Debate/aggregation functions accept a `report_keys: list[str]` parameter and prompt template uses join over available reports.
  - Crypto analyst nodes use crypto_analysts.py functions
  Modify `tradingagents/graph/propagation.py`:
  - `create_initial_state()` adds `asset_type` to state dict
Files: Modify `trading_graph.py`, `setup.py`, `propagation.py`, `tradingagents/agents/utils/agent_states.py`
Dependencies: TASK-009, TASK-011, TASK-013, TASK-014
Tests: Create graph with asset_type="crypto" → verify ONLY crypto tools bound (no stock tools), verify crypto analysts wired.
  Create graph with asset_type="stock" → verify unchanged (no crypto nodes). Two separate instantiations = two separate graphs.
  Verify AgentState TypedDict includes asset_type and crypto report keys.
Verification: Instantiate TradingAgentsGraph with crypto config, inspect nodes
AC: AC-001, AC-003
Note: WebSocket messages use same envelope as stock — agent names are display-only strings (e.g., "crypto_technical_analyst"). No new required fields or message types. Frontend renders agent names generically.
Note: Critical tool failures (klines/indicators raise) are caught inside analyst functions (try/except) which return an error report string to state, allowing the graph to terminate gracefully with a user-visible error. The graph does NOT crash on tool failure. Use a typed `error: Optional[str]` field in `AgentState` TypedDict (not a string sentinel prefix) for error propagation. When an analyst catches a critical failure, it sets `state["error"] = "description"`. Downstream nodes check `if state.get("error"):` and skip normal processing. The graph can also use a conditional edge that short-circuits to the final report node when error is set, eliminating the need for every node to independently check.

TASK-017: Update backend API
Requirements: FR-001, FR-011, FR-014
Description: Modify `backend/services/analysis_service.py`:
  - `_build_config()`: pass asset_type, interval from request to config
  - Handle exchange_credentials from config for Bybit API key
  Modify `backend/routers/analysis.py`:
  - Bybit doesn't need API key check (public API works without it)
  - Add asset_type to provider key validation skip (no key needed for crypto)
  - Pre-flight symbol check for crypto: call `await asyncio.to_thread(get_bybit_ticker, symbol)` before launching graph (must run in thread to avoid blocking event loop) with a 10s `asyncio.wait_for` timeout. If no data or retCode != 0, reject with 422 "Symbol not found on Bybit". If network unreachable / timeout, reject with 503 "Bybit API unavailable — try again later" (distinct from 422 so frontend can show appropriate message).
  Modify `backend/services/config_service.py`:
  - Handle exchange_credentials in config overrides (PATCH)
  - Mask api_key (last 4 chars: "***" + last 4), never return api_secret
  - Reject partial credential updates (both key+secret or neither)
  - Apply credentials as atomic dict replacement: `config["exchange_credentials"]["bybit"] = {"api_key": key, "api_secret": secret}` in one statement (no field-by-field update, no awaits between validation and assignment)
  - Always include exchange_credentials.bybit in GET response with shape {api_key: string|null, api_secret_configured: boolean}
  - Credential loss detection: if credentials were previously configured via PATCH but are now absent (server restart), the pre-flight check should log a warning and the WebSocket status stream should emit a warning-level message ("Bybit credentials were cleared by server restart — re-enter on Config page if authenticated endpoints needed"). This is best-effort UX; unsigned requests still work without credentials.
Files: Modify `analysis_service.py`, `analysis.py`, `config_service.py`
Tests: Verify crypto request accepted, verify config masking, verify partial credential rejection
Verification: Start server, POST crypto analysis request
AC: AC-003, AC-005, AC-012

TASK-018: Phase 3 tests
Requirements: All Phase 3 FRs
Description: Create/update test files for schemas, persistence, graph wiring, backend API
Files: Create `tests/test_schemas.py` (or update existing), update other test files
Tests: Schema validation (crypto/stock), migration, graph wiring, API endpoints, test_graph_critical_tool_failure (mock get_crypto_klines to raise RuntimeError; assert state["error"] is set; assert no unhandled exception; assert downstream trader node detects error field and propagates error instead of generating signal), test_credential_loss_warning (mock credentials previously set then absent; assert warning-level WebSocket message emitted), pre-flight symbol check (invalid symbol → 422, retCode != 0 from Bybit → 422 not 500, Bybit unreachable/timeout → 503 not 500)
Verification: `pytest tests/ -v` — all pass, stock tests unaffected
AC: AC-003, AC-006, AC-013
```

### Phase 4 Tasks

```
TASK-019: Update frontend API client
Requirements: FR-001
Description: Modify `frontend/src/api/client.ts`:
  - Add `asset_type?: "stock" | "crypto"` and `interval?: "15" | "60" | "240" | "D"` to `StartAnalysisRequest`
  - Add `asset_type?: "stock" | "crypto"` to `AnalysisRun` interface
  - Add `asset_type?: "stock" | "crypto"` filter to `listAnalyses` params
Files: Modify `frontend/src/api/client.ts`
Tests: TypeScript compilation
Verification: `npm run build`
AC: N/A (type changes)

TASK-020: Update ConfigForm with asset type toggle
Requirements: FR-012, FR-013
Description: Modify `frontend/src/components/analysis/ConfigForm.tsx`:
  - Add asset type radio group ("Stock" | "Crypto Futures") with ARIA attributes (role=radiogroup, role=radio, aria-checked)
  - Mode toggle resets: ticker, analysts, interval to mode defaults. Preserved across toggle: provider, model, language, date, research_depth.
  - Crypto mode: show crypto analysts (crypto_technical, crypto_derivatives, crypto_news), hide fundamentals, hide stock vendors
  - Crypto mode: show interval selector with visible "Timeframe" label (use shadcn/ui Select or Radix RadioGroup for accessibility). Options: [{label:"15m",value:"15"}, {label:"1h",value:"60"}, {label:"4h",value:"240"}, {label:"Daily",value:"D"}]
  - Crypto mode: ticker placeholder "e.g., BTCUSDT", label "Symbol", use `CRYPTO_TICKER_REGEX = /^[A-Z0-9]{2,20}$/` for frontend validation (switch regex based on asset_type)
  - Crypto mode: date picker defaults to today (24/7 market)
  - Crypto mode: default interval value "60" (1h) when mode first activated
  - Use Radix UI RadioGroup (from shadcn/ui) for asset type toggle — provides keyboard navigation and focus management without manual ARIA
  - Submit button disabled with spinner while request is in-flight (prevents double-submit)
  - On 503 response: show distinct message ("Bybit API is currently unavailable — please try again in a few minutes") with retry button, differentiated from 422 validation errors
  - Handle warning-level WebSocket messages: display a dismissible banner on the dashboard/config page (e.g., credential loss warning after server restart)
  - Submit includes asset_type and interval in request body
  - Add asset_type filter (tab or dropdown) to analysis history/list page, wired to `listAnalyses` query param. When crypto-filtered list is empty, show contextual empty state ("No crypto analyses yet — start one from the New Analysis page")
Files: Modify `frontend/src/components/analysis/ConfigForm.tsx`, modify `frontend/src/components/dashboard/HistoryList.tsx` (add asset_type filter tabs + empty state)
Tests: Automated React Testing Library test + manual verification
  - Warning banner: implement in a layout-level component (e.g., `AppLayout.tsx` or a shared `NotificationBanner.tsx` rendered at the router layout level) using React context or Zustand store for cross-page visibility. Warning-level WebSocket messages populate this store; the banner renders on all pages (dashboard, config, history). Add layout wrapper to Section G.
Verification: Start dev server, toggle modes, verify form changes
AC: AC-004

TASK-021: Update Config page with Bybit credentials
Requirements: FR-014
Description: Add Bybit credentials section to config page:
  - API Key field: read-only masked after save, "Edit" to clear and re-enter
  - API Secret password field: always masked
  - Status badge: "Configured" / "Not configured"
  - Info text: "Credentials are session-only and cleared on server restart. Use BYBIT_API_KEY/BYBIT_API_SECRET env vars for persistent configuration."
  - Inline validation: both fields required together
  - Save and Remove buttons with loading spinner while in-flight
  - Toast notification on success, inline error on failure (e.g., 422 partial credential rejection)
  - Confirmation dialog before Remove ("Are you sure?")
Files: Modify `frontend/src/components/config/ConfigPage.tsx`
Tests: Manual verification
Verification: Save credentials, verify masking, remove, verify status
AC: AC-005

TASK-022: Phase 4 frontend tests
Requirements: FR-012, FR-013
Description: Create automated component test for ConfigForm mode toggle
Files: Create `frontend/src/components/analysis/__tests__/ConfigForm.test.tsx`
Tests: Render, toggle to crypto, assert crypto analysts shown, stock options hidden, toggle back, assert restored. Also: crypto ticker regex rejects "AAPL." but accepts "BTCUSDT", interval selector renders only in crypto mode, submit payload includes asset_type and interval fields, submit button disabled while in-flight.
Verification: `npm test`
AC: AC-004
```

### Phase 5 Tasks

```
TASK-023: Integration tests
Requirements: All ACs
Description: Create integration test file:
  - Crypto analysis request → accepted with asset_type="crypto"
  - Stock analysis → unchanged behavior (stock regression: verify stock request still works identically, no crypto code paths triggered)
  - End-to-end signal validation (mocked LLM) → FR-008 fields present, FR-020 validation passes
  - Concurrent rate limiter contention under parallel requests
  - Integration timing: verify rate limiter + HTTP timeout budgets don't conflict (acquire 10s + HTTP 30s < reasonable total)
Files: Create `tests/test_integration_crypto.py`
Tests: API integration, signal schema validation
Verification: `pytest tests/test_integration_crypto.py -v`
AC: AC-001 through AC-019

TASK-024: Manual verification
Requirements: All ACs
Description: Manual test scenarios per Section N of plan:
  - Start crypto analysis (BTCUSDT), verify dashboard shows progress
  - Verify completed report shows trading signal with SL/TP/entry
  - Start stock analysis, verify unchanged behavior
  - Test invalid crypto symbol
  - Test Bybit credentials save/remove/masking
  - Verify No Trade output display
Verification: Manual walkthrough, screenshots
AC: AC-001 through AC-019
```

## G. File-Level Change Plan

| File | Action | Purpose | Tasks |
|------|--------|---------|-------|
| `tradingagents/dataflows/bybit_data.py` | Create | Bybit API client + rate limiter + cache | TASK-001 to TASK-007 |
| `tradingagents/agents/utils/crypto_agent_utils.py` | Create | Crypto @tool functions | TASK-009 |
| `tradingagents/agents/crypto_analysts.py` | Create | Crypto analyst agent functions | TASK-011 |
| `tradingagents/agents/utils/signal_validation.py` | Create | Signal schema + validation | TASK-010 |
| `tradingagents/default_config.py` | Modify | Add asset_type, crypto configs, credentials | TASK-013 |
| `tradingagents/graph/trading_graph.py` | Modify | Crypto graph factory, cache binding | TASK-016 |
| `tradingagents/graph/setup.py` | Modify | Crypto analyst node wiring | TASK-016 |
| `tradingagents/graph/propagation.py` | Modify | Add asset_type to initial state | TASK-016 |
| `tradingagents/agents/utils/agent_states.py` | Modify | Add asset_type + crypto report keys to AgentState TypedDict | TASK-016 |
| `backend/schemas.py` | Modify | CryptoAnalystType, model_validator | TASK-014 |
| `backend/persistence.py` | Modify | V2 migration, INSERT, list filter | TASK-015 |
| `backend/services/analysis_service.py` | Modify | Pass asset_type/interval to config | TASK-017 |
| `backend/routers/analysis.py` | Modify | Skip API key check for crypto | TASK-017 |
| `backend/services/config_service.py` | Modify | Credentials masking, PATCH atomicity | TASK-017 |
| `frontend/src/api/client.ts` | Modify | Add types | TASK-019 |
| `frontend/src/components/analysis/ConfigForm.tsx` | Modify | Asset type toggle, crypto form | TASK-020 |
| `frontend/src/components/dashboard/HistoryList.tsx` | Modify | Asset type filter tabs, empty state | TASK-020 |
| `frontend/src/components/ui/NotificationBanner.tsx` | Create | Cross-page warning banner (credential loss, etc.) | TASK-020 |
| Config page component (e.g., `frontend/src/components/config/ConfigPage.tsx`) | Modify | Bybit credentials UI | TASK-021 |
| `tests/test_bybit_data.py` | Create | Bybit data layer tests | TASK-008 |
| `tests/test_signal_validation.py` | Create | Signal validation tests | TASK-012 |
| `tests/test_crypto_agent_utils.py` | Create | Crypto tool tests | TASK-012 |
| `tests/test_crypto_analysts.py` | Create | Crypto analyst + trader tests | TASK-012 |
| `tests/test_integration_crypto.py` | Create | Integration tests | TASK-023 |

## H. API Change Plan

| Endpoint | Change | Backward Compat |
|----------|--------|-----------------|
| POST /api/v1/analysis | Add asset_type, interval fields (optional, defaults preserve stock behavior) | Yes — omitting fields = stock mode |
| GET /api/v1/analysis/{run_id} | Response includes asset_type, interval | Yes — new fields only |
| GET /api/v1/analysis | Add optional asset_type filter param | Yes — omitting = all |
| GET /api/v1/config | Response includes exchange_credentials.bybit | Yes — new key only |
| PATCH /api/v1/config | Accept exchange_credentials.bybit, atomicity enforced | Yes — existing keys unchanged |

## I. Database/Migration Plan

- **Migration V2**: `ALTER TABLE analysis_runs ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))`
- **Migration V3**: `CREATE INDEX IF NOT EXISTS idx_runs_asset_type_started ON analysis_runs(asset_type, started_at DESC)`
- **Registration**: Add `(2, '<SQL>')` and `(3, '<SQL>')` to `_MIGRATIONS` list in `persistence.py`
- **INSERT update**: Add `asset_type` to `insert_run()` column list
- **Rollback**: Column stays permanently — backward compatible, old code ignores it
- **Test**: Verify fresh DB creation, verify upgrade from V1

## J. Frontend Implementation Plan

- **ConfigForm.tsx**: Asset type radio group (accessible), conditional rendering for crypto/stock modes, form reset on toggle
- **Config page**: Bybit credentials section with masking, validation, save/remove
- **API client**: Updated types for asset_type, interval
- **UI states**: Loading (existing skeleton), error (existing error handling), crypto-specific analyst labels
- **Report display**: Crypto reports render through existing ReportPanel (markdown). The trading signal (entry/SL/TP/confidence/leverage) is part of the markdown report generated by the portfolio manager. "No Trade" signals render with the same markdown flow — the report text says "No Trade" with reasoning. No special signal-parsing component needed since the report is LLM-generated prose/markdown, not structured JSON for frontend parsing.
- **Error analysis display**: If a crypto analysis fails (critical tool error), the existing dashboard error state shows the error. The report will contain the error description.
- **Accessibility**: ARIA attributes on toggle, keyboard navigation
- **Tests**: React Testing Library component test for mode toggle

## K. Backend Implementation Plan

- **Router**: Skip provider API key check when asset_type="crypto" (Bybit public API needs no key)
- **Service**: Pass asset_type, interval, exchange_credentials to graph config
- **Schemas**: model_validator for cross-field validation (ticker regex + analyst enum + interval)
- **Persistence**: V2 migration, INSERT update, list filter
- **Config service**: Credential masking, PATCH atomicity, always-present response shape

## L. Security Implementation Plan

- **Secrets**: api_secret never returned, never logged, never transmitted; api_key masked
- **Credential storage**: Credentials from PATCH are stored in the in-memory config overrides dict (not persisted to disk/DB). On server restart, only env vars survive. This avoids plaintext-at-rest concerns. `api_secret` wrapped in Pydantic `SecretStr` (or custom class with `__repr__='***'`) so accidental serialization, logging, or traceback rendering never exposes the raw value. Credentials are server-global (single-user self-hosted deployment assumed).
- **Log scrubbing**: Strip sensitive params before logging, disable urllib3 DEBUG for Bybit session
- **HMAC**: api_secret only for local computation
- **Credential PATCH**: Atomic (both or neither), 422 on partial
- **Input validation**: Strict crypto symbol regex, interval allowlist, model_validator
- **Tests**: Secret non-exposure, masking, log scrubbing, HMAC correctness, PATCH atomicity rejection

## M. Testing Plan

| Test Type | Files | Requirements | ACs |
|-----------|-------|-------------|-----|
| Unit — data layer | test_bybit_data.py | FR-002-006, FR-017, NFR-001-008 | AC-001,009,010,015-019 |
| Unit — signal validation | test_signal_validation.py | FR-019,020,022,024 | AC-002,011,014 |
| Unit — tools | test_crypto_agent_utils.py | FR-007 | AC-001 |
| Unit — schemas | test_schemas.py | FR-001,015,018 | AC-003,006 |
| Unit — security | test_bybit_data.py | NFR-003, FR-014 | AC-005,012 |
| Integration — API | test_integration_crypto.py | FR-001,011 | AC-001,003,013 |
| Integration — signal | test_integration_crypto.py | FR-008,019,020 | AC-002,007 |
| Frontend — component | ConfigForm.test.tsx | FR-012,013 | AC-004 |
| Manual — E2E | Manual checklist | All | AC-001-019 |

## N. Manual Verification Checklist

1. Start backend and frontend (`start.bat`)
2. Navigate to New Analysis page
3. Toggle to "Crypto Futures" mode → verify crypto analysts shown, stock options hidden
4. Enter "BTCUSDT", select date, click Start → verify analysis starts
5. Monitor dashboard → verify agents running (progress is event-driven via WebSocket, not hardcoded to analyst count), messages flowing, stats updating
6. Wait for completion → verify report shows trading signal with entry/SL/TP/confidence/leverage
7. Toggle to "Stock" mode → verify stock form restored, start stock analysis → verify unchanged
8. Enter invalid symbol "invalid" → verify 422 error
9. Go to Config page → enter Bybit credentials → save → verify masked display
10. Remove credentials → verify "Not configured" status
11. Start crypto analysis without credentials → verify succeeds (unsigned requests)
12. Verify completed crypto analysis shows data on dashboard revisit (snapshot persistence)
13. Test retry-exhausted scenario: start analysis with intentionally invalid Bybit credentials (wrong API key for authenticated endpoint) → verify analysis completes with error report (not crash), error message is user-readable
14. Test Bybit unreachable: disconnect network or block Bybit IP → start crypto analysis → verify 503 "Bybit API unavailable" (not 500 or hang)

## O. Rollback and Recovery Plan

- **Code rollback**: Revert git commits; DB column stays (harmless DEFAULT 'stock')
- **Credential cleanup**: Credentials are in-memory only (not persisted to disk). Server restart clears them. No orphaned secrets on rollback.
- **Feature disable**: Remove crypto analysts from UI; backend still accepts but users can't submit
- **DB rollback**: Not needed — column is backward-compatible, CHECK constraint is additive
- **No data migration**: Existing rows default to 'stock', no data transformation

## P. Deployment/Release Plan

- **New env vars** (optional): `BYBIT_API_KEY`, `BYBIT_API_SECRET`
- **Deployment constraint**: MUST use `--workers 1` (single worker). Rate limiter is process-local; multiple workers would multiply actual API call rate. start.bat already uses single worker.
- **No start.bat changes**: Migrations run automatically on startup via `_apply_migrations()`
- **Build**: Standard `npm run build` for frontend
- **Verification**: Run checklist from Section N after deployment

## Q. Dependency and Sequencing Plan

```
TASK-001 (rate limiter) ──┐
TASK-002 (klines)     ────┤
TASK-003 (funding)    ────┤── Phase 1 (parallel after TASK-001)
TASK-004 (OI)         ────┤
TASK-005 (ticker)     ────┤
TASK-006 (indicators) ────┘── depends on TASK-002
TASK-007 (HMAC)       ────── depends on TASK-001
TASK-008 (tests)      ────── after all Phase 1

TASK-009 (tools)      ────── depends on Phase 1
TASK-010 (validation) ────── independent
TASK-011 (analysts)   ────── depends on TASK-009
TASK-012 (tests)      ────── after all Phase 2

TASK-013 (config)     ────┐
TASK-014 (schemas)    ────┤── Phase 3 (parallel)
TASK-015 (migration)  ────┤
TASK-016 (graph)      ────┤── depends on TASK-009, TASK-011, TASK-013, TASK-014
TASK-017 (backend)    ────┤── depends on TASK-014, TASK-015
TASK-018 (tests)      ────┘── after all Phase 3

TASK-019-022          ────── Phase 4 (after Phase 3)
TASK-023-024          ────── Phase 5 (after Phase 4)
```

**Critical path**: TASK-001 → TASK-002 → TASK-006 → TASK-009 → TASK-011 → TASK-016 → TASK-017 → TASK-020

## R. Traceability Matrix

| Requirement | Task(s) | Files | Tests | AC |
|-------------|---------|-------|-------|----|
| FR-001 | TASK-013,014,015,016,017 | default_config, schemas, persistence, graph, service | test_schemas | AC-003 |
| FR-002 | TASK-002 | bybit_data.py | test_bybit_data | AC-001 |
| FR-003 | TASK-003 | bybit_data.py | test_bybit_data | AC-015 |
| FR-004 | TASK-004 | bybit_data.py | test_bybit_data | AC-016 |
| FR-005 | TASK-005 | bybit_data.py | test_bybit_data | AC-017 |
| FR-006 | TASK-006 | bybit_data.py | test_bybit_data | AC-018 |
| FR-007 | TASK-009,011,016 | crypto_agent_utils, crypto_analysts, setup | test_crypto_agent_utils | AC-001 |
| FR-008 | TASK-010,011 | signal_validation, crypto_analysts | test_signal_validation | AC-002,007 |
| FR-009 | TASK-011 | crypto_analysts | test_crypto_analysts | AC-002,007 |
| FR-010 | TASK-011 | crypto_analysts | test_crypto_analysts | AC-007 |
| FR-011 | TASK-016 | trading_graph, setup | test_integration | AC-003 |
| FR-012 | TASK-020 | ConfigForm.tsx | ConfigForm.test.tsx | AC-004 |
| FR-013 | TASK-020 | ConfigForm.tsx | ConfigForm.test.tsx | AC-004 |
| FR-014 | TASK-007,017,021 | bybit_data, config_service, config page | test_bybit_data | AC-005,012 |
| FR-015 | TASK-014 | schemas.py | test_schemas | AC-006 |
| FR-016 | TASK-011 | crypto_analysts.py | test_crypto_analysts | AC-008 |
| FR-017 | TASK-002 | bybit_data.py | test_bybit_data | AC-009 |
| FR-018 | TASK-014 | schemas.py | test_schemas | AC-006 |
| FR-019 | TASK-010 | signal_validation | test_signal_validation | AC-002 |
| FR-020 | TASK-010 | signal_validation | test_signal_validation | AC-014 |
| FR-021 | TASK-002,013,014,020 | bybit_data, default_config, schemas, ConfigForm | test_bybit_data | AC-001 |
| FR-022 | TASK-010,013 | signal_validation, default_config | test_signal_validation | AC-014 |
| FR-023 | TASK-011 | crypto_analysts.py, bybit_data.py | test_crypto_analysts | AC-007 |
| FR-024 | TASK-010,011 | signal_validation, crypto_analysts | test_signal_validation | AC-011 |
| FR-025 | TASK-009 | crypto_agent_utils | test_crypto_agent_utils | AC-019 |

## S. Definition of Done

- All 24 tasks completed and verified
- All unit tests pass (`pytest tests/ -v`) — includes running full existing stock test suite to verify AC-013
- All frontend tests pass (`npm test`)
- Frontend builds without errors (`npm run build`)
- Stock analysis behavior completely unchanged (AC-003, AC-013)
- Manual verification checklist completed
- No Critical or High review findings remaining
- Plan can be executed without additional clarification

</content>
</invoke>