# Codebase Discovery Summary — AI Manager Dashboard Enhancement

## Repository Overview
- **Stack**: FastAPI backend + React/Redux frontend with Neumorphism design system
- **AI Manager**: Per-account FSM engine with 8-node LangGraph decision graph using Claude AI
- **Real-time**: WebSocket for state_change and execution events, 30s polling fallback

## Relevant Backend Files

| File | Purpose |
|------|---------|
| `backend/routers/ai_manager.py` | REST API (enable/disable/status/config/decisions/logs/performance/kill) |
| `backend/services/ai_manager_task.py` | Per-account FSM engine (2100+ lines) |
| `backend/services/ai_manager_graph.py` | 8-node LangGraph decision graph |
| `backend/services/ai_manager_llm_provider.py` | Claude/OpenAI API integration |
| `backend/services/ai_manager_llm_scheduler.py` | LLM call rate limiting |
| `backend/services/ai_manager_evaluator.py` | Urgency classification (EMERGENCY/FAST/STANDARD/DEEP) |
| `backend/services/ai_manager_repository.py` | PostgreSQL persistence + decision chain |
| `backend/services/ai_manager_market_data.py` | Real-time Bybit ticker/kline feeds |
| `backend/services/ai_manager_mtf.py` | Multi-timeframe analysis |
| `backend/services/ai_manager_correlation.py` | Correlation analysis and clustering |
| `backend/services/ai_manager_orderbook.py` | Order book monitoring and sweep detection |
| `backend/services/ai_manager_regime.py` | Market regime classification |
| `backend/services/ai_manager_memory.py` | Episodic memory and pattern learning |
| `backend/services/ai_manager_prompts.py` | System and context prompts |
| `backend/services/ai_manager_circuit_breaker.py` | Fault tolerance pattern |
| `backend/services/ai_manager_degradation.py` | Graceful degradation tiers |

## Relevant Frontend Files

| File | Purpose |
|------|---------|
| `frontend/src/components/accounts/AIMonitorPanel.tsx` | Main AI Manager dashboard (887 lines) |
| `frontend/src/components/accounts/AccountDetailView.tsx` | Tab container |
| `frontend/src/components/accounts/ConfigPanel.tsx` | Config editor |
| `frontend/src/components/accounts/PerformancePanel.tsx` | Performance metrics |
| `frontend/src/components/accounts/DecisionLog.tsx` | Decision history |
| `frontend/src/store/ai-manager-slice.ts` | Redux state (439 lines) |
| `frontend/src/api/client.ts` | API client (aiManagerApi namespace) |
| `frontend/src/hooks/useAccountWebSocket.ts` | WebSocket integration |

## Current Capabilities (Backend has, UI partially shows)

| Capability | Backend | UI Status |
|------------|---------|-----------|
| FSM State Machine | Full | Shown (state badge) |
| Emergency Fast-Path | Full | Partial (cooldown, ref equity) |
| Kill Switch | Full | Shown (button + warning) |
| Circuit Breaker | Full | Shown (count badge) |
| Graceful Degradation | Full | Shown (tier number) |
| Token Budget | Full | Shown (progress bar) |
| Daily P&L Tracking | Full | Shown (card) |
| Live Positions | Full | Shown (table) |
| Decision Log | Full | Shown (table) |
| Performance Metrics | Full | Shown (win rate, P&L) |
| Runtime Logs | Full | Shown (filterable list) |
| **LLM Call Details** | **Not logged individually** | **NOT shown** |
| **Capabilities Status** | **Not exposed as API** | **NOT shown** |
| **Market Insights/Commentary** | **Not generated** | **NOT shown** |
| **Current Thinking/Analysis** | **Partial (logs)** | **NOT shown as insights** |
| **Multi-Timeframe Analysis** | Full (backend) | **NOT shown** |
| **Correlation Analysis** | Full (backend) | **NOT shown** |
| **OrderBook Monitoring** | Full (backend) | **NOT shown** |
| **Market Regime** | Full (backend) | **NOT shown** |
| **Episodic Memory** | Full (backend) | **NOT shown** |
| **Sweep Detection** | Full (backend) | **NOT shown** |
| **Urgency Classification** | Full (backend) | **NOT shown (only in logs)** |

## Key Gaps to Fill
1. **LLM Call Logging**: No individual LLM call records (prompt, response, tokens, latency)
2. **Capabilities API**: No endpoint showing which modules are active/triggered/disabled
3. **Market Commentary**: No AI-generated insights for the user
4. **Rich Analysis View**: Backend computes regime, MTF, correlation, orderbook — none exposed to UI
5. **"Personal Manager" Experience**: No conversational/insights layer

## Database Tables (Existing)
- `ai_manager_state` — Per-account FSM state + config (JSONB)
- `ai_manager_decisions` — Immutable hash-chained decision log
- `ai_manager_logs` — Operational audit trail
- `regime_history` — Market regime snapshots
- `correlation_snapshots` — Correlation analysis results
- `sweep_events` — Sweep detection records
- `orderbook_snapshots` — Order book state captures

## WebSocket Events (Existing)
- `ai_manager.state_change` — FSM transitions
- `ai_manager.execution` — Trade execution results

## Design System
- Neumorphism design tokens (--neu-surface-base, --neu-shadow-pill, --neu-shadow-inset, etc.)
- NeuBadge, NeuButton components
- Lucide React icons
- Tailwind CSS utility classes
