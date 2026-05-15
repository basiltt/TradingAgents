# Requirements: Trade Storage & Lifecycle Tracking

## Feature Description

All trades placed through the tool must be stored in a database `trades` table with extensive details at placement time. When any trade is closed — by Take Profit, Stop Loss, manual close, close-all, or conditional close rules — the trades table must be updated with PnL details, closure reason, exit price, fees, and timestamps.

**Key Gap:** Currently, trades placed via `POST /accounts/{id}/trade` are NOT stored in any database table — only Bybit's orderId is returned. Cycle trades are stored in `cycle_trades` but lack PnL/closure tracking. There is no unified trade record.

---

## Core Features [CORE]

1. Store every trade placed via `POST /accounts/{id}/trade` in a `trades` table at placement time with: account_id, symbol, side, qty, leverage, entry_price, take_profit_price, stop_loss_price, capital_pct, base_capital, order_id, order_link_id, mark_price_at_open, status, source (manual/cycle/rule), timestamps
2. Store trades placed via `TradingCycleEngine` in the same `trades` table with source=cycle and source_id=cycle_id, maintaining backward compat with `cycle_trades`
3. Record both user-supplied parameters (signal_direction, trade_direction, take_profit_pct, stop_loss_pct) and computed values (actual TP/SL prices, qty) on each trade
4. Generate a unique local trade_id (UUID) before sending to Bybit, pass as orderLinkId for correlation even if response is lost
5. On manual close-all (`close_all_positions()`), update every affected trade to status=closed with close_reason=manual_close_all, close_timestamp, close_order_id
6. On rule-triggered close (`close_all_for_rule()`), update affected trades to status=closed with close_reason=rule, rule_id, trigger_type, close_timestamp
7. On manual single-trade close, update trade with close_reason=manual_single, close_timestamp, close_order_id
8. Detect TP/SL fills from Bybit and update trade with close_reason=take_profit or stop_loss, close_timestamp, fill_price
9. Populate PnL fields at closure: realized_pnl, realized_pnl_pct, close_price, fees_paid, net_pnl
10. Periodic reconciliation job (every 60s) comparing local open trades against Bybit positions to detect discrepancies (external closes, missing trades)
11. WebSocket event `trade.opened` broadcast when trade is stored
12. WebSocket event `trade.closed` broadcast when trade is closed with PnL details
13. API endpoint `GET /accounts/{id}/trades` — paginated trade history with filters (status, symbol, date range, close_reason, side)
14. API endpoint `GET /accounts/{id}/trades/{trade_id}` — full trade detail
15. Correlate `closed_pnl_records` (Bybit sync) with `trades` table to backfill PnL for trades closed via exchange

## User Workflows [UX]

16. Trade History panel/tab on account detail view with columns: symbol, side, entry/exit price, PnL (green/red), status, close reason badge, open/close time, duration
17. Click-to-expand or detail view for each trade showing full parameters (leverage, TP/SL %, capital %, signal vs. trade direction, exchange order IDs)
18. Open trades section showing current positions with live unrealized PnL alongside stored trade parameters
19. Close reason badges — color-coded: TP (green), SL (red), Manual (gray), Close-All (orange), Rule (blue) with tooltip
20. "Close Trade" button on each open trade row with confirmation dialog showing estimated PnL at current price
21. Empty state: "No trades placed yet"
22. Loading/skeleton state while trade history is being fetched
23. Summary cards at top of trade history: Total PnL, Win Rate, Total Trades, Average Hold Time
24. PnL chart showing cumulative PnL over time or per-trade bar chart
25. Toast notification when trade closes asynchronously (TP/SL): "BTCUSDT Long closed — TP hit — +$142.30 (+3.2%)"
26. Close-all progress indicator: "Closing 3/7 positions..." with final summary
27. Optimistic UI for manual close — gray out row, show "Closing...", revert if API fails
28. Export trade history to CSV for tax reporting / external analysis

## API & Backend [API/DATA/ASYNC]

