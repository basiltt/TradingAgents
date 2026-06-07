# Requirements: MCP Server (AI Agent Integration)

**Feature:** An MCP (Model Context Protocol) server that lets an external AI agent drive the TradingAgents app.
**Status:** COMPLETE — 586 requirements over 6 brainstorm rounds; 2 consecutive clean convergence rounds; 20 contradictions (C1–C20) resolved.
**Default posture:** Master switch OFF; conservative tool selection; read-only / backtest-only by default; no live-money trading without a separate explicit opt-in.

---

## Feature Description

Expose the TradingAgents app's capabilities as MCP tools so an external AI agent (Claude Desktop,
Claude Code, or any MCP client) can:
1. Use **basic app features** — run/list/inspect market scans; read accounts, positions, trades,
   portfolio, analytics, scheduled scans, strategies, symbols, current AutoTradeConfig.
2. Use the **backtesting subsystem** — create/list/get/compare backtests, cache warmup/status, poll
   background completion.
3. Use the **debugging routes** — auto-trade trace forensics (scan/account/symbol), debug config.
4. Run **parameter-sweep backtests to discover the optimal AutoTradeConfig** for the current setup
   (the optimizer workflow) — define a search space, run many backtests, rank by a chosen metric,
   return the best configuration(s).

The whole integration is **toggleable ON/OFF from the app UI, default OFF**, mirroring the existing
`debug_config` singleton + `app.state` availability-gate pattern.

Because every advertised MCP tool's JSON schema consumes the agent model's context window, the user
must be able to **enable/disable tool groups and individual tools**; the server registers and
advertises **only the enabled subset** so disabled tools cost zero context.

---

## Conventions
- Each requirement has a stable ID (`R-###`) assigned at spec time; Round 1 lists them by category.
- Tags from brainstorm preserved in brackets.
- "MUST / SHOULD / MAY" used per RFC-2119 intent.

---

## Core MCP Tool Capabilities [CORE]

1. Scanner tools — trigger a new market scan, list past scans (filters/pagination), fetch scan details, retrieve a scan's ranked signals/results without re-running analysis.
2. Accounts tools (read-only) — list configured accounts, get account metadata, balances, exchange connection/health status.
3. Positions tools — list open positions, get a single position's detail (entry, size, leverage, uPnL, attached close rules).
4. Trades tools — list/query trade history with filters (symbol, date range, account, win/loss), get a single trade's full lifecycle and close reason.
5. Portfolio tools — portfolio overview, exposure/allocation by symbol & sector, realized/unrealized P&L, equity snapshot.
6. Analytics & signal-analytics tools — performance metrics, signal hit-rate, sector concentration, blacklist state, win/loss distributions.
7. Scheduled-scans tools — list scheduled scan jobs, inspect schedule/cron, last-run + next-run, per-run auto-trade outcomes.
8. Strategies & config tools — read available strategies and the current/saved AutoTradeConfig(s) so the agent knows the live parameter baseline.
9. Symbols tools — search/list tradable symbols, symbol metadata, sector classification, data availability/coverage.
10. Backtest tools — create a backtest (full AutoTradeConfig param set + fresh capital/TP/SL/leverage), list backtests, get a backtest's full result, poll/await completion of the background task.
11. Backtest comparison tool — compare 2..N backtests on standard metrics (return, Sharpe, Sortino, max DD, win rate, profit factor, expectancy).
12. Kline cache tools — trigger cache warmup for symbol/timeframe/date-range, check cache coverage, report missing ranges before a sweep.
13. Debug/forensics tools — trace forensics for a scan, account, or symbol; read debug_config; surface the same trace data the debug UI exposes.
14. MCP resources (not just tools) — expose stable, low-cost read endpoints (latest scan, current config, portfolio snapshot) as MCP *resources* to avoid burning a tool slot for static reads.
15. MCP prompt templates — bundled prompts for common journeys ("optimize my config", "audit last scan", "explain why this trade closed") as guided entry points.
16. Token-efficient response modes — every tool supports compact/summary vs verbose payload + pagination, so large result sets don't blow the agent's context.

## Optimizer / Parameter-Sweep Workflow [OPTIMIZER]

17. Search-space definition — agent specifies which AutoTradeConfig fields to sweep, with ranges/enumerations/step sizes, plus fixed (non-swept) fields.
18. Sweep sizing/estimation — before running, return combination count, estimated runtime, and required kline cache coverage so the agent/user can confirm feasibility.
19. Search strategies — grid search, random search, and a "smart"/coarse-to-fine search to cover large spaces without exhaustive cost.
20. Batch execution engine — run many backtests across combinations reusing one shared cached kline set, with bounded concurrency.
21. Objective selection & ranking — rank by a chosen metric (Sharpe, total return, profit factor, min drawdown, expectancy) and return top-N configs.
22. Constraints & filters — exclude configs violating guardrails (max DD ≤ X, min trades ≥ N, min win rate) before ranking.
23. Multi-objective / Pareto output — surface the trade-off frontier (e.g. return vs drawdown) when no single metric dominates.
24. Overfitting safeguards — optional walk-forward / in-sample vs out-of-sample split and a robustness flag so the "best" config isn't curve-fit.
25. Sensitivity analysis — report which parameters most affect the chosen metric, and stability of the winner to small perturbations.
26. Sweep progress, cancel & resume — poll % complete / configs done, cancel, checkpoint/resume long sweeps.
27. Best-config delivery — return the winning AutoTradeConfig as a ready-to-apply object, with an explicit "apply to scheduled scanner" action gated behind safety/confirmation.
28. Sweep persistence & history — store completed sweeps so the user can revisit, re-rank by a different metric, or compare sweeps later.
29. Primitive-tool mode retained — low-level `run_backtest`/`get_backtest_result` tools so an agent can drive its own search loop (discouraged for large sweeps; protects context + rate limits).
30. Sweep respects BacktestService limits — catch BacktestRateLimitError/BusyError, bounded semaphore + backoff/retry queue, fair-share enqueue with UI-initiated backtests.
31. Combinatorial safety — hard cap (`max_sweep_backtests`) rejecting oversized grids; dedup identical combos; pre-flight estimate before any work scheduled.
32. Objective metric library — total return, Sharpe, Sortino, max DD, win rate, profit factor, expectancy — agent-selectable, with documented tie-breakers.
33. NaN/Inf metric quarantine — degenerate-run metrics sorted last, never win or corrupt sort order.
34. Sweep determinism — identical inputs (config/date range/cached klines) produce identical rankings and a reproducible winner.

## Master Toggle (On/Off, Default OFF) [TOGGLE]

35. Master ON/OFF switch — DB-backed singleton (mirror `debug_config`) default OFF, persisted across restarts, controlling whether the MCP server is mounted/advertised.
36. 503 availability gate — when OFF, MCP endpoints return a clear "feature disabled" response (not a silent failure); `getattr(app.state, "mcp_server", None)` gate.
37. Off-state guarantees zero attack surface — when OFF the transport is NOT mounted and NOT listening (no route, no socket, no in-process handler).
38. Off-state UI — when disabled, the panel explains what the feature does, shows it's safe/off by default, offers a single enable action.
39. One-click kill-switch — instantly disables the server, drops active sessions, revokes in-flight tool execution; reachable even mid-sweep.
40. Idempotent transitions — enabling when already enabled (and vice-versa) is a no-op; no port churn, no server restart.
41. Default-OFF on fresh DB — absent singleton row reads as disabled, not an error.
42. Toggle persists across restart — server auto-starts only if last persisted state was ON.
43. Master toggle gates the entire transport — `enabled=false` ⇒ MCP sub-app unmounted (or 503/404) and advertises zero tools.
44. Hot enable/disable — `PUT /mcp/config` + UI toggle propagate a config-change event that re-resolves the toolset and mounts/unmounts at runtime with no process restart.

## Tool-Budget Management (Enable/Disable Groups & Individual Tools) [TOOLBUDGET]

45. Tool-group enable/disable — toggle whole domains (Scans, Accounts, Positions, Trades, Portfolio, Analytics, Backtesting, Debug, Optimizer) on/off; disabled groups are not registered and cost zero context.
46. Per-tool checkboxes — granular enable/disable of individual tools within an enabled group.
47. Presets/bundles — one-click Minimal / Standard / Full / Backtesting-only / Read-only profiles; conservative Minimal is the default selection.
48. Live tool count + estimated context cost — real-time "N tools enabled ≈ ~X tokens of schema," updating as boxes are checked.
49. Budget warning — visual warning when the enabled set crosses a configurable token/tool threshold likely to saturate context (non-blocking).
50. Tool catalog browser — searchable/filterable list with each tool's description and schema preview so the user understands what they're enabling.
51. Server re-registration on change — saving the enabled set re-advertises tools (`notifications/tools/list_changed`); declare `tools.listChanged: true` capability at init.
52. Group/individual conflict resolution — an individual tool disabled inside an enabled group stays hidden (most-restrictive wins); inverse is defined.
53. Disabled tool truly unreachable — calling a disabled/unadvertised tool by name is rejected with method-not-found, never executes (defense beyond UI hiding).
54. Enabling zero tools — server still initializes and advertises an empty tool list without crashing.
55. Enabling all tools — server starts, advertises the full set, computes/surfaces the summed estimated context cost.
56. Estimated-context-cost accuracy — per-tool/group token estimate stays within tolerance of actual serialized schema size.
57. Safety-class badges per tool — Read-only / Backtest / Live-money badge so users see risk while choosing the budget.

## Architecture / Transport / Call Path [TRANSPORT/CALLPATH/TOOLREG]

58. Embedded FastMCP mounted as an ASGI sub-app on the existing FastAPI instance via streamable-HTTP, sharing the event loop and `app.state.*` services (zero-IPC in-process access).
59. Streamable-HTTP chosen over legacy SSE (better session/resumption semantics; SDK default).
60. Standalone stdio process documented as a non-default fallback (process isolation, but loses in-process access).
61. Mount path (e.g. `/mcp`) placed OUTSIDE `/api/v1`, with an explicit `CSPCSRFMiddleware` exemption for the mount prefix so the streamable-HTTP handshake POST (lacking `X-Requested-With`) is not 403'd.
62. Streamable-HTTP session management — honor `Mcp-Session-Id`, support multiple concurrent sessions, bound the session table; decide resumability vs stateless.
63. Primary call path = in-process service-layer calls — MCP handlers invoke `app.state.backtest_service`, accounts/positions services directly, bypassing HTTP serialization/CSRF/CORS; single source of validation via Pydantic.
64. ASGI loopback path documented as alternative (reuses router validation but double-validates, hits 1MB cap) — not the default.
65. Real-HTTP-to-localhost documented as loosest-coupling fallback (needed for stdio mode) — not default.
66. Call-path decision matrix codified — read tools → direct service calls; mutating tools → direct service calls wrapped in router-equivalent validation; CSRF replaced by MCP-layer auth + safe-mode gating in-process.
67. Central tool registry/manifest — each tool: `{name, group, handler, input_schema (Pydantic), output_schema, enabled_default, mutating: bool, safety_class, scope}` — single source for FastMCP registration.
68. Dynamic registration driven by persisted config — on startup and every config change, rebuild/refilter advertised toolset; disabled tools cost zero context.
69. Re-registration without restart — rebuild a fresh FastMCP instance and atomically swap, or maintain a live filter set the dispatcher consults (depends on SDK runtime add/remove support).
70. Reuse existing Pydantic v2 schemas (e.g. `BacktestCreateRequest`) to auto-generate MCP input JSON Schemas so tool contracts stay in sync with app validation.
71. Tool-schema versioning — advertise a `schema_version` in tool metadata/config; additive-change discipline + deprecation flags so agents detect contract changes.

## Data Models & Persistence [DATA/MIGRATION]

72. `mcp_config` singleton (`id INT PK CHECK(id=1)`): `enabled BOOLEAN DEFAULT false`, `enabled_groups JSONB`, `enabled_tools JSONB` (overrides), `access_token_hash TEXT`, `bind_host TEXT DEFAULT '127.0.0.1'`, `safe_mode_flags JSONB`, `schema_version`, `updated_at TIMESTAMPTZ`.
73. Safe-mode flag set persisted: `read_only`, `allow_real_trades` (default false ⇒ trade tools dry-run), `allow_debug`, `max_sweep_backtests`, `max_concurrent_backtests`.
74. Access token stored hashed (never plaintext), shown once on generation, rotation support; optional per-group scopes.
75. `mcp_sweep_jobs` table — `id`, `status` (queued/running/completed/cancelled/failed), `strategy`, `param_space JSONB`, `objective_metric`, `total_combos`, `completed_combos`, `best_result_id`, timestamps.
76. `mcp_sweep_results` table — one row per evaluated config (`sweep_id FK`, `config JSONB`, `backtest_id`, `metrics JSONB`, `rank`) for incremental ranking and best-N retrieval.
77. `mcp_audit_log` table — `id`, `tool_name`, `group`, `args_redacted JSONB`, `session_id`, `started_at`, `duration_ms`, `status`, `error`.
78. Migrations appended to `_MIGRATIONS` in `async_persistence.py` (advisory-locked), seeding the singleton `mcp_config` row with `enabled=false`.
79. Forward-compatible JSONB columns so new groups/strategies/metrics need no further DDL.

## Async / Lifecycle [ASYNC/LIFECYCLE]

80. Sweeps run as background asyncio tasks — `run_sweep` returns a `sweep_id` immediately; agent polls status/results; optional MCP progress notifications stream `completed/total`.
81. Cancellation — `cancel_sweep` cancels orchestration, drains in-flight backtests gracefully, persists partial results as cancelled.
82. Resource caps — max concurrent sweeps, max concurrent backtests per sweep, max total backtests, per-sweep wall-clock timeout.
83. Lifespan wiring — init MCP component in `create_app()` lifespan, attach to `app.state.mcp_server`, read `mcp_config` for initial mount/registration state.
84. Failure isolation — any MCP init error degrades `app.state.mcp_server` to `None` and logs; NEVER aborts trading startup (debug-trace degradation contract).
85. Graceful shutdown — cancel in-flight sweeps, persist state, close MCP sessions, flush audit log on teardown.
86. In-flight sweep recovery on restart — scan `mcp_sweep_jobs` for `running` rows; resume from `completed_combos` or mark `interrupted`, surfaced to agent on next poll.

## Security & Compliance [AUTH/AUTHZ/SAFEMODE/NETWORK/VALIDATION/SECRETS/AUDIT/RATELIMIT/INJECTION/DOS/PRIVACY/FAILSAFE]

