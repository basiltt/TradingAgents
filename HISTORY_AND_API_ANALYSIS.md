# Trading Agents: History Component, Storage & API Analysis

**Scope:** Frontend history component, analysis data storage, and API endpoints
**Date:** May 3, 2026

## 1. HISTORY PAGE COMPONENT

**File:** `frontend/src/components/dashboard/HistoryList.tsx`


## 2. KEY REPORT SECTIONS

Trade score and confidence data is stored in report_sections table:

**trader** section:
- action: Buy, Sell, Hold
- confidence: 1-10 scale
- entry_price, stop_loss, take_profit levels
- risk_reward_ratio, position_sizing

**portfolio_manager** section:
- rating: Buy, Overweight, Hold, Underweight, Sell
- confidence: 1-10 scale
- executive_summary: Text reasoning

**final_trade_decision** section:
- Merged consolidated recommendation

**_snapshot** section (JSON):
- agents: agent completion status
- messages: message history with seq
- stats: tokens_in, tokens_out, llm_calls, tool_calls
- reports: all section content combined

---

## 3. API ENDPOINTS

GET /api/v1/analysis - List all analyses
- Query params: page, limit, ticker, status, asset_type, from_date, to_date

GET /api/v1/analysis/{run_id} - Get analysis details
- Returns: run metadata, config, status, timestamps

GET /api/v1/analysis/{run_id}/snapshot - Get JSON snapshot
- Returns: agents, messages, stats, reports (with trade scores)

GET /api/v1/analysis/{run_id}/report - Get markdown report
- Returns: formatted markdown text

POST /api/v1/analysis - Create analysis
DELETE /api/v1/analysis/{run_id} - Delete analysis
DELETE /api/v1/analysis - Delete all analyses
POST /api/v1/analysis/{run_id}/cancel - Cancel running analysis

---

## 4. QUICK REFERENCE

History Component: frontend/src/components/dashboard/HistoryList.tsx
Database: ~/.tradingagents/cache/web_runs.db (SQLite)
API Base: /api/v1

Trade Scores:
- Access via GET /api/v1/analysis/{run_id}/snapshot
- Stored in report_sections: trader, portfolio_manager, final_trade_decision
- Parse trade card from trader + portfolio_manager sections
- Fields: action, confidence, rating, entry_price, stop_loss, take_profit