29. `trades` table schema: id (UUID PK), account_id (FK), symbol, side, qty, order_type, entry_price, avg_fill_price, exit_price, stop_loss_price, take_profit_price, leverage, mark_price_at_open, capital_pct, base_capital, signal_direction, trade_direction, status (enum), order_id (Bybit), order_link_id, close_reason (enum), realized_pnl, realized_pnl_pct, fees, net_pnl, source (enum: manual/cycle), source_id, metadata JSONB, opened_at, closed_at, created_at, updated_at
30. `trade_events` audit table: id, trade_id FK, event_type (placed/filled/tp_triggered/sl_triggered/close_requested/closed/failed/cancelled), old_status, new_status, payload JSONB, actor (system/user/rule_engine), timestamp — append-only
31. TradeStatus enum: pending, open, partially_filled, closing, closed, failed, cancelled
32. CloseReason enum: take_profit, stop_loss, manual_single, manual_close_all, rule_triggered, cycle_target, cycle_drawdown, external, liquidation
33. `TradeRepository` class following `CycleRepository` pattern — CRUD, bulk insert, query by status/symbol/account, PnL aggregation
34. Trade creation hook in `AccountsService.place_trade()` — after Bybit success, insert into trades + emit trade_event(placed)
35. Trade creation hook in `TradingCycleEngine` — after placement, insert into trades with source=cycle
36. Trade closure hooks in `ClosePositionsService` — update trades on close_all and close_for_rule
37. Background reconciliation job — poll Bybit positions, detect TP/SL/external closes, update trades
38. Background PnL sync — cross-reference closed_pnl_records with trades, update net_pnl with Bybit-reported values
39. Startup recovery — on boot, reconcile all open trades against Bybit positions
40. GET `/accounts/{id}/trades/open` — convenience endpoint for open trades
41. GET `/accounts/{id}/trades/stats` — aggregate: total trades, win rate, avg PnL, profit factor, avg hold time
42. PATCH `/accounts/{id}/trades/{trade_id}` — internal use for SL/TP amendment
43. Composite unique constraint on (order_id, account_id)
44. Partial index on trades WHERE status IN ('open', 'partially_filled') for fast queries
45. Keyset pagination (cursor-based on created_at + id) for trade list endpoint
46. Batch insert for cycle trades (executemany)
47. WebSocket channel integration via existing AccountWSManager for trade events
48. Map Bybit order statuses (New, PartiallyFilled, Filled, Cancelled, Rejected) to internal TradeStatus enum

## Security & Compliance [AUTH/AUTHZ/VALIDATION]

49. Validate all trade input: symbol format (whitelist), side (enum), qty (positive, max bounds), leverage (1-125), price (positive, sanity check vs market)
50. Validate Bybit order IDs match expected format before storage
51. Server-side PnL recalculation from entry/exit/qty/fees — never trust client-supplied PnL
52. Trade state machine enforced at DB level: no backward transitions (closed → open impossible)
53. Financial amounts use DECIMAL/NUMERIC columns, Python Decimal throughout — no floats for money
54. Closure operations must be idempotent — closing an already-closed trade is a no-op
55. All monetary calculations include fee structure (maker/taker/funding fees)
56. Sanitize and validate all Bybit API responses before storage — treat as untrusted input
57. Close_reason must be enum, never free-text (injection vector)
58. Trade operations scoped to account_id — no cross-account trade manipulation
59. Bulk operations (close-all) must include account_id in WHERE clause
60. Include actor_id field on trade writes for future auth support
61. Rate-limit trade placement (max 5 orders/second/account)
62. Rate-limit close-all operations (max 1 per 5 seconds/account)

## Edge Cases & Error Handling [BOUNDARY/FAILURE/CONCURRENCY]