87. Bearer-token auth on the MCP transport — every request validated against the hashed token in `mcp_config`; missing/invalid → 401; no anonymous path even on localhost.
88. Token via CSPRNG ≥256 bits; user can regenerate; generated server-side; surfaced to UI exactly once.
89. Token stored hashed (SHA-256/argon2), verified constant-time (defeat timing attacks).
90. Token rotation + immediate revocation invalidates old value and tears down sessions bound to it.
91. Token never written to logs, audit args, exception traces, or tool outputs; add to `mask_secrets` deny-list; scrub from error envelopes.
92. Missing/expired/malformed token → hard reject (401), fail closed, generic sanitized error.
93. Default bind 127.0.0.1 only; socket not reachable off-host by default.
94. Refuse to bind 0.0.0.0 / routable interface unless explicit opt-in AND TLS configured; warn loudly in UI.
95. Reuse existing HTTP protections for the MCP transport — CORS allow-list, 1MB body cap, `X-Requested-With` enforcement where applicable (handshake exemption per R-61).
96. Three capability tiers — READ-ONLY (scans/portfolio/positions read), MUTATING-DEMO (trades/auto-trade on demo accounts), LIVE-MONEY (anything touching live Bybit funds).
97. Default tier READ-ONLY / backtest-only; mutating and live tiers opt-in and independently toggled.
98. LIVE-MONEY trade placement/closing FORBIDDEN via MCP unless the user separately, explicitly opts in through a distinct confirmation flow with prominent real-money warnings — never bundled with the master ON switch.
99. Hard demo-vs-live distinction — default exposes demo accounts only; live accounts filtered from account-listing tools until live tier enabled.
100. Per-tool capability gating tied to config — disabled destructive tool omitted from list AND rejected at dispatch (genuinely unreachable).
101. All tier/capability checks enforced server-side at execution time, re-read from authoritative config each call (never trust client-asserted capability).
102. Strict Pydantic-v2 schema per tool — typed args, explicit required/optional, `extra=forbid` to reject unknown/injected fields.
103. Symbols validated against allow-list/regex of known instruments before reaching the exchange layer.
104. Account IDs validated for existence AND ownership; agent cannot reference an account outside the app's set.
105. Numeric bounds enforced on every config/sweep arg (leverage, capital, position size, TP/SL, ranges, combo counts) with min/max and step caps.
106. scan_id / run_id / backtest_id validated as UUIDs / strict id format — no path traversal, no `../`, no raw string building file paths.
107. All DB access via parameterized asyncpg queries only; no string-concatenated SQL in MCP handlers.
108. Tool outputs never contain Bybit API keys/secrets — run every response through `mask_secrets` before it leaves the process.
109. The MCP token is never returned by any tool (no "show config"/"echo settings"/debug tool surfaces it).
110. Debug/config/account tools reuse the debug-repo credential-shaped-key stripping before serialization.
111. Block any tool that would dump raw DB rows, env vars, or the accounts table with encrypted keys; redacted views only.
112. Audit every tool invocation — principal/token id, timestamp, tool name, sanitized args, outcome (allow/deny/error), result summary, duration.
113. Audit log append-only and tamper-evident (hash-chained entries) so edits/deletions are detectable.
114. Audit args masked for secrets before persistence; denied + rate-limited attempts logged too.
115. Live-money actions get elevated audit records (before/after state, account, order id), retained longer.
116. Per-token rate limit on tool calls (calls/min) to stop a runaway agent hammering tools.
117. Separate, stricter throttle on exchange-facing tools to respect Bybit limits and prevent order spam / API bans.
118. Sweep/backtest resource caps — max concurrent backtests, max total combos per sweep, max queued jobs; reject over-cap instead of unbounded queue.
119. Per-tool execution timeout + memory cap; long tools cancellable via kill-switch; auto-abort on deadline.
120. Output size cap on every tool result (row/byte limit + truncation + pagination) to prevent exfiltration-by-bulk and context flooding.
121. Treat all market data, scan text, and agent-supplied strings as untrusted — never eval/exec, never build SQL/shell/paths from them, never let them widen a capability tier (confused-deputy guard).
122. Bound blast radius — a fully prompt-injected agent confined to the default tier can only read and run backtests; no path to live-money side effects without the separate human opt-in.
123. Fail-closed everywhere — any exception, config parse error, or ambiguous capability state denies the call; on startup config failure MCP stays OFF.
124. Idempotency keys on mutating tools (place/close trade) — client-supplied key deduped server-side so a retried call cannot double-execute.

## Observability & Operations [OBSERVABILITY]

125. Full audit trail surfaced via a read API/UI panel (redacted args, correlation/session id, latency, status).
126. Structured logging with a per-call correlation id linking MCP request → service call → backtest task → audit row; metrics (call counts, latency histograms, error rates, sweep throughput).
127. Error mapping — domain exceptions (Validation/NotFound/Conflict/Busy/BacktestRateLimit) translated to structured MCP/JSON-RPC tool errors with stable codes and actionable messages, not stack traces.
128. Live server status — running/stopped, uptime/last-started, active tool count, connected clients (names/ids if available), recent-activity feed, per-tool usage stats, last error.

## Performance & Scalability [PERF]

129. Output-size bounding — every tool response capped/truncated with explicit "truncated" markers; large list tools use cursor-based pagination.
130. Response shaping — `summary` vs `detail` verbosity + field-projection so analytics/backtest results return compact digests by default.
131. Caching of expensive read paths (cached klines, computed analytics, backtest metrics) reused across sweep combos to keep sweeps "seconds not minutes".
132. Equity-curve output downsampled to a bounded point count while preserving drawdown extremes.
133. Huge debug/agent-trace trees depth- and size-capped with truncation markers.

## Frontend / UI / UX [ROUTE/TOGGLE/TOOLBUDGET/SETUP/STATUS/SAFETY/OPTIMIZER/STATE/FORM/A11Y/RESPONSIVE/THEME/FEEDBACK/HELP]

