# Requirements: Account Close Positions with Conditional Rules

## Feature Description
Add a 3-dot kebab menu to each trading account card on the Accounts page with:
1. **Close All Positions** — immediately market-close all open positions for that account via Bybit V5 API
2. **Conditional Close Rules** — set server-side rules that auto-close all positions when conditions are met (balance thresholds, % equity changes, drawdown, PnL targets)

## Core Features [CORE]
1. Kebab menu (3-dot icon) on every account card
2. "Close All Positions" triggers immediate market-order close for all open positions
3. Confirmation dialog before executing close (shows position count and estimated value)
4. "Set Conditional Rules" opens rule configuration modal
5. Condition: balance drops below a specified dollar value
6. Condition: balance rises above a specified dollar value
7. Condition: equity decreases by X% from reference point
8. Condition: equity increases by X% from reference point
9. Condition: unrealized PnL reaches negative threshold (max loss)
10. Condition: unrealized PnL reaches positive threshold (take profit)
11. Multiple conditions per account (AND / OR logic)
12. Active rules visually indicated on account card (badge/icon)
13. Rules persist server-side across browser sessions
14. Rule pause/resume without deletion
15. Optional rule expiry time
16. Reference point for % conditions configurable (rule creation time or custom value)
17. Audit log of triggered close events (timestamp, condition, positions, fill prices)
18. In-app notification when rule triggers
19. Rules evaluate server-side (fires even when browser closed)
20. Demo and live accounts have separated rule sets

## User Workflows [UX]
21. Kebab menu closes on outside click or Escape
22. "Close All" styled destructively (red text)
23. Progress indicator while close orders submit
24. Per-position result shown (success/failure per symbol)
25. "Close All" disabled with tooltip when no open positions
26. Rule form validates inputs inline
27. Warning indicator when equity nears threshold (within 10%)
28. Editing existing rule pre-populates form
29. User can delete rules individually
30. User can duplicate rule to another account
31. Condition check interval visible to user

## API & Backend [API/DATA/ASYNC]
32. POST /api/v1/accounts/{id}/positions/close-all
33. POST /api/v1/accounts/{id}/close-rules
34. GET /api/v1/accounts/{id}/close-rules
35. PUT /api/v1/accounts/{id}/close-rules/{rule_id}
36. DELETE /api/v1/accounts/{id}/close-rules/{rule_id}
37. CloseRule model: id, account_id, trigger_type, threshold_value, comparison_op, reference_value, status, created_at, triggered_at, expires_at
38. CloseExecution model: id, rule_id, account_id, triggered_by, symbols_closed, orders_placed, errors, executed_at
39. Bybit POST /v5/order/create wrapper — market order, reduceOnly=true, per-symbol
40. Fetch positions before close-all to enumerate symbols/qty
41. Retry logic (3 attempts, exponential backoff) for order placement
42. Background job polling active rules every 15-30s against cached balance/position data
43. Idempotency lock per rule to prevent double-execution
44. Close-all fan-out concurrent (asyncio.gather), not serial
45. Max 5 active rules per account
46. Per-symbol order result in close-all response
47. Store raw Bybit order response in execution record
48. Respect Bybit rate limits (10 req/s per symbol)
49. Dead-letter handling for mid-way failures
50. Emit WebSocket events: position.closed, rule.triggered
51. DB migration for close_rules and close_executions tables

## Security & Compliance [AUTH/AUTHZ/VALIDATION]
52. Account ownership verified server-side before any close/rule operation
53. Balance/percentage values validated as numeric within sane bounds
54. Rule conditions validated for logical consistency
55. Max field lengths enforced on all JSON payloads
56. Decrypted API keys exist only in-process memory during exchange call
57. API keys never in logs, error messages, or stack traces
58. Every close action produces audit log entry
59. Rule CRUD logged with before/after state
60. Failed close attempts logged with detail (no raw keys)
61. Close endpoint rate-limited per account
62. Rule evaluation cooldown to prevent threshold thrashing
63. Bybit calls throttled within V5 rate limits

## UI/UX & Frontend [SCREEN/COMPONENT/STATE]
64. 3-dot icon, positioned top-right of card header
65. Dropdown menu dark surface, shadow-lg
66. Menu open/closed toggle with outside click dismiss
67. Full arrow-key navigation through menu items
68. "Close All" with red text and XCircle icon
69. "Set Conditional Rules" with SlidersHorizontal icon
70. Confirmation modal: position count, total exposure, irreversible warning
71. Modal loading state: spinner replaces confirm button
72. Success toast: "All positions closed for [Account Name]" (green, 4s)
73. Error toast with reason and retry action (red, manual dismiss)
74. Conditional Rules dialog: full modal, scrollable, dark theme
75. Rule builder row: condition type selector + value input + delete
76. Condition type dropdown: Balance Below, Balance Above, Equity Drop %, Equity Rise %, Drawdown %
77. Empty rules state: "No rules set" with Add Rule CTA
78. Add Rule button appends new row with animation
79. Inline validation errors (red border + message)
80. Unsaved changes indicator + discard confirmation
81. Save Rules success toast
82. Active rule badge on account card
83. Rule triggered notification toast
84. Rules dialog saving state (spinner, inputs disabled)
85. Disabled menu items when no open positions
86. Dialog focus trap
87. Rule toggle switch (enable/disable without deleting)
88. Per-rule enabled/disabled visual state (dimmed row)
89. Kebab icon highlight when rule triggered