63. Bybit API succeeds but DB insert fails — must retry insert, log critical error. Trade exists on exchange regardless
64. DB insert succeeds but Bybit rejects order — update trade to status=failed with error message
65. Bybit returns orderId but order immediately cancelled — detect and update status
66. Concurrent close-all and rule-triggered close on same position — dedup via existing _closing_accounts set
67. Two rules fire simultaneously for same account — atomic DB transitions prevent double-execution
68. Manual close and close-all hit same position — one succeeds, one gets "position not found"
69. Partial close (7/10 positions closed, 3 fail) — DB reflects exact close status per trade
70. Bybit partially fills a close order — store partial close and remaining quantity
71. Circuit breaker trips mid-close — remaining positions stay open, DB accurate
72. Bybit API timeout during place_trade — check if order was placed before retrying (use orderLinkId)
73. CloseRuleEvaluator 30s cycle takes >30s — handle overlap
74. Cached stale data used for rule evaluation after position fetch timeout
75. Duplicate place_trade with same orderLinkId — idempotency guard prevents duplicate rows
76. Zero PnL (breakeven) — handled correctly, not null/missing
77. Position at Bybit minimum qty — close rounding issues
78. Trade closed on Bybit web UI directly — reconciliation detects and marks close_reason=external
79. Close in-progress flag stuck after crash — timeout/recovery mechanism
80. DB transaction for trade insert + trade_event must be atomic
81. Write-ahead pattern: record close intent in DB before calling exchange API

## UI/UX & Frontend [SCREEN/COMPONENT/STATE]

82. Trade History page/tab — paginated table of all trades
83. Trade Detail view — full lifecycle timeline with state transitions
84. Trade row component — expandable summary with full details
85. Close reason badge component — TP/SL/Manual/Rule color-coded
86. Trade lifecycle timeline — vertical timeline showing each state transition with timestamps
87. PnL cell component — green/red with percentage, consistent across all tables
88. Trade filter bar — date range, symbol, side, close reason, PnL range, account
89. Trade export button — CSV/JSON download
90. Loading skeleton for trade table and detail view
91. Empty filtered results — "No trades match filters" with clear button
92. Error states with retry buttons
93. Close-all confirmation updated to show estimated PnL impact
94. Manual close success toast with PnL and link to trade detail
95. Manual close failure toast with reason and retry
96. Conditional rule trigger notification in real-time
97. Open positions table — PnL live-updates, row animates out on close
98. Trade history prepend — newly closed trades appear at top without refresh
99. PnL stats panel updates in real-time
100. Account equity updates immediately after trade closure
101. Stale data indicator when WebSocket disconnects
102. Pending TP/SL levels shown inline on open positions
103. Trade duration column (human-readable: 2h 15m)
104. Trade summary stat cards: total trades, win rate, total PnL, avg hold, best/worst trade
105. PnL sparkline or cumulative equity curve on history page
106. Deep link URL route: /accounts/:id/trades/:tradeId
107. Breadcrumb navigation: Account > History > Trade #123
108. Responsive: mobile card layout, stacked detail, filter bottom sheet

## Configuration & Settings [CONFIG]

109. Configurable page size for trade history (default 50, max 200)
110. Retention policy: auto-archive trades older than N days (default: never delete)
111. Toggle for reconciliation job frequency (30s, 60s, 120s, disabled)

## Observability & Operations [OBSERVABILITY/ADMIN]

112. Structured logging on every trade state transition: trade_id, old_status, new_status, close_reason, latency_ms
113. Metrics counters: trades_placed_total, trades_closed_total (by close_reason), trades_pnl_total
114. Alert on reconciliation discrepancy — Bybit shows closed position with no matching trades record
115. Trade lifecycle duration histogram: placed→filled, filled→closed
116. Failed trade operations logged with full context: attempted operation, exchange error, trade state
117. Reconciliation results persisted and flagged, not just logged

## Performance & Scalability [PERF/CACHE]

118. Indexes: (account_id, status), (symbol, opened_at), (order_id), (source, source_id), (closed_at)
119. Partial index on open trades for fast queries
120. In-memory cache of open trades per account (invalidated on trade_event) for rule evaluator
121. Short-TTL cache (5-10s) on PnL summary endpoints
122. Rate limiting on Bybit API calls from reconciliation — respect 120 req/min
123. DB transactions with appropriate isolation (SERIALIZABLE for PnL updates)