134. New top-level route `/mcp` (`routes` + `route-tree.tsx`) rendered through the same `PageHeader` + neumorphism card shell as `ConfigPage.tsx`.
135. Nav entry in the **System** section of `navigation.ts` labeled "AI Agent (MCP)" with a distinct icon.
136. Status dot/badge on the nav item (green=running, gray=off, red=error) + mirrored in mobile dock.
137. Page structured as stacked sections / `ui/tabs`: Overview/Status, Tools, Connection, Safety, Optimizer, Activity — accordion on mobile.
138. Prominent master ON/OFF switch at top (switch role, default OFF, state pill).
139. Enabling opens a `ui/dialog` security-warning confirmation requiring explicit confirm; cancel reverts to OFF.
140. OFF state — muted "MCP disabled" hero with explainer + single enable CTA; downstream sections dimmed/non-interactive.
141. ON state — full control surface + "active" banner + one-click disable (also confirms).
142. Disabling while clients connected — warning in confirm dialog stating active sessions will drop + count.
143. Tool GROUPS as expandable neumorphism cards, each with a master group toggle + "X of Y enabled" count.
144. Each group expands to INDIVIDUAL tools with `ui/checkbox`, name, one-line description, `ui/tooltip` of params/return.
145. Group master toggle tri-state (checked / unchecked / partial/indeterminate).
146. Preset selector — Minimal/Standard/Full/Backtesting-only/Read-only; applying bulk-updates toggles; shows current preset or "Custom".
147. Global Select-all / Select-none + per-group select-all/none, with confirm/undo for bulk changes.
148. LIVE "N tools enabled" sticky indicator.
149. "Estimated context cost" token-budget meter (progress bar, green/amber/red, configurable warning threshold).
150. Budget warning over threshold — inline non-blocking warning to consider a smaller preset.
151. Search/filter input live-filtering tools by name/description, auto-expanding matches, highlighting; clear restores collapse.
152. Per-tool safety-class badge (Read-only/Backtest/Live-money).
153. Live-money tools individually disabled (greyed, lock icon + tooltip) until the live-money safety toggle is enabled.
154. Connection card — MCP endpoint URL + copy button + copy-confirmation; selectable, truncates on mobile.
155. Access token masked by default (`••••••`) with reveal toggle, copy, Regenerate; reveal ephemeral, re-masks on blur/nav.
156. Regenerate token — confirm dialog warning existing clients invalidated; success toast + updated token.
157. Ready-to-paste client config snippet (JSON for Claude Desktop/Code) in a code block + "Copy config", auto-filled with live URL + token; `ui/tabs` per-client variants.
158. "Copy all" / step-by-step per-client instructions; optional QR; "Test connection" button reporting reachability inline.
159. Status panel — running state, uptime/last-started, active tools, connected clients, last error + timestamp.
160. Recent tool-call activity feed / audit log (timestamp, client, tool, status, duration), newest first, empty state.
161. Activity feed filter by tool/group + outcome; rows expand to args/result summary.
162. Persistent "last error" banner with dismiss + "view details" into the activity log.
163. Safety section mode selector (Read-only / Backtest-only / Full) as a segmented control gating which tool classes can be enabled.
164. Red-accented "Allow live-money trade tools" toggle default OFF, strong warning, typed-confirm dialog ("type ENABLE to confirm").
165. Live-money enabled — persistent red caution banner on page + nav badge.
166. Optimizer section — list parameter-sweep jobs (id, status, progress bar, started, # configs evaluated).
167. Completed sweep row shows best `AutoTradeConfig` summary + "View backtests / Compare" link into the existing compare page.
168. Optional manual "Launch sweep" form (parameter ranges, base config) with validation + confirm; disabled when MCP OFF.
169. Running sweeps cancellable with confirm dialog; cancel/complete fire toasts.
170. Explicit states for every async section — loading skeletons, empty states, error states, saving spinners, disabled/feature-off styling.
171. Backend 503 (feature unavailable) handled with a dedicated panel ("MCP module not available on this deployment") + disabled controls.
172. Tool-budget changes use explicit Save with unsaved-changes guard (route-leave/beforeUnload) + sticky save/discard bar.
173. Optimistic UI for low-risk toggles with rollback; confirmed/pessimistic saves for master switch, live-money, token regen; inline validation on sweep form.
174. Full keyboard nav of the tool matrix (arrow/tab, type-ahead, Enter/Space toggle), `role=switch`/`aria-checked`, `aria-expanded` on groups, focus rings.
175. Screen-reader labels for every toggle/checkbox (group + tool + safety class), live-region announcements for "N tools enabled" + budget warnings, focus management on dialogs.
176. Responsive — mobile collapses tool matrix into accordions, sticky tool-count/budget meter docks to bottom, code snippets horizontally scrollable; respects mobile dock.
177. Dark/ivory neumorphism parity via shared `@/components/ui` primitives; semantic risk colors (amber warning, red live-money) accessible-contrast in both themes.
178. `sonner` toasts on enable/disable, preset applied, save success/failure, copy-to-clipboard, token regenerated, sweep launched/cancelled — paired with confirm dialogs for destructive/elevated actions.
179. Inline onboarding explainer — collapsible "What is MCP / what can the agent do?" panel (capabilities summary, why tool budget matters), link to per-client setup docs; prominent on first visit / when OFF.

## Errors & Edge Cases [ERROR/BOUNDARY/CONCURRENCY/FAILURE/OUTPUT/RETRY/STATE/COMPAT]

180. Agent-facing structured errors — feature OFF (503), invalid/expired token, tool disabled/unknown, invalid params, rate-limit/cap exceeded, backtest timeout.
181. Sweep & cache failure handling — partial-failure reporting (continue vs abort); "cache miss — run warmup first" actionable error before optimization.
182. Toggle OFF mid-sweep — defined policy: background sweep continues to completion (decoupled) OR cancelled; in-flight backtests never orphaned.
183. Disable mid-tool-call — in-flight call returns a clean defined error (server-shutting-down), not a hang/silent drop.
184. Rapid ON/OFF flipping — debounce, fully release+rebind port, no zombie server or leaked task.
185. Feature flips OFF — connected client `tools/list` empties + `listChanged` fires before session teardown.
186. Disabling a tool group while a tool executes — running call finishes or cleanly aborts per policy; tool gone from next list.
187. Direct call to disabled/unadvertised tool — method-not-found, never executes.
188. Empty search space — refuse up front with a validation error; no zero-backtest sweep.
189. Single-point search space — exactly one backtest, ranked trivially, no divide-by-zero.
190. Combinatorial explosion — hard cap; refuse/clamp with a clear message before scheduling any work.
191. Every backtest in a sweep fails — sweep ends `failed` with aggregated diagnostics; no corrupt "best".
192. Ties in ranking metric — deterministic documented tie-break (secondary metric then config hash).
193. Sweep cancelled midway — completed results retained/returnable; remaining combos not started; state `cancelled`.
194. Some grid configs invalid — invalid combos skipped + reported with reasons; valid ones still run.
195. Sweep throttled by BacktestRateLimitError — backpressure + bounded retry/backoff, not whole-sweep failure.
196. Invalid SL/leverage (liquidation) combo rejected by existing validator before any backtest runs.
197. `breakeven_timeout >= max_duration` rejected.
198. `close_on_profit` without `target_goal` rejected (existing validation).
199. Date range with no scan data — explicit empty/no-signals result, not a crash or misleading zero-trade "success".
200. Missing/partial kline cache — defined behavior (auto-fetch or precise "cache miss" error), never silent wrong numbers.
201. Two MCP clients connected — sessions isolated; shared resources (rate limiter, sweep registry) correct.
202. Concurrent sweeps — queued/parallelized within global rate limit, no deadlock/starvation.
203. Concurrent toggle writes to singleton row — row-level lock / atomic upsert prevents lost updates/split state.
204. Sweep backtests vs manual UI backtest competing for shared rate limiter — fair sharing, neither starved.
205. DB connection lost mid-call — clean service-unavailable error promptly, no indefinite await.
206. Backtest service `None` (degraded startup) — backtest/sweep tools return defined "service unavailable".
207. MCP init fails (bad port/config) — isolated, MUST NOT abort core trading startup.
208. Abrupt network drop to client — server detects dead session, cleans up tasks, frees resources.
209. Backend restart mid-sweep — interrupted sweep recovered to terminal/resumable state, never perpetually `running`.
210. Long tool exceeds timeout — defined timeout error + partial-result reference, no leaked task.
211. 50k-trade backtest paginated/truncated (cursor/summary), never one unbounded payload.
212. Token rotated mid-session — existing sessions invalidated/re-challenged; new connections require new token.
213. Bind port already in use — clear startup error, doesn't kill app startup.
214. Re-running create-backtest / duplicate sweep with same idempotency key returns the original job (deduped).
215. Sweep job state machine rejects illegal transitions (completed→running, cancel an already-completed job).
216. Older MCP client / protocol version negotiated gracefully (degrade cleanly or clear version-mismatch error).

## Configuration & Setup [CONFIG/SETUP]

217. Access mode selector — global Read-only / Backtest-only / Full, controlling which tool categories are eligible to be enabled.
218. Rate limiting & resource caps configurable — max concurrent backtests, max combos per sweep, request rate per client.
219. Default response verbosity & pagination size configurable to balance usefulness vs token cost.
220. Connection details display — server URL/endpoint, chosen transport, "test connection" button verifying reach+auth.
221. Auth token lifecycle UI — generate, view (masked), rotate, revoke; rotating invalidates old tokens.

---

## Round 1 Total: 221 requirements
## Rounds Completed: 1

---

# Round 2 — Gap-Finding (Integration, Backend, Security, Product/Optimizer, QA/Perf)

## MCP Protocol Conformance [MCP-PROTOCOL]

222. `initialize` handshake response contract — define exact result: `serverInfo {name, version}`, echoed `protocolVersion`, and `instructions` steering the agent toward optimizer prompts/sweep tools and away from the primitive run_backtest loop.
223. Full capabilities advertisement at init — declare `resources {subscribe, listChanged}`, `prompts {listChanged}`, and `logging`, not just `tools.listChanged`.
224. Protocol-version pinning + streamable-HTTP version header — enumerate supported MCP revision(s); respond to an unsupported requested version with the server's supported version (not a hard error); validate the `MCP-Protocol-Version` HTTP header post-handshake.
225. `isError` result semantics vs JSON-RPC protocol errors — tool execution failures return a successful JSON-RPC response with `isError: true` + agent-visible content; only malformed/unroutable requests use JSON-RPC error objects.
226. Standard JSON-RPC 2.0 error-code mapping — pin `-32700`/`-32600`/`-32601`/`-32602`/`-32603` + server-defined range; tie "disabled/unknown tool" rejection to `-32601 method not found`.
227. Structured tool output — advertise per-tool `outputSchema`, return `structuredContent` alongside text content blocks, using typed MCP content blocks (text / resource_link / embedded resource).
228. MCP tool annotations — populate `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` from the registry's `mutating`/`safety_class` fields.
229. Resource protocol surface — define resource URI scheme (e.g. `tradingagents://scan/latest`), `resources/read` returning `mimeType` + contents, `resources/templates/list` for parameterized reads, `resources/subscribe` + `notifications/resources/updated` for live snapshots.
230. Prompt protocol surface — define `prompts/get` (not just list), each prompt's argument schema, optional `completion/complete` argument autocompletion.
231. Progress token + request cancellation — emit `notifications/progress` keyed to the request `_meta.progressToken`; handle protocol-level `notifications/cancelled` to abort an in-flight request (distinct from the `cancel_sweep` tool).
232. `ping` / keepalive — respond to MCP `ping` and optionally issue keepalive pings for dead-session detection.

## Compatibility [COMPAT]

233. Exclude `/mcp` from OpenAPI — mount with `include_in_schema=False`; keep out of `/docs`/`/redoc` so the JSON-RPC sub-app never pollutes the OpenAPI document.
234. Reserve new `app.state` keys — namespace + startup assertion that `mcp_server`/`mcp_config`/`mcp_sweep_registry` don't collide with existing keys.
235. Reuse the shared `bybit_rate_gate` — exchange-facing MCP tools acquire the existing `app.state.bybit_rate_gate`, not a parallel limiter, so MCP + scanner + reconciler stay under Bybit limits collectively.
236. CSRF exemption boundary-safe — R-61 exemption matches only the exact `/mcp` subtree (no bleed into `/mcp-*` or `/api/v1/...`), with a regression test asserting existing endpoints still enforce CSRF.
237. Additive-only to shared code + signature contract tests — MCP must not break any existing service/router/schema signature; contract tests pin the exact service methods MCP depends on.
238. Reuse the existing background-task registry — register MCP sweep/backtest tasks in the same task tracking the app uses for graceful shutdown/health.

## Versioning & Forward-Compat [VERSIONING]

239. Schema-stamped saved sweeps — stamp each saved sweep with the AutoTradeConfig schema version; read-time coercion flags unknown/removed/renamed fields so historical sweeps stay loadable/comparable.
240. Stale-client schema tolerance — define major/minor `schema_version` semantics; breaking changes force a major bump + deprecation window; server tolerates old clients omitting newly-added optional fields.
241. Agent-discoverable version — expose app/MCP/contract version via `serverInfo.version` + a `get_server_info` resource/tool so the agent branches on capabilities.

## Interop [INTEROP]

242. Tag sweep-spawned backtests — mark sweep-created backtests `source=mcp_sweep` (+ `sweep_id`) in BacktestService so they're filterable in the existing list/UI and excluded from UI-backtest GC/retention.
243. Shared kline cache store — MCP cache-warmup tools write to the SAME cache store/keys as BacktestService so warmup benefits both UI and MCP backtests.

## External Client Specifics [CLIENT]

244. stdio↔HTTP bridge — document/ship an `mcp-remote` (npx) stdio bridge config for clients lacking native streamable-HTTP (Claude Desktop), wiring the bearer token through the bridge.
245. Per-client auth-header convention — specify `Authorization: Bearer <token>` and how each client supplies it (Claude Desktop `headers` block, Claude Code `--header`, generic); optional query-param fallback explicitly forbidden for security (see R-226 below supersedes).
246. Origin-header validation — validate `Origin` on the MCP transport (DNS-rebinding protection) in addition to localhost bind + CORS reuse.

## Contract Stability [CONTRACT]

247. Immutable, namespaced tool names — stable naming convention (e.g. `scans_list`, `backtest_create`); once published a name never changes (rename = new tool + deprecate old).
248. Output field/enum stability — output field names additive-only; enum string values (sweep status, close reason, safety_class) append-only / never repurposed; documented as the agent-facing contract.
249. Declared units, precision, timezone & money format — every numeric/time output declares unit/precision (% vs bps, decimals, UTC ISO-8601); money serialized to avoid float drift.

## Backend Service Design [SERVICE/SWEEP-ENGINE/TRANSACTION/ERROR-MAP/POOL/REUSE/DATA-LAYER/LIFECYCLE]

250. Class decomposition — `MCPServer` (transport/session/dispatch), `MCPService` (tool-handler orchestration), `ToolRegistry` (manifest + enablement resolution), `SweepOrchestrator`, repositories `MCPConfigRepository`/`AuditRepository`/`SweepRepository`; constructor-injected deps, wired in `create_app()` lifespan.
251. Tool handlers are thin adapters (validate → call injected service → map errors → shape response) with NO business logic and NO direct SQL; unit-testable with fake services, no transport/DB.
252. Config caching reconciled with per-call-authoritative reads — cache only non-security config (enabled groups/tools, verbosity), invalidated synchronously on config-change; token validity, `allow_real_trades`/live-money gate, tier remain read-through-authoritative per call.
253. Data access isolated behind repository classes returning typed domain objects (no asyncpg in handlers/orchestrator), mirroring the debug-repo pattern.
254. Deterministic combination generator — grid (cartesian) / seeded-RNG (random) / coarse-to-fine (smart), each emitting a canonical key-sorted type-normalized config dict; identical inputs yield identical ordered combo list.
255. Combo dedup via canonical config hash (stable JSON, sorted keys, normalized numerics) before enqueue; data layer enforces uniqueness on `(sweep_id, config_hash)`.
256. Shared-kline pre-warm phase — warm/validate full cache coverage ONCE up front, then fan out all combos against that immutable snapshot (no per-combo fetch).
257. Pool/UI-aware fan-out — sweep semaphore sized strictly below `max_concurrent_backtests`, reserving BacktestService capacity (lower-priority lane) for UI-initiated backtests.
258. Metric aggregation is a pure, separately-unit-testable function reusing the existing backtest metrics module (no re-implemented math); NaN/Inf quarantine applied here.
259. `SweepOrchestrator` depends on a `BacktestRunner` Protocol/ABC that BacktestService satisfies and a `FakeBacktestRunner` implements, so sweeps unit-test deterministically.
260. Atomic config update — `PUT /mcp/config` is a single serialized UPSERT with optimistic concurrency (version/`updated_at` precondition) and row-locked read-modify-write of the JSONB sets (prevents lost updates from concurrent tabs).
261. Non-blocking durable audit writes — tool calls enqueue audit records onto an in-process buffer flushed by a dedicated writer off the hot path; response never blocks on the DB write; bounded queue, synchronous fallback on overflow, flush-on-shutdown.
262. Hash-chain integrity under concurrency — audit appends serialized through a single writer so concurrent calls can't fork the chain; continuity seeded from last persisted hash across restarts.
263. Incremental crash-safe sweep persistence — each combo result written in its OWN committed transaction, atomically incrementing `completed_combos`; a crash never loses finished combos.
264. Central exception→MCP-error mapping table with retryable flags — ValidationError→invalid-params (terminal), NotFound→not-found, Conflict→conflict, Busy/BacktestRateLimit→busy/rate-limited (retryable+backoff hint), pool-timeout/DB-down→service-unavailable (retryable).
265. Dispatcher catch-all boundary — every handler in a try/except mapping known exceptions and converting any unmapped exception into a generic internal-error envelope (logged w/ correlation id); a service exception can never crash the MCP session/dispatcher/event loop.
266. Pool-aware capacity — derive `max_concurrent_backtests` + total MCP concurrency from asyncpg pool size with reserved headroom for core trading/UI; documented so a sweep can never starve the app.
267. Acquire-with-timeout + connection-per-operation — every MCP/sweep DB access acquires with a bounded timeout (fail fast → service-unavailable) and releases immediately; background sweep tasks never hold a pooled connection across combo execution.
268. Single backtest engine — sweeps drive backtests EXCLUSIVELY through the existing BacktestService path (shared filter-chain, sizing, close-rules); no duplicate backtest/sizing implementation in sweep code.
269. Read-method inventory — enumerate which MCP reads map to EXISTING side-effect-free service methods vs which need NEW thin read-only repository methods (e.g. fetch a scan's ranked signals without re-running analysis).
270. Keyset (seek) pagination — list tools paginate via an opaque tamper-validated cursor encoding `(sort_key, last_id)` over an indexed column; stable under concurrent inserts; server-enforced max page size.
271. Indexes for new tables — `mcp_audit_log(started_at DESC)` + `(tool_name, group, status)`; `mcp_sweep_results(sweep_id, rank)` + `(sweep_id, config_hash)`; `mcp_sweep_jobs(status)`.
272. DB-level idempotency — unique constraints back mutating-action + sweep-job idempotency keys + combo dedup, using `INSERT … ON CONFLICT` so dedup is race-safe.
273. Background-task registry — every sweep `create_task` held in a strong-referenced set with a done-callback that removes it and logs exceptions (prevents GC of in-flight tasks).
274. Bounded shutdown drain ordering — stop accepting new sweeps → cooperative cancel → await with timeout → force-cancel stragglers → persist partial + flush audit.
275. Transactional boot recovery — atomically claim `running` sweeps (`UPDATE … WHERE status='running' RETURNING`) guarded against double-claim, BEFORE the server advertises tools.
276. Resumability read by config hash — on resume, read the SET of completed `config_hash`es and skip them (not a `completed_combos` count).

## Security — Round 2 Gaps [CSRF-MOUNT/TOKEN/CONFIG-WRITE/ESCALATION/SUPPLY-CHAIN/RESOURCE-PRIORITY/EXFIL/REMOTE-HARDENING/RETENTION/REPLAY/TOCTOU/SECURE-DEFAULT]

277. Host-header allowlist — validate `Host` against (`127.0.0.1:<port>`, `localhost:<port>`); reject others as DNS-rebinding defense (bearer auth alone doesn't stop rebinding from reaching the socket).
278. Reject browser `Origin` on the CSRF-exempt mount — transport rejects any request with a non-allowlisted browser `Origin` (legitimate MCP clients send none); CORS never reflects arbitrary origins nor pairs Allow-Credentials with wildcard.
279. Token TTL/expiry — configurable expiry (not infinite-life) with a "must-rotate-by" date surfaced in UI; expired tokens fail closed (401).
280. Multiple named per-client tokens — each independently revocable with its own scope and audit principal; revoking one client never disrupts others.
281. Token only via `Authorization: Bearer` — auth via URL query/path forbidden and rejected (keeps it out of access logs/history/Referer); no intermediary may log the Authorization header. (Supersedes the R-245 query-param fallback.)
282. Apply-to-scanner requires out-of-band human approval in the app UI — the MCP agent may only PROPOSE; no tool argument (`confirm=true`) can satisfy the gate.
283. Apply field-level diff persisted with the approval record — current vs proposed config; high-risk fields (leverage, position size, account binding) visually flagged.
284. Applied config sanitized — can never set/raise live-trading-enabling fields (`allow_real_trades`, live-account binding, auto-trade-on); such fields stripped or apply rejected.
285. Config-write elevated before/after audit record including approver identity, the diff, and source sweep id.
286. No MCP tool may mutate `mcp_config` — cannot enable groups/tools, flip safe-mode flags, change tier/access mode, or alter `bind_host`; a read-only agent has zero path to widen its own tier.
287. No MCP tool may read/generate/rotate/revoke the auth token, toggle master/kill-switch, or disable/pause/clear/rotate the audit log, or change rate-limits/caps.
288. Registration-time deny-list — an enumerated set of sensitive service methods/endpoints (config writers, token lifecycle, audit, kill-switch, debug_config writes) that may NEVER be wrapped as a tool; registry rejects them at build/startup.
289. MCP SDK + transitive deps hash-pinned in the lockfile (no floating ranges); upgrades go through documented security review.
290. Audit + override the MCP library's own defaults (bind host, auth, CORS, session caps); assert the SDK doesn't open its own unauthenticated port or permissive CORS (verify FastMCP doesn't default to 0.0.0.0/no-auth).
291. CI dependency vulnerability scan (pip-audit/SCA) + SBOM for the MCP dependency tree, gating on known CVEs.
292. Live-trading loop hard priority — scanner, position reconciler, close-rule evaluator, auto-trade executor have scheduling priority over all MCP work; MCP sweeps/backtests/tool calls yield/pause under contention.
293. Bounded separate DB connection-pool allocation for MCP that cannot exhaust/starve the pool the live-trading loop depends on.
294. CPU-heavy sweep/backtest work offloaded off the main event loop (executor/worker); a health circuit-breaker auto-suspends/throttles MCP when live-trading latency/health degrades, resuming when healthy.
295. Per-tool/field data-sensitivity classification (public/internal/financial/secret); sensitive classes require an elevated tier or explicit opt-in and are unavailable in default read-only mode.
296. Account balances + absolute monetary P&L aggregated/redacted by default (ratios/percentages); raw figures require an explicit "financial detail" opt-in distinct from the master switch.
297. Cumulative per-session/per-token data-volume budget (anti-bulk-exfil) beyond per-call caps; bulk pulls throttled and flagged as exfil-anomaly in audit.
298. Outputs use app-internal opaque ids, never raw Bybit account UIDs / exchange identifiers meaningful outside the app.
299. Non-local binding fails closed unless ALL of: valid TLS (≥1.2, no plaintext fallback), an IP allowlist, and per-client short-TTL tokens (a single shared infinite token rejected in remote mode).
300. Remote mode adds auth-failure/anomaly alerting + brute-force lockout + auto-tightened rate limits; remote + live-money tier needs an additional explicit confirmation and is blocked by default.
301. Configurable audit-retention policy — live-money/financial records retained per regulatory minimum, routine logs purged shorter; records with account ids/amounts access-controlled (restricted read API) and encrypted at rest.
302. GDPR/data-subject erasure via tombstoning that preserves the hash-chain's tamper-evidence (erase payload, keep chain verifiable).
303. Replay protection — mutating/exchange-facing calls carry a nonce + timestamp; reject stale-timestamp (outside skew window) or previously-seen nonce (idempotency keys stop accidental re-exec, not malicious replay).
304. Idempotency keys TTL-bounded and scoped to token+session, so a captured key can't be replayed later or across sessions.
305. TOCTOU fence — re-verify capability atomically immediately before any side-effecting exchange call; capture a config snapshot/epoch at dispatch; if the epoch advanced (tier revoked, kill-switch, token rotated) before the order, abort fail-closed.
306. First-enable force-generates a strong token if none exists; server refuses to start/accept connections with a blank/null/weak/known-default token (fail closed).
307. Default/first-enable toolset contains ZERO mutating/live tools (read-only only); no preset or migration may pre-enable a write/live tool.
308. Missing/corrupt `safe_mode_flags` JSONB interpreted as most-restrictive (`read_only=true`, `allow_real_trades=false`), never permissive.

## Optimizer & Product Value — Round 2 Gaps [OBJECTIVE/BASELINE/EXPLAINABILITY/REALISM/ADOPT/ITERATION/REPORTING/ONBOARDING/FEASIBILITY/TRUST]

309. Persisted user guardrail+objective profile (set once, agent cannot override) — hard constraints (max DD ≤ X, min trades ≥ N, min win rate, max leverage) + primary objective every sweep inherits by default; the agent must respect and cannot loosen it.
310. User-language risk presets (Conservative/Balanced/Aggressive) mapping to objective+constraint bundles, so non-quant users express intent without naming raw metrics.
311. Consistency/stability objectives in the metric library — % profitable months/rolling windows, longest losing streak, equity-curve smoothness (R²), Calmar (return/maxDD).
312. "Keep current config" null-result honesty — optimizer explicitly returns "no candidate robustly beats what you run today" when true, instead of always crowning a winner.
313. Baseline backtest of the live AutoTradeConfig — automatically run the CURRENT config through the same harness to establish incumbent metrics as the reference point.
314. Delta/uplift scoring vs baseline — every candidate reported as improvement over the live config (Δreturn, ΔmaxDD, ΔSharpe, Δexpectancy), rankable/filterable by uplift.
315. Seed the search space from the current config — center the sweep on live parameter values; default the backtest window to the live schedule's actual run history/regime.
316. Apples-to-apples harness lock — baseline and all candidates forced to identical capital, fees, slippage, date range, symbol universe; mismatched comparisons rejected.
317. Natural-language "why this config won" rationale — which parameters drove the result, trade-offs vs baseline, in plain language.
318. Robustness/confidence VERDICT as a first-class graded output (Robust/Moderate/Fragile/Likely-overfit) with reasons, not just a boolean flag.
319. Winner + baseline equity & drawdown curves returned together (downsampled) for visual side-by-side comparison.
320. Provenance on every recommendation — each metric traces to a stored `backtest_id`, date range, data snapshot, schema version, seed; the agent never surfaces an untraceable number (anti-fabrication).
321. Backtest-fidelity disclosure on every projection — surface the known ~1% backtest-vs-live deviation + modeling assumptions (fees, slippage, fill, no order-book depth) as a caveat/confidence band.
322. Multiple-testing / data-snooping warning scaling with # configs evaluated — "you tested N configs; expect some to look good by chance," with in-sample vs out-of-sample degradation %.
323. Monte Carlo / confidence intervals on projected return & drawdown (trade-sequence resampling) — report a distribution, not a single point estimate.
324. Multi-regime / multi-period validation — validate the winner across sub-periods (bull/bear/chop); flag configs that only work in one regime.
325. Minimum data-sufficiency guard — refuse to declare a winner (or hard-warn) when trade count / period is too small to be statistically meaningful.
326. Config DIFF view — show exactly which AutoTradeConfig fields change (live → proposed) with old/new values before any apply.
327. Dry-run / shadow (paper) adoption — apply the proposed config to the live scanner in non-trading simulation for a probation period before real money.
328. Staged rollout — adopt with reduced capital/position size first, ramp up on confirmation.
329. One-click revert + applied-config version history — snapshot the live config at apply time; instantly restore the prior config if the new one underperforms.
330. Human-only apply gate — the agent may recommend but can never write the live AutoTradeConfig via MCP; adoption requires explicit human confirmation in the app UI.
331. Refine/extend a prior sweep across sessions — launch a finer search centered on a previous winner (cross-session coarse-to-fine), reusing prior results.
332. Adopted-config performance tracking — record an adopted config and compare its REAL scanner performance against its backtested expectation over time (predict-vs-actual loop, drift detection).
333. Agent-readable "optimization memory" — a durable champion record (current best config, what's been tried, last sweep, adopted history) loaded at session start so new sessions build on prior work.
334. Generated human-readable optimization report artifact (markdown/PDF) — objective+guardrails, search space, baseline, winner, runner-ups, sensitivity, equity/DD curves, robustness verdict, caveats — exportable.
335. Copyable example prompts / playbooks in the UI ("Optimize for max Sharpe with DD < 15% and ≥30 trades", "Is my current config still optimal?") + plain-language capability catalog.
336. Field-level sweep metadata + first-run guided setup wizard — per AutoTradeConfig field: type, valid range, step, sweepable?, expected impact; plus a guided "generate token → copy snippet → test → enable preset → try example prompt" flow.
337. User-facing live ETA, throughput (configs/sec), and completion push notification (the app has push) so the user can walk away.
338. "Too good to be true" anomaly flag + standing simulation-only guarantee — auto-flag suspicious returns / unrealistic Sharpe / single-trade-dominated results; display that optimization is simulation-only and moves no real money.

## QA / Testability / Performance Targets — Round 2 Gaps [TESTABILITY/UNIT/INTEGRATION/CONTRACT-TEST/PROPERTY/PERF-TARGET/LOAD/REGRESSION/FIXTURE/METRICS/SMOKE]

339. Handler signature `handler(validated_args, ctx)` with ctx carrying injected deps — handlers never reach `app.state.*`/module globals; unit-testable with fakes, no transport/loop.
340. `FakeBacktestRunner` test double implementing the BacktestService interface, returning deterministic metrics keyed by config-hash in <1 ms/call.
341. Seeded klines factory `make_klines(seed, symbol, timeframe, start, end)` producing reproducible OHLCV; byte-identical metrics across runs; shared pytest fixture.
342. Deterministic seeded scan-results fixture (persisted via a test factory) so backtests have a stable signal source decoupled from live scanning.
343. Canonical "golden sweep" — seeded scan + klines + a small grid (e.g. 3×3×3 = 27 combos) with exactly one known-winning config; the determinism/regression anchor.
344. Transport tests drive the FastMCP sub-app via in-memory ASGI transport (no TCP port) exercising full `initialize → tools/list → tools/call` in CI.
345. Session-lifecycle test — `Mcp-Session-Id` issuance, reuse, isolation between two concurrent in-memory sessions, teardown-on-disable, without a real socket.
346. Per-tool schema-equivalence test — advertised input JSON Schema equals `PydanticModel.model_json_schema()`; drift fails the build (parametrized over the registry).
347. Registry-completeness test (parametrized over ALL tools) — each has: non-empty schema, callable handler, valid `safety_class`, an error-mapping entry per domain exception it can raise, emits exactly one audit row, `mutating: bool` set.
348. Error-mapping golden snapshot — every domain exception maps to a stable JSON-RPC code; snapshot asserts the code→message set is exhaustive and unchanged.
349. Combination-generator property test (Hypothesis ≥1000 examples) — grid count == product of cardinalities, zero duplicate combos, every combo within bounds, cap rejection at exactly `max_sweep_backtests`.
350. Random-search generator produces exactly N distinct combos for N ≤ space size, reproducible under a fixed seed.
351. Toggle/registry state-machine property test — for random toggle sequences the advertised set always equals the most-restrictive resolution, never contains a disabled tool, round-trips through persistence unchanged.
352. Golden ranking test — golden-sweep fixture reproduces a known top-N ordering and the exact tie-break path (secondary metric → config hash) byte-for-byte.
353. [PERF] Read-tool latency (in-process, default pagination, warm pool): p50 < 50 ms, p95 < 200 ms.
354. [PERF] Sweep throughput: FakeBacktestRunner schedules+collects ≥500 combos/sec; real cached-kline backtests ≥50 backtests/sec/core; max sweep size = `max_sweep_backtests` (default 5000).
355. [PERF] Sweep memory ceiling: a 5000-combo sweep grows RSS by <512 MB (results streamed to DB incrementally).
356. [PERF] Output-shape numbers: equity curve downsampled to ≤1000 points (drawdown extremes preserved), trade-list default page ≤500 rows, backtest detail at `summary` verbosity ≤256 KB serialized.
357. [PERF] Audit write non-blocking: adds <5 ms p95 to a tool call's critical path; test asserts latency with audit on vs off differs by <5 ms p95.
358. [PERF] Tool-schema token budget per preset: Minimal ≤2,000, Standard ≤8,000, Full ≤20,000 tokens of serialized advertised schema; estimated-vs-actual within ±10%.
359. [LOAD] A `max_sweep_backtests` sweep (FakeRunner) completes in <60 s in CI; after completion `asyncio.all_tasks()` returns to baseline (no leaked task).
360. [LOAD] asyncpg pool non-exhaustion under 50 concurrent tool calls + 5 concurrent sweeps; acquisitions never exceed pool max; no PoolTimeout; pool returns to idle.
361. [SOAK] Leak guard — 10,000 sequential tool calls + 1,000 toggle ON/OFF flips grow RSS <50 MB; session-table, registry, and `all_tasks()` at baseline.
362. [REGRESSION] OFF-path zero-overhead — with MCP disabled, `/mcp` returns 404/503, no MCP background task, startup issues no DB query beyond the single `mcp_config` read, startup-time delta vs feature-absent build <50 ms.
363. [REGRESSION] Behavioral-equivalence — existing app test suite passes unchanged with MCP present-but-OFF; golden test asserts representative existing endpoints return identical responses vs pre-feature baseline.
364. [REGRESSION] Core-trading isolation — force MCP init to raise; assert trading startup still succeeds with `app.state.mcp_server is None`.
365. [SMOKE] Generated client-config validity — a test parses the UI-produced JSON snippet, injects live URL+token, connects an MCP client, lists tools, calls one read tool, runs a 2-combo sweep.
366. [SMOKE] One full e2e against an ephemeral port (`port=0`) — real streamable-HTTP client initializes, lists tools, calls a read tool, launches+polls a tiny sweep to completed (slow/serial).
367. [METRICS] Emit + assert `mcp_sweep_throughput`, `mcp_tool_error_rate`, `mcp_audit_completeness`; a mixed-workload test asserts audit_completeness == 1.0.
368. [METRICS] Reproduce-from-audit — a documented procedure + test takes one audit row and re-issues it in a sandbox, reproducing the same error code / outcome class.
369. [TESTABILITY] Injectable clock for all timeout/next_run/duration logic; tests use a frozen clock; no sleep-based waits.
370. [TESTABILITY] No hard-coded ports in tests — in-memory ASGI or `port=0`; CI greps and fails on any literal port binding.
371. [TESTABILITY] Background-task determinism — an `await_sweep(sweep_id)` helper resolving on terminal state with a hard timeout; sweep tests await this rather than sleeping.

---

## Round 2 Total: 150 new (R-222..R-371) — Cumulative: 371
## Rounds Completed: 2

---

# Round 3 — Gap-Finding (Architecture, DevOps, Database, Performance, Maintainability)

## Architecture & Layout [LAYOUT/REGISTRY-EXT/TAXONOMY/SEPARATION/CONVENTION/EXTENSIBILITY]

372. Single self-contained package — the whole feature under `backend/mcp/` (`core/`, `tools/`, `repositories/`, `router.py`, schemas). Removal = delete the dir + one mount line + leave additive migrations. No MCP logic in `backend/services/` or `backend/routers/`.
373. One-way dependency rule, CI-enforced — `backend/mcp/**` MAY import services/schemas/db; nothing outside `backend/mcp/` may import `backend/mcp/**` (sole exception: the single mount call in `create_app()`). Enforce with import-linter / AST import-scan test.
374. Single integration seam — exactly one `mount_mcp(app)` function is MCP's only touchpoint in `create_app()`/lifespan; `main.py` references no MCP class names.
375. Lazy `app.state` resolution + clean-removal proof — MCP modules resolve service singletons from `app.state` at call time, never at module load (prevents circular imports). Test: `import backend.mcp` constructs no services, opens no DB connection.
376. Decorator-based self-registration; no god-file — adding a tool = one module under `backend/mcp/tools/<group>/` exposing a `@tool(name=, group=, input_schema=, output_schema=, safety_class=, mutating=)` handler, auto-discovered by package import scan. No central tool-list edit required.
377. Per-tool co-location ("one place to edit") — a tool's input/output schema, handler, safety_class, MCP annotations, error-map contributions, and audit metadata all live in its single module; the central error table is assembled FROM per-tool contributions.
378. Cross-cutting concerns applied by the dispatch pipeline, not per-handler — auth/tier-gate, audit, error-mapping, output-capping, pagination, per-call timeout applied uniformly by the dispatcher wrapping every handler.
379. "How to add a tool" recipe + scaffold — a ≤1-page in-repo guide, a copy-paste template tool module, and a scaffold test that fails until a new tool declares schema + handler + safety_class + error-map + audit.
380. `ToolGroup` enum is the single declared taxonomy — every tool declares exactly one group; tests assert no orphan groups and every group has ≥1 tool; group values append-only.
381. Presets defined as predicates over registry metadata, not name lists — Minimal/Standard/Full/Read-only/Backtest-only computed by predicates over safety_class/group/mutating; new tools auto-classify; presets can't drift from the tool set.
382. Single-source-of-truth sync tests — the registry is the ONLY catalog; UI browser, budget estimates, presets, docs all derive from it; tests forbid any parallel hardcoded tool/group list and assert Minimal/first-enable contains zero mutating tools.
383. Trading-free core — `backend/mcp/core/` (transport, session, dispatch, registry, audit, auth, error-mapping, pagination, output-shaping) MUST NOT import any trading domain; trading tools depend on core, never the reverse (import-linter enforced).
384. Core testable via a built-in example tool — a dependency-free `core_ping` ships with core so the plumbing's initialize→list→call→audit path is unit-tested with zero trading deps.
385. Shared response-shaping utility — verbosity/projection/truncation/keyset-pagination implemented ONCE in core and reused by every tool; per-tool re-implementation forbidden.
386. Control-plane vs data-plane split — the config/status/audit-read API is a NORMAL FastAPI router at `/api/v1/mcp/...` (router→service→repository→schema, debug feature as template); only the JSON-RPC data-plane is the special ASGI sub-app (kept out of OpenAPI).
387. Mirror the debug-feature precedent for placement/naming/wiring — repositories mirror debug-repo; control-plane schemas in `backend/schemas/`; migrations append to `_MIGRATIONS`; `app.state` reserve-and-assert; frontend via `client.ts`; tests under `tests/backend/mcp/`.
388. Transport abstraction seam — dispatch/registry/audit behind a `Transport` interface so streamable-HTTP (default) and stdio share one code path; active transport config-selected.
389. Pluggable auth-provider seam — auth behind a `TokenAuthenticator` interface (bearer for MVP) so future OAuth/mTLS drops in without changing dispatch/tools.
390. Config-driven behavior over constants — caps, timeouts, page sizes, bind host, default verbosity, transport, enabled sets read from `mcp_config`/settings; a test fails on hardcoded numeric limits/ports in `core/`.

## Architecture Decision Records [ADR]

391. One ADR per load-bearing decision in `docs/adr/` — (a) embedded-FastAPI vs standalone, (b) streamable-HTTP vs stdio vs legacy SSE, (c) in-process call-path vs ASGI-loopback vs real-HTTP, (d) optimizer-as-tool vs primitive-loop, (e) decorator self-registration. Each "documented as" clause points at its ADR.
392. Living architecture/boundary doc + add-a-tool guide — module map (core vs tools vs control-plane), the one-way dependency rule, owned `app.state` keys, clean-removal procedure; updated in the same PR when a boundary changes.

## MVP Phasing & YAGNI Deferrals [YAGNI/PHASING]

393. MVP optimizer = grid + random + baseline only — DEFER to a later phase: smart/coarse-to-fine search (R-19), Pareto frontier (R-23), walk-forward/IS-OOS (R-24), sensitivity analysis (R-25), Monte Carlo CIs (R-323), multi-regime validation (R-324). MVP keeps R-20/21/22/313/314/316.
394. MVP adoption = propose + human apply only — DEFER: shadow/paper probation (R-327), staged capital rollout (R-328), cross-session refine (R-331), predict-vs-actual tracking (R-332), optimization-memory champion (R-333), generated md/PDF report (R-334). MVP keeps R-282/R-330 (human apply gate), R-326 (diff), R-329 (revert/version history).
395. MVP networking = localhost + single bearer — DEFER: non-local TLS/remote hardening (R-299/300), multiple per-client tokens (R-280), retention+encryption-at-rest (R-301), GDPR tombstoning (R-302), CPU-offload executor + circuit-breaker (R-294). MVP keeps R-93/94 (127.0.0.1), R-87..92 (single hashed bearer), R-82/118 (semaphore caps).
396. Defer replay machinery; keep TOCTOU — DEFER nonce+timestamp replay (R-303/304); localhost+bearer+idempotency keys (R-124) suffice while live-money is OFF. KEEP R-305 (TOCTOU re-verification) for any mutating path.
397. MVP protocol surface = static resources + prompts — DEFER `resources/subscribe`+`notifications/resources/updated` (R-229) and `completion/complete` (R-230). MVP ships `resources/list`+static `resources/read` and `prompts/list`+`prompts/get`.
398. Phase 0 walking skeleton — first deliverable proves the spine end-to-end: master toggle OFF→ON, `/mcp` mount + bearer auth, ToolRegistry + dispatch pipeline, ONE read-only tool (`scans_list`), `mcp_config` + `mcp_audit_log` tables, a green in-memory-ASGI initialize→list→call test emitting one audit row.
399. Codified phase dependency order, each shippable behind OFF — P0 skeleton → P1 read-only tools + resources/prompts → P2 control-plane config/budget/safety UI → P3 backtest tools + kline cache → P4 optimizer core (grid/random/baseline) → P5 advanced optimizer → P6 remote/hardening. Build registry+dispatch+auth+audit BEFORE any tool; SweepOrchestrator only after backtest tools are green.

## DevOps / Operations — MULTIWORKER (Correctness) [MULTIWORKER]

400. Declare & enforce the supported process topology — the design assumes ONE process (in-process mount, singleton config cache, in-memory sweep registry + rate limiter, single-writer hash-chain, in-process task set). Under `uvicorn --workers N` every assumption breaks. Spec MUST pick: (a) hard single-worker requirement when MCP enabled, (b) DB-shared state, or (c) advisory-lock leader. Recommended: (a)+(c).
401. Startup guard against multi-worker + MCP-enabled — at lifespan init detect worker count (`WEB_CONCURRENCY`/uvicorn `--workers`); if >1 and `mcp_config.enabled`, refuse to mount (degrade `app.state.mcp_server=None`, log loudly, surface in `/health`) or elect a leader — never silently run N MCP servers.
402. Advisory-lock leader election — if multi-worker supported, exactly one worker takes a dedicated pg advisory lock (distinct from the migration lock) and owns background sweeps, boot recovery, the audit writer, and the sweep registry; on leader death the lock releases and another worker takes over.
403. Session affinity or shared session store — `Mcp-Session-Id` must be sticky-routed (documented reverse-proxy affinity) or persisted to a shared store so a follow-up POST hitting a different worker resolves the session.
404. Cross-process config-change & kill-switch propagation — hot enable/disable, token rotation, kill-switch fire an in-process event reaching only the local worker; define DB-epoch polling / LISTEN/NOTIFY / version-column so every worker re-reads `mcp_config` and drops sessions within a bounded window. A kill-switch disarming only 1 of N workers is a security defect.

## DevOps — Environment & Binding [ENV/BINDING]

405. Define the MCP env-var set (mirroring `_ENV_MAP`, `TRADINGAGENTS_MCP_` prefix) — `MCP_ENABLED`, `MCP_BIND_HOST`, `MCP_PORT` (or same-port/unset), `MCP_TOKEN` (bootstrap), `MCP_MAX_SWEEP_BACKTESTS`, `MCP_MAX_CONCURRENT_BACKTESTS`, `MCP_RATE_LIMIT_PER_MIN`, `MCP_SESSION_TTL`, `MCP_TOKEN_TTL`, `MCP_ALLOW_REMOTE_BIND`. Ints via `_validated_int`.
406. Precedence: env override > DB `mcp_config` > coded default — security fields (`MCP_BIND_HOST`, `MCP_ALLOW_REMOTE_BIND`, force-OFF `MCP_ENABLED`) are env-only; when set, UI/API can't override and show the field read-only ("managed by environment").
407. `MCP_ENABLED` is tri-state — unset ⇒ DB toggle governs; `=false` ⇒ hard force-OFF (ops kill-switch the UI/API can't override); `=true` ⇒ force-ON only on fresh DB, still honoring off-by-default upgrade unless explicitly acked. Document the truth table.
408. Resolve same-port-mount vs `bind_host` contradiction — a mounted sub-app inherits uvicorn's `--host`, so MCP-level `bind_host` is a no-op. Decide: (a) same-port ⇒ drop `bind_host`, enforce loopback via deploy + Host/Origin allowlist; or (b) separate listener on `MCP_PORT` with a real `bind_host`. State which.
409. Reverse-proxy runbook for streamable-HTTP — `proxy_buffering off`, chunked/streaming for the long POST, `proxy_read_timeout` above the longest poll, pass-through of Authorization/Mcp-Session-Id/MCP-Protocol-Version, real Host/Origin forwarding so allowlists work.
410. Frontend talks ONLY to `/api/v1/mcp/*`, never `/mcp` — the browser uses the same-origin control API; `WEB_CSP_CONNECT_SRC` needs no `/mcp` entry; "test connection" hits a backend proxy endpoint, not `/mcp`.

## DevOps — Upgrade / Health / Secrets-Ops / Observability-Ops / Limits / Rollout / Runbook

411. Off-by-default on upgrade of an existing deployment — seed sets `enabled=false` only on singleton INSERT; on an existing DB never flip a prior value; new columns default OFF. Test: upgrade a populated pre-MCP DB ⇒ `enabled=false`, no transport mounted.
412. Backward-migration / rollback contract — new tables + `mcp_config` additive/forward-only, may be left in place on downgrade; older build ignores them; no FK from existing tables INTO mcp tables; a down-migration refuses to drop `mcp_audit_log` while retention requires it.
413. Drain connected MCP clients on shutdown/deploy — on SIGTERM stop new sessions, empty tools/list_changed, close streamable-HTTP sessions within a grace window (inside the platform termination grace), then exit.
414. Rolling-deploy version skew — only the leader drives sweeps; `schema_version` tolerance handles contract skew; if single-instance required, document blue-green/Recreate instead of rolling when MCP enabled.
415. Surface MCP sub-status in `/api/v1/health` — add `mcp: {enabled, state: off|running|degraded, leader, active_sessions, last_error_at}`; MCP degraded MUST NOT flip overall status to 503 but must be visible; `/healthz` stays MCP-agnostic.
416. Dedicated `/api/v1/mcp/health` control endpoint — same-origin (existing API auth, not the bearer transport) returning enabled/mounted/leader/session-count/sweep-queue-depth/audit-backlog/circuit-breaker; returns 200 when OFF (feature-disabled is healthy).
417. Headless/CI token bootstrap & rotation without the UI — `MCP_TOKEN` env hashed-and-stored at boot when no hash exists; a management command (`python -m backend.manage mcp rotate-token`) printing the token once and updating the hash; both reuse the hashing, never log plaintext, tear down sessions on rotate.
418. Backup/restore covers the new tables; token survives restore — document `mcp_config` (incl. `access_token_hash`), `mcp_audit_log`, `mcp_sweep_*` in the backup set; hash-chain re-seeds continuity from the restored last hash; the hashed token doesn't depend on `ACCOUNTS_ENCRYPTION_KEY`.
419. Non-prod clones must not carry the prod token / must not auto-enable — a staging DB cloned from prod inherits `enabled` + `access_token_hash`; require a post-clone force-OFF + token rotation (or `MCP_ENABLED=false` in non-prod); warn the client-config snippet embeds a live token never to be committed.
420. MCP metrics register into the EXISTING `metrics.prometheus_text()` `/metrics` — pin series+labels: `mcp_tool_calls_total{tool,group,status}`, `mcp_tool_latency_seconds`, `mcp_sweeps_active`, `mcp_sweep_throughput`, `mcp_active_sessions`, `mcp_audit_queue_depth`, `mcp_audit_completeness`, `mcp_rate_limited_total`, `mcp_circuit_breaker_state`, `mcp_enabled`(0/1), `mcp_leader`(0/1); OFF ⇒ series absent/zero, no scrape error.
421. Configurable server-side log level + structured fields (`MCP_LOG_LEVEL`, default INFO) distinct from protocol `logging` — every line carries correlation_id, session_id, tool, group, token_id, leader, token scrubbed.
422. Define alerting thresholds — tool_error_rate > X%/N min; audit_queue_depth near cap; circuit-breaker open; auth-failure/brute-force spike; sweep stuck past wall-clock timeout; leader-lock lost. Each maps to an existing series.
423. OS-level resource budget — document FD/socket ulimit headroom for concurrent sessions + sweep DB connections; a container mem request/limit sized so a max sweep (+512 MB RSS) can't OOM-kill the shared trading process; MCP ceilings are additive to the trading loop's.
424. Bound the sweep CPU-offload pool separately from `_default_executor` — a dedicated bounded executor (`MCP_SWEEP_THREADS`, validated-int, small default) so sweeps degrade gracefully under contention instead of monopolizing the shared pool.
425. Disk-space budget & guard for audit + sweep tables — a monitored size threshold, enforced row/age cap with background prune, and fail-safe behavior (stop new sweeps, keep core trading writable) when the volume crosses a watermark.
426. Ops-reachable kill-switch without UI or DB write — `MCP_ENABLED=false` force-OFF overriding the DB toggle, taking effect on restart even if the DB is read-only/unreachable or the UI is down (the genuine break-glass); the in-UI kill-switch stays the fast in-session path.
427. Staged/dark rollout strategy — ship dark (code present + `enabled=false`, zero-overhead), enable per-environment dev→staging→single prod canary, validate via `/api/v1/mcp/health` + metrics; tie "single canary" to the multi-worker single-owner constraint.
428. Operator runbook artifact (checked-in `docs/`) — enable/disable (UI + env), connect a client (snippet + mcp-remote bridge), headless token rotate/revoke, read health/metrics, force-OFF break-glass, troubleshooting matrix (port-in-use, 401, feature-OFF 503, multi-worker misconfig, degraded-after-init, stuck sweep): symptom → check → fix.
429. Client setup & connectivity doc as a maintained artifact — prerequisites, transport URL shape for same-port vs proxy, exact `Authorization: Bearer` wiring per client, the stdio bridge for non-HTTP clients, a manual verify-connection walkthrough.

## Database / Schema / Migration / Integrity [SCHEMA/TYPES/FK/MIGRATION-SAFETY/SINGLETON/RETENTION/DB-CONCURRENCY/ENCRYPTION/JSONB/INDEX/BACKUP/TIMESTAMPS]

430. `mcp_audit_log` hash-chain columns — add `seq BIGINT NOT NULL`, `prev_hash TEXT`, `entry_hash TEXT NOT NULL`, `UNIQUE(seq)` (and/or `UNIQUE(entry_hash)`) so a forked append fails at the DB layer; plus `principal_token_id TEXT`, `correlation_id UUID`, `mutating BOOLEAN NOT NULL`, `safety_class TEXT`.
431. Reserved-word columns — rename `group` → `tool_group` and `rank` → `result_rank` (the migration runner splits on `;` and executes raw fragments; unquoted reserved words are a latent bug).
432. Fully-typed status columns — `mcp_sweep_jobs.status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','cancelled','failed','interrupted'))`; `mcp_audit_log.status TEXT NOT NULL CHECK(status IN ('ok','error','rejected','rate_limited','timeout'))`.
433. `config_hash CHAR(64) NOT NULL` (SHA-256 hex) on `mcp_sweep_results`, backing `UNIQUE(sweep_id, config_hash)`.
434. Money inside `metrics JSONB` loses Decimal exactness — money-valued metrics serialized as decimal STRINGS in the JSONB; promote the ranking objective to a typed `objective_value NUMERIC(20,8)` column so ranking/sort is exact and indexable.
435. NaN/Inf coercion at the DB boundary — Postgres NUMERIC rejects Infinity; quarantine maps NaN/Inf → NULL before writing `objective_value`; ranking query sorts `ORDER BY objective_value DESC NULLS LAST`.
436. Sweep-job counter constraints — `total_combos INT NOT NULL CHECK(total_combos > 0)`, `completed_combos INT NOT NULL DEFAULT 0 CHECK(completed_combos <= total_combos)`.
437. `mcp_sweep_results.sweep_id UUID NOT NULL REFERENCES mcp_sweep_jobs(id) ON DELETE CASCADE` (matching backtest_results→backtest_runs CASCADE).
438. Circular `best_result_id` — `nullable, REFERENCES mcp_sweep_results(id) ON DELETE SET NULL, DEFERRABLE INITIALLY DEFERRED` (set after results inserted; deferrable so dump/restore of the cycle doesn't deadlock).
439. `mcp_sweep_results.backtest_id UUID REFERENCES backtest_runs(id) ON DELETE SET NULL` — the existing DELETE /backtest must not orphan/error a sweep result; the metric snapshot survives in `metrics` JSONB (provenance).
440. Pin the migration version — append MCP DDL as the next sequential integer after the current max (43 confirmed via async_persistence.py), one transaction per version; never renumber existing tuples.
441. Constrain V43 to plain `;`-free statements OR supply it as a `callable(conn)` migration (the runner supports callables) — any trigger/DO block/function body with `;` shatters under the naïve `split(";")`.
442. Additive-only, `IF NOT EXISTS` on every CREATE — all-new tables ⇒ zero-downtime, safe on a live DB; UUID-default tables require `gen_random_uuid()` (assert availability, same dependency backtest_runs uses).
443. Forward-only migration implications documented — rolling the app back past V43 needs a manual runbook (drop MCP tables + decrement schema_version); deploying an older binary against a V43 DB refuses to start.
444. Singleton exact seed/defaults — `enabled BOOLEAN NOT NULL DEFAULT false`, `bind_host TEXT NOT NULL DEFAULT '127.0.0.1'`, seeded `INSERT INTO mcp_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING`.
445. Seeded JSONB defaults proven fail-safe — `safe_mode_flags JSONB NOT NULL DEFAULT '{"read_only":true,"allow_real_trades":false,"allow_debug":false}'`, `enabled_groups JSONB NOT NULL DEFAULT '[]'`, `enabled_tools JSONB NOT NULL DEFAULT '{}'` (zero tools on a fresh DB).
446. Rename `mcp_config.schema_version` → `config_schema_version INT NOT NULL DEFAULT 1` (avoid collision with the global migration `schema_version` table; it versions the JSONB shape).
447. Optimistic-concurrency precondition column — add `row_version BIGINT NOT NULL DEFAULT 0` to `mcp_config`, bumped on every write; UPSERT `… SET …, row_version=row_version+1 WHERE id=1 AND row_version=$expected RETURNING …`.
448. Idempotency-key home — add `idempotency_key TEXT` to `mcp_sweep_jobs` (and mutating-action tables) with partial unique `UNIQUE(principal_token_id, session_id, idempotency_key) WHERE idempotency_key IS NOT NULL`.
449. Retention config + mechanism — add `audit_retention_days INT NOT NULL DEFAULT 365 CHECK(BETWEEN 1 AND 3650)`, `sweep_retention_days INT NOT NULL DEFAULT 90` to `mcp_config`, plus a scheduled purge task reusing the debug-trace purge pattern.
450. `mcp_sweep_results.created_at TIMESTAMPTZ NOT NULL DEFAULT now()` for age-based purge (purge whole jobs by age, CASCADE removes results); `idx_mcp_sweep_jobs_created`.
451. Chain-aware audit purge — on purge persist the last-surviving `entry_hash` as a new chain anchor/genesis so the remaining chain stays verifiable; reconcile with GDPR tombstoning.
452. Indexes for listed query patterns — `mcp_audit_log(session_id, started_at DESC)` (activity feed); partial `mcp_sweep_jobs(status) WHERE status IN ('queued','running')` (boot recovery); the idempotency partial-unique; retention-scan index; consider BRIN on `mcp_audit_log(started_at)`.
453. App-level encryption reusing `ACCOUNTS_ENCRYPTION_KEY` (Fernet, not pgcrypto) — store sensitive args (account ids/amounts) in encrypted `sensitive_payload BYTEA`; keep only redacted non-sensitive fields in `args_redacted JSONB`.
454. Hash over canonical PLAINTEXT (pre-encryption) — so GDPR erasure can null `sensitive_payload` while `entry_hash` keeps the chain verifiable; key rotation re-encrypts without re-hashing.
455. Versioned Pydantic v2 model per JSONB column (`param_space`, `config`, `metrics`, `safe_mode_flags`, `enabled_groups`, `enabled_tools`) validated on write+read, plus cheap DB guards `CHECK(jsonb_typeof(enabled_groups)='array')`, `CHECK(jsonb_typeof(safe_mode_flags)='object')`; stamp each blob with its shape version.
456. Restore-safety — stamp an `installation_id UUID` (or validate against bind-host/env); refuse to honor `enabled=true` when the running env's id ≠ the stored one; fail closed to OFF and force token rotation on a detected restore (prevents a prod dump auto-starting MCP in staging).
457. Explicit TIMESTAMPTZ (UTC) everywhere — `created_at … DEFAULT now()` on every table; `started_at`/`completed_at` nullable with `CHECK(completed_at IS NULL OR completed_at >= started_at)`; `mcp_audit_log.started_at … DEFAULT now()` + `duration_ms INT CHECK(duration_ms >= 0)`.

## Performance & Context-Budget Economics [CONTEXT-BUDGET/OUTPUT-COST/SWEEP-PERF/CONCURRENCY/MEMORY/LATENCY/CACHE/SCALE-LIMIT/COLDSTART]

458. Per-tool schema minimization — terse one-line descriptions, compact JSON Schema, avoid huge inline enums (reference a small enum or resource); each tool's serialized schema has a soft cap (~300-500 tokens) asserted in tests so the Full preset stays within R-358's 20k budget.
459. Two-level / lazy tool disclosure option — support a "compact" advertisement mode where a small set of meta/dispatcher tools expand capabilities on demand, vs all tools upfront; documented as the mitigation when even Minimal is too large for a given client.
460. Resource-vs-tool tradeoff guidance — static reads (latest scan, current config, portfolio snapshot) exposed as MCP resources (don't bloat the tool list) rather than tools; the tool-budget meter counts tools, and the UI notes resources are "free" of the tool-list budget.
461. Default-compact tool outputs — every read/result tool defaults to a `summary` projection with a documented "typical response ≈ N tokens" budget; `detail` is opt-in per call; large arrays paginated by default.
462. Sweep metric memoization & no re-parse — the shared kline snapshot and parsed scan data are loaded once and reused across all combos; metric computation reuses the existing backtest metrics module without re-parsing per combo.
463. Event-loop responsiveness budget — quantify max acceptable event-loop block time from MCP work (e.g. no single MCP task blocks the loop >50 ms); CPU-bound sweep/backtest work runs in the dedicated bounded executor (R-424), keeping the live-trading loop responsive.
464. Cacheable read tools with TTLs — symbols/sectors/current-config reads cached with short TTLs; cache invalidated on config change; financial/position data never served stale beyond a tight bound (or not cached).
465. Documented scale limits — max tools, max concurrent sessions (default e.g. 8), max concurrent sweeps (default e.g. 2), max combos/sweep (5000), max audit rows before retention; document what degrades first and the back-pressure behavior at each limit.
466. Cold-start / warm-up — the first sweep pays the kline-fetch cost; the pre-warm phase (R-256) + existing cache-warmup endpoints prime the cache; the UI surfaces "warming cache" so the first sweep's longer ETA is expected.
467. Estimated-context-cost meter is cheap & accurate — computed from the registry's per-tool serialized-schema token counts (precomputed at registration), summed client-side as toggles change, within ±10% of actual (ties R-56/R-358); no server round-trip per checkbox.

## Maintainability / Docs / Naming / Code-Health [DOC/ADR/NAMING/CODE-HEALTH/TYPING/TEST-ORG/ERROR-CATALOG/REMOVABILITY/TOOL-DESC/PRESET-SYNC/CHANGELOG]

468. "How to add a new MCP tool" developer guide — registry pattern, thin handler adapter, group/preset/safety_class/mutating assignment, error-map entry, audit emission, the completeness + schema-equivalence tests, with one fully worked end-to-end example tool.
469. User connect-a-client guide (authored deliverable) — Claude Desktop (mcp-remote bridge), Claude Code (`--header`), generic client; what the agent can/cannot do; default-safe posture; troubleshooting (401, port-in-use, token rotation).
470. Inline docstring standard — new MCP modules/classes/public functions carry docstrings matching the codebase's rich module-docstring style; enforced by ruff/pydocstyle (D rules).
471. Feature changelog entry — project changelog/feature-log entry covering the new `/mcp` route, nav entry, migrations, default-OFF posture.
472. Tool-contract changelog — a maintained doc enumerating every tool-contract change (tool added/deprecated/output field added/enum appended) stamped with schema_version + deprecation window.
473. Authored error catalog + exhaustive code list — every server-defined JSON-RPC error code (the `-32000…` range), its domain-exception source, retryable flag, message template, remediation; CI test asserts catalog ≡ code.
474. Documented structured-log field schema + maintainer runbook — exact log fields (correlation_id, tool_name, group, session_id, token_id, duration_ms, outcome, error_code) and stable event names for grepability.
475. No god-file for tools — handlers one module per group; registry/manifest separate; soft per-file line cap (~400-500) enforced by lint.
476. Lint + typecheck CI gates — backend MCP passes ruff + mypy (strict); frontend `/mcp` passes `tsc --noEmit` (strict) + eslint; build fails on any violation.
477. Python typing discipline — `from __future__ import annotations`, fully type-hinted public signatures, no bare `Any` in tool input/output models; mypy --strict clean.
478. Frontend type/validation discipline — `/mcp` API responses validated with zod v4 schemas mirroring backend Pydantic; no `any`; types shared/derived so contract drift surfaces at typecheck.
479. Test location & taxonomy — MCP tests under `tests/backend/mcp/` mirroring service layout; shared fixtures in `tests/backend/mcp/conftest.py`; pytest markers (unit/integration/slow) so the fakes-only unit suite is fast and separable.
480. Fast-suite time budget — the MCP unit suite (fakes only, no socket/DB) completes under a stated CI wall-clock budget; socket/DB/e2e tests carry `slow` and are excluded from the fast gate.
481. Registry membership test (group + preset) — a parametrized test fails if any tool is not assigned to exactly one group, is absent from every preset, or lacks a safety_class.
482. Preset-integrity test — every preset references only existing tools; `Minimal ⊆ Standard ⊆ Full` containment holds; per-preset token-budget recomputed and asserted whenever the tool set changes.
483. Documented full-removal / uninstall path — checklist + down-migration to drop all `mcp_*` tables, remove the mount/nav/`app.state` keys, delete the `backend/mcp/` + frontend `/mcp` packages; a test asserts the app builds and boots with the MCP package physically absent.
484. Code-isolation import rule — all MCP code in dedicated packages with no inbound imports from core trading into MCP (and MCP additive-only into shared code); enforced by an import-linter/ruff boundary rule.
485. Tool-description style guide + lint — every tool/resource/prompt description follows a fixed template and voice (one-line imperative present-tense; declares side-effects, safety_class, pagination/verbosity, output units); a test asserts each is non-empty, within length bounds, contains required clauses.
486. Agent-facing copy consistency review — tool descriptions, `initialize.instructions`, and prompt texts reviewed as a set for one vocabulary (always "sweep" not "optimization"; "config" not "parameters").
487. Canonical naming spec + glossary — one convention for tool names (`group_action`), group ids, config/column/enum/env-var names, plus a glossary; rename inconsistent primitives before publishing; names immutable thereafter.
488. Single-source enums — objective-metric, sweep-status, safety_class, and group-id sets each defined once in a single module and reused by backend, frontend, and docs.
489. Env-var posture statement — document that MCP config is DB-backed with no new REQUIRED env vars; optional overrides use the `TRADINGAGENTS_MCP_` prefix with documented defaults.
490. Data-model doc incl. missing tables (ERD + column comments) — add the `mcp_tokens` table (multi-token + TTL) and a config-apply/approval-history table (diff/approver/source-sweep); reconcile with the single `access_token_hash`; persist `bind_port`.
491. Frontend `/mcp` decomposition — per-section components (Overview/Tools/Connection/Safety/Optimizer/Activity), shared `@/components/ui` primitives only, no duplicated inline styling.

---

## CONTRADICTIONS & AMBIGUITIES TO RESOLVE (carry into the Spec, Step 4)

These are real conflicts found in Round 3; the spec MUST resolve each (resolution noted):

- **C1 — OFF-state unmounted vs 503** (R-37 vs R-36/43/362): keep a tiny always-mounted gate route returning **503 "feature disabled"**, while the full JSON-RPC transport (sessions/handlers/dispatch) stays unmounted. Pin all refs to 503.
- **C2 — Bearer-only vs query-param fallback** (R-245 vs R-281/226): delete the query-param fallback from R-245; Bearer-only; fix the bad cross-ref (R-226→R-281). Note R-226 numbering collision (JSON-RPC codes vs client header).
- **C3 — primitive run_backtest vs backtest_create vs sweep** (R-29/222/247/10/20): canonical `backtest_run/get/list/compare` + `sweep_run/status/results/cancel`; primitives in an **Advanced group default-OFF**; sweep is the default path; instructions steer to sweep.
- **C4 — default read-only vs backtest-only** (R-1 vs R-47): **Minimal = read-only only (no sweep)**; "Backtest-only" is a separately selectable posture; reword R-1/R-47 to agree.
- **C5 — single token column vs multiple per-client tokens** (R-72/74 vs R-279/280): add an `mcp_tokens` table; deprecate `mcp_config.access_token_hash`. (MVP may ship single-token per R-395, but model the table now.)
- **C6 — hashed-only vs reveal toggle** (R-89/88/74 vs R-155): reveal works **only in the one-time post-generation window**; afterward masked placeholder + Regenerate only.
- **C7 — sweep resume mechanism** (R-86 vs R-276): R-276 supersedes (resume by set of completed config_hashes, not a count); update R-86.
- **C8 — sweep-status enum drift** (R-75 vs R-86/209): canonical enum includes `interrupted`; single-source it.
- **C9 — objective-metric list drift** (R-11/21/32/311): one canonical append-only objective-metric enum (superset), defined once.
- **C10 — overlapping capability taxonomies** (access mode vs tiers vs safe_mode_flags vs presets): the **capability tier is the single authoritative ceiling**; access-mode sets the tier; presets choose tools within the tier; rename presets to remove the Read-only/Full collision.
- **C11 — `/mcp` route collision** (frontend SPA R-134 vs backend transport R-58/61): mount the transport at a distinct prefix (e.g. `/mcp/rpc` or `/mcp-server`); keep the page at `/mcp`; scope CSRF exemption to the transport prefix only.
- **C12 — hot reload firm vs SDK-dependent** (R-44 vs R-69): adopt **atomic fresh-instance rebuild-and-swap** as the contract; demote the live-filter variant to an optional optimization.
- **C13 — kill-switch vs in-flight sweep** (R-39 vs R-182): master-OFF cancels in-flight tool calls and persists running sweeps to `interrupted` (resumable); the kill-switch hard-cancels everything including sweeps. Remove the "OR".
- **C14 — read tools raw money vs default redaction** (R-2/5 vs R-296): R-2/5 outputs subject to R-296 redaction by default; cross-reference both.
- **C15 — progress notifications optional vs required** (R-80 vs R-231): required **when the client supplies a progressToken**; reword R-80.
- **C16 — group taxonomy doesn't cover all tools** (R-45 vs CORE categories): define the authoritative group set covering every tool/resource/prompt; assign orphans (Scheduled-scans, Strategies/config, Symbols, Kline-cache); enforce with the membership test.
- **C17 — "Backtest-only" vs "Backtesting-only"** (R-1/163/217 vs R-47/146): pick "Backtest-only" everywhere.

---

## Round 3 Total: 120 new (R-372..R-491) + 17 contradictions — Cumulative: 491
## Rounds Completed: 3

---

# Round 4 — Gap-Finding (Agent-UX, Migration/Deploy Safety, Security Deep-Dive, QA Convergence)

## Agent-UX — How the AI agent actually drives this [DISCOVERY/SWEEP-DIALOG/HANDLES/ERROR-UX/OUTPUT-UX/APPLY-HANDOFF/SIM-SIGNAL/AGENT-ECONOMY/COMPOSITE/REPEATABILITY]

492. Agent get-started capability resource — a `get_started`/`capabilities` resource (or `initialize.instructions`) telling the agent the recommended workflow, the current config baseline summary, available scan-data date ranges, and cache coverage, so it doesn't discover by trial-and-error.
493. Sweep pre-validate/estimate tool — a `sweep_estimate(space)` tool returning combo count, ETA, cache gaps, and validity BEFORE running, so the agent iterates on the search space conversationally without launching work.
494. Fire-and-poll sweep handles with reconnect — `sweep_run` returns a durable `sweep_id`; the agent can disconnect and a later session reattaches by id (`sweep_status`/`sweep_results`), surviving agent timeouts/disconnects mid-sweep.
495. Stateful conversation handles — tools accept/return durable handles (`sweep_id`, `baseline_id`, `proposal_id`) so a multi-call agent carries context; live state exposed as re-readable resources.
496. Actionable error messages for self-correction — tool errors carry both a machine code AND an agent-readable remediation ("combo count 1.2M exceeds cap 5000 — reduce ranges or use random search"), so the agent self-corrects without a human.
497. LLM-shaped outputs — results are compact, labeled, unit-tagged, ranked, and include a short natural-language summary alongside structured data; comparisons return a digest the agent can relay verbatim.
498. Apply-handoff deep link — when the agent finds a winner it can only PROPOSE (per security) and receives a `proposal_id` + a deep link to the UI approval screen to tell the user exactly where to approve.
499. Simulation-vs-real signalling — every tool result and the capability doc clearly mark what is simulation/backtest vs would-be-real and what is gated, so the agent never promises the user an action it can't perform.
500. Top-N + drill-down, never bulk paging — result tools return top-N (default e.g. 20) with a drill-down handle; the agent never has to page through thousands of rows, protecting its context economy.
501. Composite one-shot optimizer tool — an `optimize_config(objective, constraints)` convenience tool that internally does baseline + sweep + rank + report and returns the best proposal, so the agent makes ONE call instead of orchestrating eight primitives (primitives remain available for advanced control).
502. Agent-side repeatability — re-asking the same question (same inputs) yields consistent answers (ties determinism R-34); cached/idempotent reads so repeated tool calls are cheap and stable.

## Migration / Deployment Safety [DEPLOY-RISK/PREFLIGHT/MIGRATION-TIMING/RESEED/COEXIST/DEPLOY-OBSERVABILITY/FEATURE-ROLLBACK/STAGING-SOAK/CONTRACT-EVOLUTION/SECRETS-DEPLOY/PLATFORM]

503. Live-trading-critical-files CI gate — a PR check fails if the MCP branch modifies an enumerated hot-path set (scanner_service, auto_trade_service, close_rule_evaluator, position_reconciler, accounts_service, lifespan/startup) outside a reviewed allowlist — mechanically proving the live path is additively untouched.
504. Post-deploy live-trading smoke with MCP OFF — before anyone can flip the toggle, an automated post-deploy check confirms a scheduled scan fires, a reconcile cycle completes, and the order path is healthy on the new build.
505. Three-tier rollback ladder, documented + tested with latencies — (a) UI/API kill-switch (instant, needs UI); (b) direct DB `UPDATE mcp_config SET enabled=false` polled by all workers within a bounded window (no restart, needs DB); (c) `MCP_ENABLED=false` env (needs restart, works if DB read-only/UI down). At least one tier MUST work when the event loop is saturated (the circuit-breaker must auto-fire then).
506. Programmatic enable-time preflight gate — OFF→ON is BLOCKED unless an aggregate self-check passes every invariant (token strong+set, bind loopback, read_only=true, zero mutating/live tools, migrations at expected version, single-worker-or-leader OK), returning a human-readable pass/fail; any failure keeps it OFF.
507. Enable-time "dry connect" runtime self-test — on enable, loop back an in-process MCP client, run initialize→tools/list→one read tool, assert auth enforced and only read-only tools advertised, THEN complete the transition; self-test failure auto-reverts to OFF.
508. Real-money-accounts-present acknowledgment at first enable — if live Bybit accounts exist when enabling, surface a context-aware extra confirmation naming the live-account count and asserting read-only/filtered exposure.
509. Atomic V43 — all four `mcp_*` tables + indexes + singleton seed land in ONE migration version/transaction; an injected mid-migration failure test asserts FULL rollback (zero `mcp_*` objects remain).
510. Startup-sequence ordering contract — V43 commits BEFORE MCP boot-recovery; MCP boot-recovery and mount run AFTER existing migrations, stale-backtest-recovery, and scanner-resume, so MCP never delays/interleaves with live-trading startup; asserted by a startup-order test.
511. Bounded migration-lock wait — a worker that can't acquire the migration advisory lock within a deadline fails its own boot cleanly (no hang); a waiting worker's live-trading startup isn't blocked by MCP DDL.
512. Migration-version-collision check at merge/deploy — CI asserts migration versions are contiguous/unique against merged main (the just-merged backtest/debug/caching features make 43 a real race), and that 43 is still the next free integer.
513. Boot-time singleton repair/normalization — detect a present-but-incomplete `mcp_config` row from a prior aborted attempt (NULL safe_mode_flags/missing defaults) and repair to fail-safe defaults; a detected-incomplete row is forced `enabled=false`.
514. Cross-service dependency manifest + per-method contract tests sited to fail the OWNER's CI — name every BacktestService/debug-repo/kline-cache/native-provider method MCP calls; locate each contract test so it breaks in the sibling feature's PR when they change the signature.
515. MCP-consumes-public-API-only boundary — an import-linter/AST rule forbidding MCP from calling siblings' private members or repositories directly, so backtest/debug/cache/native-provider can refactor internals freely.
516. Cache-coexistence quota — MCP read-tool caching and kline warmup are bounded/namespaced/priority-tiered so they cannot evict or pressure cache entries the live scanner/backtests depend on.
517. Native-provider/LLM rate-gate reuse — any MCP tool invoking the native-provider/LLM path acquires the SAME shared provider rate gate as live analysis, at lowest priority, never a parallel limiter.
518. Concrete "live-trading health" SLI + breaker trigger + attribution — define the signals the circuit-breaker watches (event-loop lag p95, scanner cycle time, reconciler/order latency, asyncpg pool-wait) with thresholds, the ops alert, and a metric that ATTRIBUTES degradation to MCP (correlate breaker-open with active sweeps).
519. Breaker recovery hysteresis + flap cap — resume only after N consecutive healthy windows/cooldown; after K flaps stay suspended and page ops; breaker transitions audited + alerted.
520. Enable-window heightened watch + auto-disable — for the first N minutes after a prod enable, compare live-trading SLIs to the just-before-enable baseline; auto-flip OFF and alert on regression beyond a documented threshold.
521. Orphan-tables-safe-forever guarantee + purge-hole fix — document/test that `mcp_*` tables left after code removal cause zero harm; CRITICAL: the retention-purge lives in MCP code, so removing the code stops the purge and tables grow unbounded — the removal runbook must run an external prune OR the purge must be independent of feature code.
522. Ordered, prod-safe decommission runbook with audit export — force-OFF → verify no sessions/sweeps → deploy code removal → export `mcp_audit_log` before any DROP → (separate later migration, only after backups confirm retention satisfied) drop tables.
523. Concurrent-coexistence soak on the prod OS — MCP enabled for hours WHILE scanner/reconciler/auto-trade run on a staging Linux box, asserting live-trading SLIs stay within baseline and no RSS/FD/pool creep.
524. Real external-client + restore drills on staging — paste the literal generated snippet into real Claude Desktop/Code (and the mcp-remote bridge) against staging; rehearse backup/restore of `mcp_*` and confirm hash-chain continuity + installation_id force-OFF fire.
525. Committed tool-contract golden snapshot + CI diff-gate — snapshot the published wire surface (tool names, schemas, enums, annotations); CI classifies any diff additive (allowed) vs breaking (blocked without a major bump + changelog + deprecation window).
526. Concrete deprecation mechanics + external compatibility policy — deprecated tools/fields keep working through the window, advertise `deprecated:true` + sunset date, emit a deprecation warning to agent/audit; publish a minimum N-version deprecation window an external integrator can rely on.
527. Deploy-layer secret hygiene for `MCP_TOKEN` — injected via the platform secret store; masked in CI/CD logs; absent from pipeline YAML/build-args/`ps`/`/proc/<pid>/environ`; the snippet's embedded token treated as a secret artifact.
528. Rotation-vs-env-bootstrap precedence — env `MCP_TOKEN` seeds the hash ONLY when none exists; a rotated DB hash is never overwritten by a stale env token on restart; document rotate → session-teardown → redistribute → reconnect + a compromise break-glass.
529. Prod-OS (Linux) CI gate — the MCP suite (e2e, coexistence soak, SIGTERM drain) runs on Linux in CI; a green Windows-dev run is not the sole gate.
530. Event-loop-policy + signal parity — verify the transport, CPU-offload executor, and graceful drain under uvloop and real SIGTERM/SIGKILL; confirm Postgres releases the leader advisory lock on ungraceful death so failover works.
531. Loopback/path portability — the Host/loopback allowlist includes IPv6 `::1` and verifies Linux dual-stack bind; no Windows-style hard-coded paths in any artifact; a Linux test catches filesystem case-sensitivity for module/asset/cache lookups.

## Security Deep-Dive — Round 4 [DEEP-INJECTION/APPROVAL-UI-GUARD/SERVER-SANITY-BOUNDS/OUTPUT-ENCODING/XSS-SINK/RESOURCE-INJECTION/SESSION-INVALIDATE/DENIAL-OF-WALLET/DATA-EGRESS-CONSENT/REDACTION-COMPLETENESS/SDK-SURFACE]

532. Untrusted-content fencing in tool outputs — every free-text field sourced from market data, scan `decision_summary`, symbol/sector names, exchange messages, or error strings is returned inside a clearly-delimited typed "untrusted data" envelope so the agent distinguishes app-trusted framing from attacker-influenceable content; the server never concatenates such text into instruction-position framing (tool descriptions, instructions, prompt bodies).
533. Prompt-injection neutralization on free-text egress — known injection patterns ("ignore previous instructions", fake system/tool markers, role lures, zero-width/base64 obfuscation) in untrusted fields are stripped/escaped/flagged and length-capped before reaching the agent or audit; the neutralizer is unit-tested against an injection corpus.
534. No untrusted-data-driven capability path + provenance — a decision to call a mutating/elevated tool or surface an apply-proposal MUST NOT be derivable solely from tool-result content; untrusted strings flowing into high-risk args stay subject to allow-list + sanity validation; a proposed config carries "influenced by untrusted source X" provenance.
535. Server-computed risk verdict, independent of the agent — the apply-config approval screen renders a risk assessment computed server-side from the diff alone, never from the agent's rationale; the agent's rationale appears only in a visually-segregated panel labeled "agent-generated, unverified" that can't be styled to resemble a system message.
536. Per-high-risk-field acknowledgment + anti-fatigue friction — applying a config that changes any high-risk field (leverage, position size, SL/TP, account binding, trade frequency) requires individual acknowledgment of each; typed-confirm gates any server-flagged "unusually risky" config; a cool-down rate-limits consecutive applies.
537. "Unusually risky" standout warning — when applied values breach server-side sane bands relative to the incumbent or absolute ceilings, the UI shows a prominent non-dismissible-by-default warning quantifying the delta ("leverage 5×→50×, SL 5%→0.5%") regardless of agent rationale.
538. Absolute non-overridable sanity ceiling at apply time — independent of the agent AND the user guardrail profile, the apply path enforces hard maxima/minima (max leverage, min stop distance, max position fraction, max concurrent positions, TP/SL ordering) and rejects out-of-band applies fail-closed at write time.
539. Apply path reuses existing config validators — the propose→approve→write pipeline runs the SAME validators as a normal live-config edit (liquidation, breakeven_timeout, close_on_profit, numeric bounds) at apply time; a config the normal UI would reject can never be written via the MCP-origin flow.
540. Canonical output encoding at the tool boundary — all string fields in tool/resource results are encoded for safe downstream consumption (no control chars, normalized Unicode, length-bounded, JSON-safe), applied once in core and tested.
541. Reflecting reads return inert escaped data — any tool/resource reflecting stored strings (audit args, error/trace text, prior results) returns them escaped and non-executable, re-neutralized on read, with attacker-influence provenance.
542. Activity-feed / audit-panel XSS hardening — the React `/mcp` activity feed, audit panel, error banners, and sweep/diff views render ALL agent-/market-/exchange-derived strings as inert text via framework escaping; no `dangerouslySetInnerHTML`; a test injects `<script>`/`onerror`/markup through a symbol and error path and asserts no execution.
543. Strict CSP on the `/mcp` operator route — no inline script, no unsafe-eval, aligned with the existing CSP middleware and regression-tested.
544. Resource-URI parameter validation parity — `resources/read` of parameterized URIs validates every template parameter with the SAME strict UUID/allow-list rules as tool args (reject `../`, scheme/path manipulation, wildcard/`latest` abuse outside whitelist, cross-scope ids); unknown/oversized URIs fail closed.
545. Shipped prompt/resource integrity + inert argument interpolation — bundled prompts and static resources are server-owned, read-only, integrity-checked, not agent/config-mutable; `prompts/get` arguments validated + escaped before interpolation.
546. Session lifecycle independent of token validity — sessions carry an absolute max lifetime AND idle timeout (configurable), invalidating and re-authenticating even while the bearer token is valid; `Mcp-Session-Id` values CSPRNG-generated, unguessable, bound to the issuing token+principal.
547. Token-compromise / panic response — one operator action (plus a headless command) revokes ALL tokens, drops ALL sessions across ALL workers, cancels in-flight sweeps/tool calls under any principal, flips master OFF, and writes an elevated audit marker; revoking a single token cancels that principal's background work.
548. Reserved live-trading quota floor on the shared Bybit gate — MCP/sweep exchange-facing calls (incl. kline pre-warm) acquire `bybit_rate_gate` in a strictly subordinate lane with a guaranteed reserved floor for the live loop; MCP can NEVER consume the share live trading needs.
549. Bybit 429/ban circuit-breaker protecting live API access — on Bybit rate-limit/ban signals a breaker immediately halts MCP/sweep kline fetching and exchange-facing tools (preserving live API budget), surfaces state, resumes only when healthy.
550. Bound NEW-data fetch volume per sweep — independent of the combo cap, a sweep enforces a hard ceiling on UNCACHED kline fetching (symbols × timeframes × range); over-ceiling sweeps rejected pre-flight with "warm cache first / narrow scope".
551. Third-party data-egress consent + standing notice — enabling MCP requires a one-time explicit consent acknowledging that tool results (strategy, config, positions, performance, account-derived data) are transmitted to whatever external MCP client/model provider the user connects (outside the app's trust boundary); the consent enumerates data classes, is audited, and a persistent `/mcp` notice reminds the user.
552. Egress-minimization defaults tied to consent tier — until the user opts into financial-detail and strategy-detail egress, config/strategy/performance reads return redacted/aggregated views; full-fidelity egress gated behind the consent.
553. Canonical secret inventory + positive leak test — a single deny-list (Bybit API key, Bybit API secret, ACCOUNTS_ENCRYPTION_KEY, every MCP bearer token, account passphrases/secrets, DB credentials, internal Bybit UIDs); a parametrized test fuzzes tool outputs, resource contents, error envelopes, logs, and audit rows for each pattern and FAILS the build on any appearance.
554. Redaction over results and errors, not just args — `mask_secrets`/credential-stripping runs over tool RESULTS, exception/error messages, and exchange-passthrough text, so a Bybit error/stack trace echoing a key or connection string is scrubbed before reaching agent/UI/logs/audit.
555. Enumerate + lock down SDK auto-registered routes — audit every route the MCP SDK (FastMCP) mounts (legacy `/sse`, message endpoint, inspector/debug/`.well-known`/discovery/health) and assert each is disabled or behind the same bearer auth + Host/Origin allowlist; a regression test enumerates the mounted sub-app's routes and fails on any unauthenticated/unexpected one.
556. SDK debug/verbose off + strong session-id entropy — disable any SDK request/response echo, verbose traceback, or inspector in production; pin SDK session-id generation to a CSPRNG and override if the default is weak.
557. "Test connection" SSRF guard — the backend "test connection" proxy targets ONLY the fixed loopback MCP endpoint and never an agent/user-supplied URL.
558. Per-principal authorization on read paths — sweep/result/idempotency reads are scoped per principal; a lower-trust (read-only) token cannot read a higher-trust principal's sweep results containing live-account-derived data.

## QA — Acceptance, E2E & Convergence [ACCEPTANCE/E2E/DOD/MANUAL-VERIFY/COVERAGE-GAP]

559. Headline-outcome acceptance test — on the golden fixture whose space contains a config that beats a known-suboptimal baseline, the optimizer top-1 MUST (a) equal the known winner, (b) report Δobjective vs baseline > 0, (c) carry non-empty rationale + robustness verdict + a provenance backtest_id on every metric, (d) emit a ready-to-apply proposal object. The single falsifiable success criterion for the headline use case.
560. Null-result honesty test — on a fixture where nothing beats baseline, the optimizer returns "keep current config" and crowns NO winner (MVP-critical anti-fabrication).
561. Whole-feature E2E scenario — enable+confirm → real streamable-HTTP client + bearer → tools/list → run sweep → poll completed → get best config → submit proposal → human approves via control-plane → diff persisted → revert.
562. Resource + prompt protocol E2E for the MVP surface — `resources/list` + static `resources/read` (`tradingagents://scan/latest`) and `prompts/list` + `prompts/get`.
563. Per-phase definition-of-done — every phase P0–P6 gets an explicit exit gate: named green suites, signed-off manual checks, docs updated, OFF-overhead regression passing, shippable-behind-OFF proven.
564. Real-client interop sign-off once per release — a human pastes the UI snippet into actual Claude Desktop (mcp-remote) and Claude Code and confirms connect/list/call/sweep.
565. Live-money opt-in walkthrough manual verify — a human confirms the typed-confirm "type ENABLE", red banners, and live-account hiding render correctly in a real browser in both themes.
566. DNS-rebinding test — forged `Host` and non-allowlisted browser `Origin` are rejected by the transport.
567. Registration deny-list test — build/startup FAILS if any deny-listed method (config writer, token lifecycle, master/kill-switch, audit mutation, debug_config write) is wrapped as a tool.
568. Apply-sanitization test — an approved proposal carrying allow_real_trades / live-account binding / auto-trade-on has those stripped or the apply rejected.
569. Multi-worker guard + cross-worker kill-switch test — with WEB_CONCURRENCY>1 + enabled, mount refuses or elects one leader; kill-switch/token-rotation reaches ALL workers in the bounded window.
570. TOCTOU epoch-fence test — a tier revoke / kill-switch / token rotation injected between dispatch and a side-effecting call aborts fail-closed.
571. Redaction-by-default test — default-mode read tools return ratios and redact raw balances/absolute P&L unless the financial-detail opt-in is on.
572. Restore-safety test — a DB cloned with enabled=true + foreign installation_id boots fail-closed to OFF and forces token rotation.
573. Stale-recommended-config apply test — a proposal computed under an older AutoTradeConfig schema is coerced/validated at apply time; a now-required-missing or now-removed field yields a clear error, never a silent write into live config.
574. Migration-runner safety test — V43 applies cleanly under the real `split(";")` runner; reserved-word columns (tool_group, result_rank) and any callable migration don't shatter; reapply is idempotent.

## Out-of-Scope (explicitly declared) & MVP-SDK Decision

575. MCP SDK selection pinned in the spec/ADR — choose the official `mcp` Python SDK's FastMCP, pin the version (e.g. ≥1.12), and the supported MCP protocol revision date(s); this is a load-bearing input, not left abstract.
576. Not-financial-advice / liability disclaimer surfaced in optimizer outputs and the `/mcp` page (the optimizer recommends configs that can move real money).
577. User LLM-token COST awareness — surface an estimate of the agent's own token spend for a sweep ("~N agent tokens / M polls") and guidance to minimize round-trips (await-vs-poll, completion push), framed as the user's monetary concern, not just context budget.
578. Accessibility verification — an axe/jsx-a11y/lighthouse a11y gate + a keyboard-nav test + contrast assertions for the `/mcp` page (beyond tsc/eslint).
579. i18n/localization explicitly OUT OF SCOPE (English-only); money/number/timezone formatting (R-249) is the only seam retained.
580. Agent reconnect-to-running-sweep across sessions — a NEW session reattaches to a prior in-flight sweep by id and resumes progress/polling; resumability behavior pinned (not left "to decide").
581. SBOM license-compatibility check (not just CVE) for bundling the MCP SDK.

---

## ADDITIONAL CONTRADICTIONS (Round 4) — resolve in the Spec

- **C18 — `bind_host` triple-bind:** R-72/93/444 make `bind_host` an authoritative NOT-NULL column, R-408 says it's a no-op under same-port mount, C11 mounts on the same app/port, R-490 implies a separate `bind_port` listener. **Resolution:** commit to **same-port mount** (C11) → `bind_host`/`bind_port` are NOT used for socket binding (loopback enforced by deploy `--host 127.0.0.1` + Host/Origin allowlist R-277/278); keep the column for display/validation only OR drop it. Reconcile R-444/490 accordingly.
- **C19 — token TTL in/out of MVP:** R-279 mandates configurable expiry; R-405 ships `MCP_TOKEN_TTL`; R-395 keeps a single bearer for MVP silent on TTL. **Resolution:** MVP ships a single bearer with **optional, default-disabled** TTL (no forced expiry that could lock out a UI-only user); `MCP_TOKEN_TTL` documented but defaulting to "no expiry"; multi-token + enforced TTL deferred.
- **C20 — OFF-state status code:** R-362 says "404/503"; C1 pins 503. **Resolution:** tighten R-362 to 503 only (the always-mounted gate route).

---

## Round 4 Total: 90 new (R-492..R-581) + 3 contradictions — Cumulative: 581
## Rounds Completed: 4
## CONVERGENCE: QA reviewer verdict — "Stop now; the set is over-complete." Brainstorm COMPLETE. Dominant remaining risk is SCOPE, not coverage. Proceed to Architecture (Step 3) then Spec (Step 4), resolving C1–C20 and applying the MVP phasing (R-393..399).

---

# Round 5 — Convergence Check (material/blocking gaps only)

3 of 5 reviewers (architecture, security, product) returned **NO MATERIAL GAPS — converged**. Backend/DB and frontend independently surfaced ONE coherent cluster: the **human-apply config-proposal loop** (the single place a swept config becomes live trading config) is under-specified. These 5 close it:

582. `mcp_proposals` table — the apply→live handoff needs a backing entity the append-only audit log can't hold: `id UUID PK, sweep_id UUID FK → mcp_sweep_jobs ON DELETE SET NULL, config JSONB, diff JSONB, status TEXT CHECK(status IN ('pending','approved','rejected','expired','applied','reverted')), approver TEXT, applied_config_version, created_at/expires_at TIMESTAMPTZ`. `proposal_id` (R-498) references this; the audit log records the approval EVENT, not the proposal state.
583. Apply-write owner defined — the control-plane approval action invokes the EXISTING scheduled-scanner config-write service (no MCP code inside `scanner_service`/`auto_trade_service`, satisfying the R-503 hot-path gate); sanitization (R-284) + the absolute sanity ceiling (R-538) + existing live-config validators (R-539) are applied AT that boundary.
584. Decimal discipline on money fields in `config`/`param_space` JSONB — extend R-434's decimal-string rule beyond `metrics` to money-valued fields (TP/SL/capital/position-size ranges + steps) in the swept `param_space` and the winning `config`, with canonical numeric normalization BEFORE config-hashing — so applied-config == backtested-config (reproducibility within the <1% bar) and combo hashes (R-433/255) stay deterministic.
585. Frontend Apply-Proposal review screen — a dedicated MCP approval screen (reached via the R-498 deep link + a pending-proposal nav badge/inbox so the deep link has a destination) rendering: the server-computed risk verdict (R-535), a visually-segregated "agent-generated, unverified" rationale panel, the field-level live→proposed diff with high-risk flags (R-326/537), per-high-risk-field acknowledgment + typed-confirm (R-536), and applied-config version history with one-click revert (R-329). This is MVP (R-394 keeps R-282/326/329/330), not deferred.
586. Proposal lifecycle + expiry — a pending proposal expires after a bounded TTL (stale baseline/market); expired proposals can't be applied; status transitions (pending→approved/rejected/expired/applied→reverted) are validated and audited; a proposal computed under an older AutoTradeConfig schema is coerced/validated at apply time (R-573) or rejected, never silently written.

## Round 5 Total: 5 new (R-582..R-586) — Cumulative: 586
## Rounds Completed: 5 — material cluster closed; architecture/security/product converged. One more convergence round to confirm 2 consecutive clean.

---

# Round 6 — Final Convergence (CLEAN)

All 3 reviewers (backend/DB, frontend, holistic QA) returned **CONVERGED — spec-ready**:
- Backend/DB: R-582..586 fully close the data-integrity / apply-owner / decimal-discipline gaps; nothing material survives.
- Frontend: R-585/586 fully close the apply-proposal review screen gap; no required user-facing flow lacks coverage.
- Holistic QA: 20/20 contradictions resolved; R-582..586 introduce no new contradiction; all 4 user asks map to requirements; the headline optimizer loop closes end-to-end with a falsifiable acceptance gate (R-559/560/561).

## FINAL: 586 requirements, 6 rounds, 20 contradictions resolved. 2 consecutive clean convergence rounds (R5 partial-converged + R6 fully clean). **BRAINSTORM COMPLETE — proceed to Step 3 (Architecture) / Step 4 (Spec).**

The spec author MUST: (1) resolve C1–C20 as pinned, (2) apply the MVP phasing R-393..399 (P0 skeleton → P6 hardening), (3) treat as MVP-critical-non-deferrable: default-OFF + zero-surface (R-35/37), zero mutating/live tools default (R-307), redaction-by-default (R-296), apply sanitization + sanity ceiling + human gate (R-284/538/539/282/585), multi-worker guard (R-401/404), live-trading resource priority (R-292/548), and the falsifiable headline acceptance test (R-559/560).

