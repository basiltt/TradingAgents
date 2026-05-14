# Traceability Matrix — Institutional Audit Fixes

## Finding → Implementation → Test Mapping

| Finding | Description | Files Changed | Tests | Status |
|---------|-------------|---------------|-------|--------|
| F1 | Data Leakage — Bull/Bear see confluence | `constants.py` (READABLE_KEYS), `state_filter.py`, `crypto_analysts.py` | `test_phase1_state_keys.py` | DONE |
| F2 | Information Barrier Violations | `constants.py`, `state_filter.py`, all agent modules | `test_phase1_state_keys.py`, `test_crypto_analysts.py` | DONE |
| F3 | Missing Risk Manager | `risk/risk_manager.py`, `schemas.py`, `setup.py`, `trading_graph.py` | `test_phase4_risk_manager.py` | DONE |
| F4 | Multi-Timeframe Analysis absent | `bybit_data.py` (multi_timeframe_analysis) | `test_phase3_data_sources.py` | DONE |
| F5 | Timeframe not passed to 3 analysts | `crypto_analysts.py`, `constants.py` | `test_crypto_analysts.py` | DONE |
| F6 | Naming confusion (derivatives_report) | `constants.py` (ReportKeys), `crypto_analysts.py`, `setup.py` | `test_phase1_state_keys.py` | DONE |
| F7 | Missing institutional layers | `bybit_data.py` (orderbook, volatility, liquidation, funding, regime) | `test_phase3_data_sources.py` | DONE |
| F8 | Prompt-level improvements | `trader.py` (two-pass), `prompt_guard.py`, `portfolio_manager.py` (structured), `compliance_officer.py`, `risk_manager.py` | `test_structured_agents.py`, `test_prompt_guard.py`, `test_phase4_risk_manager.py` | DONE |
| F9 | Scanner signal extraction fragile | `schemas.py` (PortfolioDecision), `portfolio_manager.py` (_PM_SIGNAL_DATA) | `test_structured_agents.py` | DONE |

## New Files Created (8)

| File | Purpose |
|------|---------|
| `tradingagents/agents/constants.py` | State key constants, per-role READABLE/WRITABLE_KEYS |
| `tradingagents/agents/utils/state_filter.py` | filter_state_for_read / validate_state_write |
| `tradingagents/agents/utils/prompt_guard.py` | wrap_external_data prompt injection protection |
| `tradingagents/agents/risk/__init__.py` | Risk package init |
| `tradingagents/agents/risk/risk_manager.py` | Independent Risk Manager agent with veto power |
| `tradingagents/dataflows/bybit_data.py` | Multi-TF analysis, orderbook, volatility, liquidation, funding, regime |
| `tradingagents/config/__init__.py` | Config package init |
| `tradingagents/config/feature_flags.py` | Feature flags for gradual rollout |

## New Test Files (4)

| File | Coverage |
|------|----------|
| `tests/test_phase1_state_keys.py` | State key rename, barrier allowlists, write validation |
| `tests/test_phase3_data_sources.py` | Multi-TF, orderbook, volatility, liquidation, funding, regime |
| `tests/test_phase4_risk_manager.py` | Risk Manager verdicts, fail-closed, leverage capping |
| `tests/test_prompt_guard.py` | Prompt injection wrapping, Unicode normalization |

## Modified Files (9)

| File | Changes |
|------|---------|
| `tradingagents/agents/crypto_analysts.py` | Info barriers, timeframe propagation, prompt guard wrapping |
| `tradingagents/agents/trader/trader.py` | Two-pass (direction → levels), structured output, prompt guard |
| `tradingagents/agents/managers/portfolio_manager.py` | Structured PortfolioDecision output, PM signal data |
| `tradingagents/agents/compliance/compliance_officer.py` | State filter, prompt guard, fail-closed defaults |
| `tradingagents/agents/schemas.py` | RiskAssessment, PortfolioDecision, ComplianceCheck schemas |
| `tradingagents/agents/utils/agent_states.py` | New state keys (microstructure, technical_levels, risk, compliance, execution) |
| `tradingagents/graph/setup.py` | Risk Manager + Execution Monitor wiring, compliance routing |
| `tradingagents/graph/trading_graph.py` | Feature flag integration |
| `backend/services/analysis_service.py` | Minor import fix |

## Validation Results

- **763 tests passed**, 0 failures in our code
- Pre-existing failures: 53 scanner/backend tests fail due to missing `asyncpg` dependency (unrelated)
- 59 collection errors from same `asyncpg` import chain (unrelated)