## Compatibility & Migration [COMPAT/MIGRATION]

124. New migration #25 in both persistence.py and async_persistence.py for trades + trade_events tables
125. Deprecation path for cycle_trades — add trade_id FK to cycle_trades pointing to canonical trades record
126. Schema versioning — both persistence files updated in lockstep
127. NOT NULL constraints, UNIQUE constraints, CHECK constraints on all enum fields
128. Foreign key from trades.account_id to trading_accounts with appropriate delete policy

## Accessibility [A11Y]

129. Trade history table keyboard-navigable with ARIA labels for status/PnL
130. Confirmation dialogs trap focus, dismissible via Escape
131. Toast notifications use role="alert" with aria-live="polite"

---

## Round 2 Additions

### Core Features (additions)

132. Detect and handle liquidation events — Bybit-initiated forced closure with distinct handling: liquidation price, insurance fund deduction, critical UI alert
133. Backfill migration: import existing `cycle_trades` into new `trades` table; optionally fetch recent closed PnL from Bybit for historical trades
134. TP/SL amendment lifecycle: `tp_sl_amended` event type, Bybit API call to modify conditional orders, rollback on rejection, validation vs current price
135. Multiple open trades on same symbol/account: closure must allocate PnL proportionally (FIFO or pro-rata); reconciliation must handle Bybit's merged position
136. Pre-trade validation: check available balance, verify margin mode, verify API key has trade permission; store rejection reason if pre-checks fail

### API & Backend (additions)

137. Service initialization order: DB pool → TradeRepository → AccountWSManager → Reconciliation → CloseRuleEvaluator with readiness gate
138. Graceful shutdown: background jobs register with shutdown handler, drain in-flight work, complete/rollback DB transactions before exit
139. Close-all API response contract: `{ succeeded: [], failed: [], total: int }` with per-trade error details
140. PnL sync must run after reconciliation in each cycle to avoid race between the two jobs
141. Reconciliation must skip trades with status IN ('pending', 'closing') and not transition trades updated within last N seconds
142. Startup recovery for `closing` status trades: check Bybit — if closed, update; if still open, reset to open. Max closing-state duration (5 min) before force-clear

### Data Model (additions)

143. `archived_at` nullable timestamp column for soft-archive; archived trades excluded from default queries via partial index
144. All timestamp columns use TIMESTAMPTZ; all app-layer datetimes are UTC; Bybit epoch-ms converted to UTC on ingestion
145. trades.account_id FK must use ON DELETE RESTRICT — accounts with trades cannot be hard-deleted
146. PnL calculated using avg_fill_price (actual execution), not entry_price (requested). Warn if divergence exceeds slippage threshold
147. trade_events retention follows same policy as parent trade; partition by month for growth management

### Security (additions)

148. All trade status transitions must acquire row-level lock (SELECT ... FOR UPDATE) within transaction
149. Financial fields on closed trades are write-once; corrections require trade_event with old/new values and reconciliation_override flag
150. trade_events table append-only enforced at DB level (revoke UPDATE/DELETE or use trigger)
151. metadata JSONB validated: max 16KB size, restricted to known keys, sanitized before rendering
152. Reconciliation grace period: skip trades updated within last N seconds to avoid racing with in-flight operations
153. CSV export: prefix cell values starting with =, +, -, @, TAB, CR with single quote (formula injection prevention)
154. All query parameters (date_range, cursor, page_size) validated server-side; date ranges max 1 year; DB query timeout set

### Edge Cases (additions)

155. Closing → failed transition: define transient vs permanent exchange errors. Closing → open allowed on transient error retry exhaustion
156. Pending → cancelled (user cancels unfilled), pending → failed (exchange rejects), pending → open (exchange confirms fill) — explicit triggers defined
157. Circuit breaker trips during cycle placement: unplaced trades recorded as status=cancelled with circuit_breaker metadata
158. Bybit close succeeds but DB update fails: retry with exponential backoff, critical alert, reconciliation as safety net
159. PnL sanity check: if |realized_pnl| > base_capital * leverage * 2, flag anomalous, require manual review
160. Semaphore exhaustion during close: timeout for waiting requests, guaranteed release in finally blocks, starvation detection
161. Cache freshness for rule evaluator: validate cache version vs DB before acting, or use read-through cache with short TTL