## Edge Cases & Error Handling [BOUNDARY/FAILURE/CONCURRENCY]
90. Close with zero positions returns success
91. Single position closes cleanly
92. 0% threshold: document behavior (trigger immediately or never)
93. Max positions (500+) — batch/paginate close
94. Manual close and scheduler condition fire simultaneously — idempotent
95. Two scheduler ticks overlap — no duplicate orders
96. User edits rule mid-evaluation — use live or snapshot?
97. Bybit 429 rate-limit mid-batch — remaining positions left open, error surfaced
98. Partial success — DB reflects only actually closed positions
99. Network timeout after order submitted before confirmation — position state unknown
100. PostgreSQL write fails after Bybit close succeeds
101. Scheduler crashes mid-check — rule doesn't silently stop
102. 10 of 15 positions close, 5 fail — distinguish in response
103. Active rule but no API key — surface config error
104. Close same position twice — idempotency against Bybit order status
105. Rule deleted while close in-flight — orphaned close completes, no re-trigger
106. Bybit response exceeds timeout — task cancelled, state flagged
107. Retry re-closes already-closed positions — Bybit rejects, handler swallows
108. Exponential backoff doesn't block scheduler for other accounts
109. Unified vs classic Bybit account type
110. Symbol with no market liquidity — rejection handled
111. Hedge-mode positions (long+short same symbol) — both sides closed
112. Multiple conditions AND/OR — evaluated atomically or independently?
113. DB rule row updated between check and execution
114. Account suspended by Bybit mid-close
115. All retries exhausted — rule auto-disabled or retries next tick?
116. FastAPI worker restart mid-close — in-flight lost, lock released

## Configuration & Settings [CONFIG]
117. Rule evaluation interval configurable (default 15-30s)
118. Max rules per account configurable
119. Close-all concurrency limit configurable
120. Retry count and backoff configurable

## Observability & Operations [OBSERVABILITY]
121. Structured log per rule evaluation: account_id, rule_id, condition_result, action_taken
122. Execution record persisted regardless of partial failure
123. WebSocket events for frontend real-time updates

## Performance & Scalability [PERF]
124. Close-all concurrent fan-out
125. Rule evaluation loop completes within one polling interval
126. Skip accounts with stale/invalid API keys
127. Position cache with short TTL to avoid per-tick API calls

## Accessibility [A11Y]
128. Kebab button aria-label includes account name
129. Menu items keyboard navigable (arrows, Enter, Escape)
130. Confirmation dialog traps focus, returns on close
131. Rule status badge has screen-reader text

## Mobile & Responsive [MOBILE]
132. Kebab touch target minimum 44x44px
133. Rule modal scrollable on small viewports
134. Menu as bottom sheet on mobile

## Round 2 Additions

### Prerequisites & Lifecycle
134. Validate API key existence and connectivity before allowing rule creation
135. Manual close-all acquires same idempotency lock as scheduler
136. Rule evaluator re-fetches decrypted API key on each evaluation cycle (no cross-tick cache)
137. After API key rotation, stale cached clients must be invalidated for rule evaluation

### Architecture & Integration
138. Define scheduler startup integration: extend SnapshotScheduler pattern or separate service (like ScanSchedulerService)
139. Migration version numbers following sequential integer key pattern in persistence.py _MIGRATIONS
140. BybitClient: extend existing class with POST order methods (shared semaphore/rate-limit deque)
141. WebSocket event payload schema for position.closed and rule.triggered events
142. Database index on close_rules(status, account_id) for evaluator hot path
143. Transaction boundary: lock acquisition + execution record + rule status update in single BEGIN/COMMIT

### Security Additions
144. Destination account ownership verified for rule duplication
145. CSRF protection via existing X-Requested-With middleware (already in place)
146. Define concrete threshold bounds (e.g., balance -1M to 10M, percentage 0.01-100)
147. Audit log records immutable — no delete/update endpoints

### Edge Case Additions
148. Rule expiry while close in-flight — close completes, rule then expires
149. Duplicate rule to account at max-rules limit — reject with error
150. Reference point of zero — guard against divide-by-zero in % calculations
151. Positions across multiple Bybit categories (linear only initially, document limitation)
152. Rule toggled to paused during evaluation — current evaluation still completes
153. All retries exhausted — rule auto-pauses, surfaces error to user

### UI/UX Additions
154. "View History" entry in kebab menu — shows close execution audit log for that account
155. Rule dialog refreshes if rule triggers while dialog is open (WebSocket-driven)
156. Duplicate-to-account picker UI (account selector dropdown)
157. Proximity warning badge on card (amber dot or text) when equity nears threshold

### Round 3 Additions
158. Rule triggers on empty position set — log event, rule stays active (no auto-pause)
159. Notification fallback: persistent unread badge in UI when WebSocket delivery fails
160. Evaluator per-account timeout (e.g., 10s) so one slow account doesn't stall others
161. Idempotency lock TTL (e.g., 60s) to auto-release on crash/hang
162. Flush position cache after manual close-all to prevent stale re-trigger
163. Source account ownership verified for rule duplication
164. Account deleted while rules active — evaluator skips gracefully, orphaned rules cleaned up
165. Floating-point precision: use Decimal comparison for thresholds, not float
166. USDT settlement only (document limitation, no currency conversion)
167. Rules dialog skeleton loading state while fetching existing rules
168. Proximity warning badge auto-clears when equity recovers past threshold

## Total Requirements Count: 168
## Rounds Completed: 3
