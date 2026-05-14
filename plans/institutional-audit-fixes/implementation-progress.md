# Implementation Progress — Institutional Audit Fixes

## Phase 1: State Key Rename + Timeframe Propagation
| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| 1.1 | Create constants module | PENDING | |
| 1.2 | Rename fundamentals_report → derivatives_report | PENDING | |
| 1.3 | Pass crypto_interval to all analysts | PENDING | |
| 1.4 | Add timeframe-aware prompt instructions | PENDING | |

## Phase 2: Information Barriers + Data Leakage Fix
| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| 2.0 | Update AgentState TypedDict | PENDING | |
| 2.1 | Define per-role READABLE/WRITABLE_KEYS | PENDING | |
| 2.2 | Create state filtering utility | PENDING | |
| 2.3 | Apply read filters to Bull/Bear Researchers | PENDING | |
| 2.4 | Apply read filters to Risk Debaters | PENDING | |
| 2.5 | Apply read filters to Compliance Officer | PENDING | |
| 2.6 | Apply read filter to Trader + technical_levels_summary | PENDING | |
| 2.7 | Fix PM truncation | PENDING | |
| 2.8 | Apply write validation to all agent outputs | PENDING | |

## Phase 3: Multi-Timeframe Analysis + New Data Sources
| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| 3.1 | Add orderbook depth fetcher | PENDING | |
| 3.2 | Add volatility metrics | PENDING | |
| 3.3 | Add liquidation price calculator | PENDING | |
| 3.4 | Add funding rate cost projection | PENDING | |
| 3.5 | Create market regime classifier | PENDING | |
| 3.6 | Create multi-timeframe analysis module | PENDING | |
| 3.7 | Create market_microstructure aggregation | PENDING | |
| 3.8 | Integrate new data into instrument context | PENDING | |
| 3.9 | Wire multi-TF + microstructure into Technical Analyst | PENDING | |
| 3.10 | Wire orderbook + volatility into Derivatives Analyst | PENDING | |

## Phase 4: Risk Manager + Prompt Improvements + Scanner Fix
| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| 4.1 | Create Risk Manager schema | PENDING | |
| 4.2 | Create Risk Manager agent | PENDING | |
| 4.3 | Wire Risk Manager into graph | PENDING | |
| 4.4 | Update trading_graph.py for Risk Manager | PENDING | |
| 4.5 | Upgrade Crypto Trader to two-pass | PENDING | |
| 4.6 | Add debate truncation | PENDING | |
| 4.7 | Add Research Manager info preservation | PENDING | |
| 4.8 | Add prompt injection guards | PENDING | |
| 4.9 | Refactor PM to structured output | PENDING | |
| 4.10 | Fix scanner signal extraction | PENDING | |
| 4.11 | Confluence checker timeframe awareness | PENDING | |

## Phase 5: Cross-Cutting — Feature Flags, Observability, Testing
| Task | Description | Status | Tests |
|------|-------------|--------|-------|
| 5.1 | Add feature flags module | PENDING | |
| 5.2 | Add agent execution logging | PENDING | |
| 5.3 | Update stream_parser.py | PENDING | |
| 5.4 | Update scanner_service.py | PENDING | |
| 5.5 | Comprehensive integration tests | PENDING | |