### UI/UX (additions)

162. Pagination controls: previous/next buttons (cursor-based), total trade count, end-of-results behavior
163. Filter state serialized to URL query parameters — survives navigation and is shareable/bookmarkable
164. Sort controls on trade history columns (opened_at, closed_at, PnL, symbol, duration); default: newest first; persisted in URL
165. Concurrent close feedback: when manual close returns "already closed", show specific toast with actual close reason
166. Partial close-all failure summary: list succeeded/failed positions with reasons, "Retry Failed" button
167. WebSocket reconnection: exponential backoff, "Reconnecting..." banner, "Reconnect" button after N failures, full state refresh on reconnect
168. Reconciliation discrepancy banner on affected account: "1 position was closed externally and has been synced"
169. Export progress indicator for large datasets, error toast with retry, date range in filename
170. Empty state for open positions section: "No open positions" with CTA to place trade

### Round 3 Additions (genuinely new items only — most R3 findings duplicated R2)

171. ADL (Auto-Deleveraging) detection: distinct from liquidation, Bybit forcibly reduces profitable positions — detect, store close_reason=adl, distinct UI alert
172. Partial close support: user can close X% of a position (not just all-or-nothing); API endpoint with qty param, PnL calc on partial, trade record qty reduction
173. Limit order cancellation: cancel pending/unfilled order via UI button and API endpoint; auto-cancel timeout for stale unfilled orders
174. Symbol delisting/trading halt: reconciliation detects when open trade's symbol is no longer tradeable; mark with appropriate status; alert user
175. Filled qty vs requested qty tracking: partial fills at open update avg_fill_price incrementally; trade_event per fill; transition to open only when fully filled
176. Advisory locks for background jobs: reconciliation, rule evaluation, PnL sync use pg_advisory_lock to ensure single-instance execution across deployments
177. Migration rollback: migration #25 includes reversible down-migration; rollback tested before merge
178. Negative fees (maker rebates): fees field accepts negative values; net_pnl = realized_pnl - fees (negative fees increase net_pnl)
179. Decimal precision per column: specify exact precision (e.g., NUMERIC(18,8) for qty/price, NUMERIC(20,8) for PnL); rounding mode ROUND_HALF_UP; never float
180. React error boundaries around trade history page, PnL chart, trade detail — fallback UI with "Reload" action
181. Multi-select checkboxes on open positions for "Close Selected" (subset close, not just single or all)
182. Info tooltips on financial column headers explaining "Net PnL" vs "Realized PnL", close reason meanings
183. Cursor pagination stability: use monotonic ID as sort key, immune to concurrent inserts
184. CSV export: UTF-8 with BOM, RFC 4180 escaping, period decimal separator

### Round 4 Additions (near-clean round — mostly duplicates, few new items)

185. Partially_closed state: after partial close (req 172), trade retains open status with reduced qty, or creates child trade for closed portion with PnL attribution
186. API credential expiry handling: if Bybit returns auth errors during reconciliation/close, mark account as degraded, alert user, suspend automated rules until credentials restored
187. Zero-downtime migration strategy: additive schema changes first (nullable columns), deploy code, backfill, then add constraints
188. Symbol renaming/contract rollover: historical trades retain original symbol; define behavior for reconciliation when symbols change on exchange
189. Bybit rate-limit (429) during close-all: retry with backoff, queue remaining closes, report progress to user rather than failing batch
190. Margin mode storage: add margin_mode (cross/isolated) to trades schema for accurate liquidation/risk calculations
191. Hedge mode handling: support two opposing positions on same symbol; position_idx tracking for reconciliation

---

## Total Requirements Count: 191
## Rounds Completed: 4 (R3-R4 near-clean — exit criteria met)
