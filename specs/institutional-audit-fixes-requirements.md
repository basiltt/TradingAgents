# Institutional Audit Fixes — Requirements Document

**Feature**: Address all 9 findings from the institutional crypto analysis workflow audit
**Date**: 2026-05-14
**Status**: Draft — Brainstorm Round 1

## Table of Contents

1. [Finding 1: Data Leakage in Bull/Bear Researchers](#finding-1)
2. [Finding 2: Information Barrier Violations](#finding-2)
3. [Finding 3: Missing Risk Manager Role](#finding-3)
4. [Finding 4: Multi-Timeframe Analysis Absent](#finding-4)
5. [Finding 5: Timeframe Not Passed to All Analysts](#finding-5)
6. [Finding 6: Naming Confusion (derivatives_report)](#finding-6)
7. [Finding 7: Missing Institutional Layers](#finding-7)
8. [Finding 8: Prompt-Level Improvements](#finding-8)
9. [Finding 9: Scanner Signal Extraction Fragile](#finding-9)
10. [Cross-Cutting: Architecture](#cross-cutting-architecture)
11. [Cross-Cutting: Data Layer](#cross-cutting-data-layer)
12. [Cross-Cutting: Security](#cross-cutting-security)
13. [Cross-Cutting: Testing](#cross-cutting-testing)

---

## Workflow Modes to Respect

- **quick_trade**: Analysts → Confluence → Researchers → RM → Trader → END (no compliance/risk/PM). Used for rapid screening.
- **deep_analysis**: Full pipeline with Compliance, Risk Manager (new), Risk Debate, PM, Execution Monitor. Used for final trade decisions.

All changes must preserve both modes. New agents (Risk Manager) must be appropriately wired or skipped per mode.

---

<a id="finding-1"></a>
## Finding 1: Data Leakage in Bull/Bear Researchers

**Problem**: Bull/Bear Researchers see ALL 5 analyst reports + the confluence summary. Both debaters argue over the same pre-digested picture, reducing the debate's value as independent cross-validation.

**Institutional Standard**: Researchers should see raw analyst reports independently, NOT the pre-digested confluence. The confluence should inform the Research Manager, not the debaters.

### Requirements

**FR-101**: Remove `confluence_summary` from Bull/Bear Researcher input context. Researchers must receive only raw analyst reports and current price data.
- AC: Researcher prompts contain zero references to confluence output; state passed to researchers does not include `confluence_summary` key.
- Risk: High

**FR-102**: Bull and Bear Researchers receive identical, independent copies of the 5 analyst reports with no cross-contamination between their inputs.
- AC: Unit test confirms both nodes receive same raw reports; neither sees the other's prior output on first round.
- Risk: Medium

**FR-103**: Confluence summary is passed to the Research Manager alongside the debate history, serving as a safety net for data points the debaters may have missed.
- AC: Research Manager prompt includes `confluence_summary`; RM output references confluence data when it adds information not covered in debate.
- Risk: Medium

**FR-104**: In `quick_trade` mode, the confluence summary is still generated and passed to RM (the debate still happens, just without compliance/risk/PM layers).
- AC: Quick trade graph includes Confluence → Researchers → RM path with confluence passed to RM.
- Risk: Low

---

<a id="finding-2"></a>
## Finding 2: Information Barrier Violations

**Problem**: Multiple agents see data they shouldn't per institutional norms. This can introduce bias and violate role separation.

### Requirements

**FR-201**: Crypto Trader receives ONLY `investment_plan`, `current_price_context`, and `instrument_context`. Remove `confluence_summary` and `market_report` from Trader input.
- AC: Trader prompt template references only investment_plan and price data; grep confirms no confluence/market_report references in Trader function.
- Risk: High

**FR-202**: Compliance Officer receives ONLY `trader_investment_plan`, `current_price_context`, `instrument_context`, and `max_leverage` config. Remove `past_context` from Compliance input.
- AC: Compliance prompt template has no history/past_context variables; unit test confirms exclusion.
- Risk: High

**FR-203**: Risk Bull/Bear Debaters receive ONLY `trader_investment_plan`, `current_price_context`, and quantitative risk metrics (volatility regime, liquidation distance, funding cost). Remove all 5 raw analyst reports.
- AC: Risk debater prompts reference only trade proposal and risk metrics; no analyst report keys in their input.
- Risk: High

**FR-204**: Portfolio Manager receives the FULL `trader_investment_plan` (not just first line). Fix the `.split('\n')[0]` truncation.
- AC: PM input string length equals full trader output string length; regression test with multi-line JSON plan confirms no truncation.
- Risk: High

**FR-205**: Implement a `StateProjection` utility that each agent node uses to filter its input state to only its allowed keys, configured via a per-agent allowlist.
- AC: Allowlist defined as a constant per agent; any key not in allowlist is dropped before node execution; test confirms enforcement.
- Risk: Medium

**FR-206**: Add an integration test that traces every state key through the full graph and asserts no node receives a key outside its allowlist.
- AC: Test iterates all nodes, asserts `received_keys ⊆ allowed_keys` for each agent.
- Risk: Medium

---

<a id="finding-3"></a>
## Finding 3: Missing Risk Manager Role

**Problem**: No independent Risk Manager exists. Risk assessment is embedded in the bull/bear risk debate, judged by the PM — creating a conflict of interest where the PM is both decision-maker and risk judge.

**Institutional Standard**: Risk Manager is independent, has veto power, sits "above the Chinese wall," sees positions/exposure but NOT alpha-generating signals.

### Requirements

**FR-301**: Create a dedicated `RiskManager` agent in `tradingagents/agents/risk/risk_manager.py` with independent veto authority.
- AC: Module exists; agent has its own system prompt; outputs structured `RiskAssessment` schema.
- Risk: High

**FR-302**: Risk Manager is positioned in the graph AFTER Compliance Officer and BEFORE the Risk Bull/Bear Debate (in `deep_analysis` mode).
- AC: Graph edges show: Trader → Compliance → Risk Manager → (if veto: END, else: Risk Debate → PM).
- Risk: High

**FR-303**: Risk Manager receives ONLY: `trader_investment_plan`, `current_price_context`, `instrument_context`, `max_leverage`, and new quantitative risk metrics (volatility regime, liquidation distance, funding cost, order book liquidity).
- AC: Risk Manager prompt contains only these data points; no analyst reports, no debate history.
- Risk: High

**FR-304**: Risk Manager evaluates: (a) position size vs portfolio limits, (b) leverage vs volatility regime, (c) liquidation price proximity (reject if within 2x ATR of entry), (d) funding rate cost impact, (e) order book liquidity adequacy.
- AC: Each check is a separate finding in the structured output; unit tests cover boundary conditions for each.
- Risk: High

**FR-305**: Risk Manager output is a structured `RiskAssessment` Pydantic schema: `risk_score` (0-100), `verdict` (Approve/Modify/Reject), `findings` list, `adjusted_position_size` (optional), `adjusted_leverage` (optional).
- AC: Schema validates correctly; scanner_service can extract risk fields; render function produces markdown.
- Risk: Medium

**FR-306**: Risk Manager uses fail-closed logic (matching Compliance Officer pattern): if structured parsing fails, default to REJECT. If any individual finding is REJECT, force overall to REJECT programmatically.
- AC: Test with structured output failure defaults to REJECT; test with one REJECT finding forces overall REJECT regardless of LLM summary.
- Risk: High

**FR-307**: In `quick_trade` mode, Risk Manager is SKIPPED (same as Compliance and PM). The quick_trade path remains: Analysts → Confluence → Researchers → RM → Trader → END.
- AC: Quick trade graph has no Risk Manager node; graph compiles and runs without error.
- Risk: Low

**FR-308**: Risk Manager veto produces a terminal state with clear rejection reason, formatted consistently with the existing `_blocked_trade_node` pattern.
- AC: Vetoed trade output matches format: "## TRADE BLOCKED BY RISK MANAGER\n\n..." with findings.
- Risk: Low

---

<a id="finding-4"></a>
## Finding 4: Multi-Timeframe Analysis Absent

**Problem**: System only pulls klines for the single user-selected timeframe. No higher-TF trend confirmation. Trading a 15m signal against a daily downtrend is a known failure mode.

**Institutional Standard**: 3-tier model — Strategic (Weekly/Daily for trend), Tactical (Daily/4H for setups), Execution (4H/1H/15m for entry/exit).

### Requirements

**FR-401**: Define a timeframe hierarchy mapping that, given any user-selected interval, returns the appropriate higher timeframe(s) for trend confirmation.
- AC: Mapping covers all supported intervals: 1m→15m/1h, 5m→1h/4h, 15m→4h/1d, 1h→4h/1d, 4h→1d/1w, 1d→1w. Edge cases (1w has no higher) handled gracefully.
- Risk: Low

**FR-402**: Technical Analyst fetches klines for BOTH the user-selected timeframe AND the primary higher timeframe for trend confirmation.
- AC: Two kline fetches occur (verified by log or mock); Technical Analyst report includes a "Higher Timeframe Context" section stating trend direction.
- Risk: High

**FR-403**: Technical Analyst's report explicitly states whether the higher TF trend CONFIRMS or CONTRADICTS the setup on the user's timeframe.
- AC: Report contains a clear "HTF Alignment: Confirming/Contradicting" statement with supporting evidence.
- Risk: High

**FR-404**: Confluence Checker weights signals by timeframe — higher timeframe signals carry more weight for directional bias, lower timeframe signals carry more weight for entry timing.
- AC: Confluence prompt includes timeframe weighting instructions; a contradicting HTF reduces consensus confidence by at least 2 points.
- Risk: Medium

**FR-405**: When higher TF strongly contradicts the lower TF signal (e.g., daily downtrend vs 15m buy), the Trader reduces position size or outputs "No Trade" based on the degree of contradiction.
- AC: Trader prompt includes HTF alignment instructions; test with strong HTF contradiction produces reduced confidence or No Trade.
- Risk: High

**FR-406**: Rate limiter budget accounts for the additional higher-TF kline fetches without starving other data calls.
- AC: Multi-TF fetches respect rate limiter; no TimeoutError from rate limiter under normal operation.
- Risk: Medium

**FR-407**: Higher-TF data is cached with a longer TTL proportional to interval (daily klines: 3600s, weekly: 7200s) to minimize redundant API calls during scanner batch runs.
- AC: Second request within TTL returns cached data; cache key includes interval.
- Risk: Low

---

<a id="finding-5"></a>
## Finding 5: Timeframe Not Passed to All Analysts

**Problem**: News, Fundamentals, and Social analysts call `build_instrument_context(symbol)` without `crypto_interval`. They don't know if the user is looking at a 15m scalp or a weekly swing trade.

### Requirements

**FR-501**: Pass `crypto_interval` to ALL analyst functions via `build_instrument_context(symbol, crypto_interval)`.
- AC: All 5 analyst functions call `build_instrument_context` with both arguments; grep confirms no single-arg calls in crypto analyst code.
- Risk: Medium

**FR-502**: News Analyst prompt includes timeframe-aware filtering instructions (e.g., 1h timeframe → focus on last 24h news; 1d → focus on last week).
- AC: News Analyst prompt contains `{timeframe}` variable with guidance on news relevance window.
- Risk: Medium

**FR-503**: Fundamentals Analyst prompt includes timeframe relevance weighting (fundamentals matter less for short-term scalps, more for swing/position trades).
- AC: Fundamentals report on 5m/15m timeframe includes a note about reduced fundamental relevance; 1d/1w gives full weight.
- Risk: Medium

**FR-504**: Social Analyst prompt adjusts the sentiment analysis window to match the timeframe horizon.
- AC: Social sentiment window scales with timeframe (short TF → recent social buzz, long TF → sustained trend).
- Risk: Medium

**FR-505**: Confluence Checker receives `crypto_interval` and uses it to weight signal relevance (sentiment matters more for short-term, fundamentals more for long-term).
- AC: Confluence prompt includes timeframe and weighting guidance.
- Risk: Medium

**FR-506**: Risk Bull/Bear Debaters receive `crypto_interval` so they can frame risk assessments appropriately (holding period affects funding costs, volatility exposure).
- AC: Risk debater prompts include timeframe context.
- Risk: Low

---

<a id="finding-6"></a>
## Finding 6: Naming Confusion (derivatives_report)

**Problem**: Derivatives Analyst output is stored as `fundamentals_report` while the actual Fundamentals Analyst writes to `crypto_fundamentals_report`. Confusing and error-prone.

### Requirements

**FR-601**: Rename the Derivatives Analyst output state key from `fundamentals_report` to `derivatives_report` everywhere.
- AC: `grep -r "fundamentals_report"` across `tradingagents/` and `backend/` returns zero hits (excluding migration shim and comments).
- Risk: High

**FR-602**: Update all downstream consumers to read `derivatives_report` instead of `fundamentals_report`.
- AC: Full pipeline runs without KeyError; all agents reference correct key.
- Risk: High

**FR-603**: Define a `ReportKeys` constants class/enum for all report key names to prevent future typos.
- AC: All agent functions import report key names from `ReportKeys`; no hardcoded string literals for report keys.
- Risk: Low

**FR-604**: Add a state migration shim: if `fundamentals_report` exists in persisted state (from in-progress scans), copy to `derivatives_report` with deprecation warning. Remove after one release.
- AC: Loading old state still works; warning logged; new scans use only `derivatives_report`.
- Risk: Medium

---

<a id="finding-7"></a>
## Finding 7: Missing Institutional Layers

**Problem**: No order book/liquidity analysis, volatility regime detection, market regime classification, liquidation price calculation, or funding rate cost projection.

### Requirements

**FR-701**: Add `get_bybit_orderbook(symbol, depth=25)` to `bybit_data.py` using `/v5/market/orderbook`. Return bid/ask arrays, spread (bps), and bid/ask imbalance ratio.
- AC: Function returns structured dict; respects rate limiter; circuit breaker integrated; cached with 5s TTL.
- Risk: Medium

**FR-702**: Add volatility metrics: ATR (14-period), realized volatility (24h, 7d), Bollinger bandwidth. Derived from existing kline data (no extra API call).
- AC: Returns dict with `atr_14`, `rv_24h`, `rv_7d`, `bb_width`; unit tested against known values.
- Risk: Low

**FR-703**: Add volatility regime classifier: Low/Normal/High based on trailing 90-day ATR percentile.
- AC: Returns regime label + percentile; test with known ATR series matches expected classification.
- Risk: Medium

**FR-704**: Add market regime detector using ADX + EMA alignment. Output: trending/ranging + direction + strength.
- AC: ADX > 25 = trending, < 20 = ranging; EMA alignment determines direction; test coverage.
- Risk: Medium

**FR-705**: Calculate estimated liquidation price given entry, leverage, side, maintenance margin rate.
- AC: Matches Bybit formula; unit tests for long and short at various leverage levels.
- Risk: Medium

**FR-706**: Calculate projected funding rate cost over hold period using weighted average of last 7 days.
- AC: Returns total cost %, annualized %, and break-even price move needed.
- Risk: Low

**FR-707**: Feed all new metrics into Risk Manager as structured `market_microstructure` data.
- AC: Risk Manager prompt includes liquidity, volatility regime, liquidation distance, funding cost.
- Risk: Medium

**FR-708**: In extreme volatility regime, Risk Manager auto-reduces max position size by 50%.
- AC: Test with `regime=high` confirms reduced sizing.
- Risk: High

---

<a id="finding-8"></a>
## Finding 8: Prompt-Level Improvements

**Problem**: RM information loss (only sees debate, not reports), unbounded debate token growth, single-pass crypto trader, no prompt injection protection, confluence checker lacks timeframe awareness.

### Requirements

**FR-801**: Pass `confluence_summary` to Research Manager alongside debate history as a data safety net.
- AC: RM prompt includes confluence summary; RM output can reference data not covered in debate.
- Risk: Medium

**FR-802**: Implement debate history truncation: after N rounds, summarize earlier rounds preserving key arguments, price targets, and dissenting opinions. Keep latest 2 rounds verbatim.
- AC: With max_debate_rounds=4, rounds 1-2 are summarized into a paragraph; rounds 3-4 are verbatim. Total token count reduced vs. unbounded.
- Risk: Medium

**FR-803**: Upgrade Crypto Trader to two-pass architecture matching stock Trader: Pass 1 = directional decision using structured `TraderDirection` schema, Pass 2 = level calculation using `TraderProposal` schema with direction locked from Pass 1.
- AC: Crypto Trader makes exactly 2 LLM calls; Pass 2 action matches Pass 1; override safeguard logs warning if Pass 2 tries to change direction.
- Risk: High

**FR-804**: Wrap all external data (news, social, market data) in XML-delimited boundaries before prompt interpolation, with system prompt instruction to treat content inside tags as untrusted data.
- AC: Every prompt template uses `<external_data source="...">` tags; no raw f-string interpolation of external data.
- Risk: High

**FR-805**: Add `max_tokens` caps per agent to prevent runaway token consumption.
- AC: Config specifies per-node token limits; LLM calls include max_tokens parameter.
- Risk: Low

**FR-806**: Add token-count guard before each LLM call. If assembled prompt exceeds 90% of context window, apply truncation with priority order: system prompt > compliance data > latest round > older rounds.
- AC: Test constructs oversized prompt; confirms truncation preserves system prompt and compliance data.
- Risk: Medium

---

<a id="finding-9"></a>
## Finding 9: Scanner Signal Extraction Fragile

**Problem**: `scanner_service.py` uses regex to parse PM decisions from free-text LLM output. Breaks if prompt formatting changes.

### Requirements

**FR-901**: Replace regex-based PM signal extraction with structured output parsing using `PortfolioDecision` Pydantic schema.
- AC: No regex in `_extract_pm_signal`; scanner reads `_pm_signal_data` structured object.
- Risk: High

**FR-902**: Crypto PM must use structured output via `invoke_structured_or_freetext` matching stock PM pattern.
- AC: Crypto PM outputs `PortfolioDecision` object; `_pm_signal_data` populated in state.
- Risk: High

**FR-903**: Scanner `_extract_signal_from_structured` becomes the only signal extraction path.
- AC: All extraction goes through structured path; no regex fallback.
- Risk: Medium

**FR-904**: Structured output failure fallback: retry once, then return `PARSE_ERROR` (not a guessed signal).
- AC: Test with malformed output triggers retry; second failure returns `PARSE_ERROR`.
- Risk: Medium

---

## Cross-Cutting: Architecture

**FR-A01**: New agents follow factory function pattern: `create_risk_manager(llm)` returns callable `node(state) -> dict`.
- AC: Pattern matches existing agents. Risk: Low

**FR-A02**: Graph topology changes preserve backward compatibility with frontend/backend.
- AC: Scanner extracts signals from both old and new graph outputs. Risk: Medium

---

## Cross-Cutting: Data Layer

**FR-D01**: New data functions follow existing patterns: rate limiter, circuit breaker, cache.
- AC: Each function uses `_bybit_request` or equivalent. Risk: Low

**FR-D02**: Multi-TF fetches account for additional rate limit token consumption.
- AC: 2 timeframes = 2 tokens; no starvation. Risk: Medium

---

## Cross-Cutting: Security

**FR-S01**: External data wrapped in XML boundary tags before prompt interpolation.
- AC: System prompt treats tagged content as untrusted. Risk: High

**FR-S02**: Risk Manager uses fail-closed logic matching Compliance Officer.
- AC: Parsing failure → REJECT; any REJECT finding → overall REJECT. Risk: High

---

## Cross-Cutting: Testing

**FR-T01**: Unit tests verify information barriers per agent.
- AC: Extra injected keys absent from agent's filtered view. Risk: High

**FR-T02**: Integration test with mocked LLMs for BTC, ETH, low-cap token.
- AC: All 3 complete; valid portfolio decision in final state. Risk: High

**FR-T03**: Risk Manager veto test confirms PM not invoked on REJECT.
- AC: State after veto has rejection but no PM output. Risk: High

---

## Summary

**Total Requirements**: 62 | **High Risk**: 22 | **Medium**: 30 | **Low**: 10

| Priority | Findings | Rationale |
|----------|----------|-----------|
| P0 | F6 (rename), F5 (timeframe pass) | Quick fixes, high data correctness impact |
| P1 | F4 (multi-TF), F2 (barriers), F3 (Risk Manager) | Core institutional compliance |
| P2 | F1 (data leakage), F7 (institutional layers), F8 (prompts) | Analysis quality |
| P3 | F9 (scanner parsing) | Robustness |

---

## Addendum: Round 2 Review Findings

**FR-NFR-01**: Maximum end-to-end pipeline latency: `quick_trade` < 45s, `deep_analysis` < 120s (with mocked LLMs excluded from timing).
- AC: Integration test measures wall-clock time for data fetching + graph execution. Risk: Medium

**FR-NFR-02**: Feature flags per finding group (e.g., `USE_INFORMATION_BARRIERS`, `USE_RISK_MANAGER`, `USE_MULTI_TF`) for incremental rollout.
- AC: Each flag defaults to `true`; setting to `false` reverts to pre-change behavior. Risk: Medium

**FR-NFR-03**: Structured event logging for barrier enforcement, Risk Manager vetoes, HTF contradictions, and debate truncation events.
- AC: Each event logged with structured fields (agent, action, reason, timestamp). Risk: Low

**FR-NFR-04**: All new data functions return a "data unavailable" sentinel on failure; downstream agents handle gracefully without crashing.
- AC: Pipeline completes even if orderbook/volatility/liquidation endpoints are down. Risk: Medium

**FR-CLARIFY-01**: FR-405 threshold — HTF contradiction + confidence delta > 3 = No Trade; delta 1-3 = 50% size reduction; delta < 1 = proceed normally.
- AC: Unit tests cover all 3 threshold bands.

**FR-CLARIFY-02**: FR-708 — "50% of the configured `max_position_size` for that instrument" (not 50% of Risk Manager's adjusted size).

**FR-CLARIFY-03**: FR-307/FR-301 — Use unambiguous names throughout: "Research Manager" (investment debate judge) vs "Risk Manager" (pre-trade risk gate). Never abbreviate to "RM."

**FR-CLARIFY-04**: FR-703 — Volatility regime lookback is configurable (default 90 days, minimum 14 days). If insufficient data, default to "Normal" regime.

**FR-CLARIFY-05**: FR-903 — Keep a validated regex as a second-tier fallback before returning PARSE_ERROR. Order: structured output → retry with formatting hint → validated regex → PARSE_ERROR.

**FR-CLARIFY-06**: State key renames require changelog entry and frontend/backend contract notification.

