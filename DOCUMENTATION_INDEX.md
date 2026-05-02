# TradingAgents Documentation Index

**Discovery Date:** May 3, 2026  
**Scope:** Complete codebase exploration of TradingAgents multi-agent stock analysis system

---

## 📚 Documentation Files

### 1. **CODEBASE_DISCOVERY.md** (559 lines)
**Purpose:** Comprehensive technical reference with all system details

**Sections:**
1. Overall Architecture - High-level data flow, directory structure
2. Data Providers & Vendor Configuration - yfinance, Alpha Vantage routing
3. LangGraph Trading Graph Structure - Graph nodes, execution flow
4. Analyst Types & Implementation - 4 analyst types, agent state
5. Structured Output Schemas - ResearchPlan, TraderProposal, PortfolioDecision
6. Configuration System - Default config, request overrides, hierarchy
7. Frontend Analysis Form - ConfigForm.tsx structure and fields
8. API Schemas & Endpoints - All request/response models and endpoints
9. LLM Provider Catalog - 9 providers, model options
10. Backend Architecture Details - Services, persistence, concurrency
11. Memory & Learning - Memory log, reflection system
12. Test Structure - 30+ test files organization
13. Key Utilities - Agent tools, dataflow utils
14. Environment Variables - All required and optional env vars
15. Key Takeaways - Architecture highlights, data flow summary

**Use for:** Deep understanding of system architecture, finding specific file paths, understanding configuration hierarchy

---

### 2. **QUICK_REFERENCE.md** (340 lines)
**Purpose:** Fast developer guide for common tasks

**Sections:**
- System Overview
- Entry Points (Frontend form, Backend endpoint)
- Analyst Agent Flow (4 steps: parallel → research → trading → risk mgmt)
- Data Vendor Routing (Configuration, fallback, tool types)
- Configuration Hierarchy (Priority order)
- Structured Output Schemas (Quick reference)
- LLM Providers (All 9 with modes)
- Backend Architecture (Concurrency, persistence, streaming)
- API Endpoints Summary (All endpoints with methods)
- Memory & Learning (Markdown-based memory log)
- Testing (Quick overview)
- File Paths - Key Components (Fast lookup by component)
- Default Configuration (Ready-to-reference config)
- Quick Start Reference (5-step process flow)

**Use for:** Getting started, quick lookups, understanding data flow at a glance

---

### 3. **ARCHITECTURE_DIAGRAMS.md** (452 lines)
**Purpose:** Visual representations and detailed timelines

**Content:**
- System Architecture Overview (ASCII diagram with all components)
- Data Flow (Detailed timeline from T=0s to T=19s with execution steps)
- Request Configuration Hierarchy (Visual merge order)
- LLM Provider Selection Flow (Dynamic model catalog flow)

**Diagrams show:**
`
Frontend Form
    ↓
FastAPI Backend
    ↓
Analysis Service (concurrency control)
    ↓
LangGraph (4 parallel analysts + researchers + managers + risk debators)
    ↓
Data Vendor Abstraction (route to yfinance or Alpha Vantage)
    ↓
Stream Processing & Persistence (WebSocket broadcast + SQLite)
    ↓
Response Back to Frontend
`

**Use for:** Understanding system visualization, debugging data flow, presentations

---

## 🎯 Quick Navigation by Topic

### Understanding Architecture
→ Start with: **ARCHITECTURE_DIAGRAMS.md**  
→ Deep dive: **CODEBASE_DISCOVERY.md** sections 1, 3, 10

### Working with Analysts & Agents
→ Overview: **QUICK_REFERENCE.md** "Analyst Agent Flow"  
→ Details: **CODEBASE_DISCOVERY.md** sections 3, 4, 5

### Configuring Data Vendors
→ Quick: **QUICK_REFERENCE.md** "Data Vendor Routing"  
→ Complete: **CODEBASE_DISCOVERY.md** section 2, 6

### API Integration
→ Reference: **QUICK_REFERENCE.md** "API Endpoints Summary"  
→ Full specs: **CODEBASE_DISCOVERY.md** section 8

### LLM Provider Support
→ Options: **QUICK_REFERENCE.md** "LLM Providers"  
→ Catalog: **CODEBASE_DISCOVERY.md** section 9

### Configuration Management
→ Hierarchy: **QUICK_REFERENCE.md** "Configuration Hierarchy"  
→ Details: **CODEBASE_DISCOVERY.md** section 6

### Understanding Data Flow
→ Timeline: **ARCHITECTURE_DIAGRAMS.md** "Data Flow (Detailed Timeline)"  
→ Technical: **CODEBASE_DISCOVERY.md** section 1

### Frontend Development
→ Form guide: **QUICK_REFERENCE.md** or **CODEBASE_DISCOVERY.md** section 7

### Backend Services
→ Overview: **QUICK_REFERENCE.md** "Backend Architecture Details"  
→ Full details: **CODEBASE_DISCOVERY.md** section 10

### Memory & Learning
→ Summary: **QUICK_REFERENCE.md** "Memory & Learning"  
→ Details: **CODEBASE_DISCOVERY.md** section 11

### Testing Strategy
→ Overview: **QUICK_REFERENCE.md** "Testing"  
→ Full reference: **CODEBASE_DISCOVERY.md** section 12

---

## 📋 Key Files by Component

### Core Agent System
`
tradingagents/agents/analysts/              Market, Social, News, Fundamentals
tradingagents/agents/managers/              Research Manager, Portfolio Manager
tradingagents/agents/researchers/           Bull & Bear researchers
tradingagents/agents/risk_mgmt/             Risk debators
tradingagents/agents/utils/                 Tools, memory, state definitions
`

### Data Fetching
`
tradingagents/dataflows/interface.py        Vendor routing layer
tradingagents/dataflows/y_finance.py        Yahoo Finance implementation
tradingagents/dataflows/alpha_vantage*.py   Alpha Vantage implementations
`

### Graph Orchestration
`
tradingagents/graph/trading_graph.py        Main graph class
tradingagents/graph/setup.py                Graph construction
tradingagents/graph/conditional_logic.py    Routing & flow control
`

### LLM Clients
`
tradingagents/llm_clients/factory.py        Provider routing
tradingagents/llm_clients/model_catalog.py  Model options
tradingagents/llm_clients/*_client.py       Provider implementations
`

### Backend API
`
backend/main.py                             FastAPI initialization
backend/routers/analysis.py                 Analysis CRUD + report
backend/routers/config.py                   Config management
backend/services/analysis_service.py        Lifecycle management
backend/persistence.py                      SQLite abstraction
backend/event_bus.py                        WebSocket broadcasting
`

### Frontend
`
frontend/src/components/analysis/ConfigForm.tsx       Analysis form (MAIN INPUT)
frontend/src/components/analysis/AnalysisDashboard.tsx Live updates
frontend/src/api/client.ts                            API wrapper
frontend/src/hooks/useAnalysisWebSocket.ts            WebSocket connection
`

### Tests
`
tests/backend/                              Backend unit tests
tests/                                      Integration tests
`

---

## 🔍 Quick Facts

### System Metrics
- **File Count:** 100+ Python files, 40+ React components, 30+ test files
- **Codebase Size:** ~8,000 lines (backend) + ~3,500 lines (frontend)
- **Concurrency:** Max 3 concurrent analyses
- **Timeout:** 30min wall / 35min hard limit
- **Memory Log:** Markdown-based, auto-rotating

### Supported Providers (9 total)
1. OpenAI (GPT-5.x, GPT-4.x)
2. Anthropic (Claude Opus/Sonnet/Haiku)
3. Google (Gemini 3.x/2.5)
4. xAI (Grok 4.x)
5. DeepSeek (V4, V3.2)
6. Qwen (3.x, Plus)
7. GLM (5.x, 4.7)
8. Azure (Any deployed model)
9. Ollama (Local inference)

### Supported Data Vendors (2 total)
1. Yahoo Finance (yfinance) - Default, free
2. Alpha Vantage - Requires API key

### Analyst Types (4 total)
1. Market - Technical analysis
2. Social - Sentiment analysis
3. News - News events
4. Fundamentals - Financial analysis

### Agent Chain (6 stages)
1. Parallel Analysts (fetch data)
2. Bull & Bear Researchers (debate)
3. Research Manager (recommendation)
4. Trader (transaction proposal)
5. Risk Debators (risk debate)
6. Portfolio Manager (final decision)

---

## 📖 How to Use This Documentation

### For Code Review
1. Read: **ARCHITECTURE_DIAGRAMS.md** (understand flow)
2. Reference: **CODEBASE_DISCOVERY.md** (find specific details)
3. Verify: Check file paths in section 13

### For Feature Development
1. Check: **QUICK_REFERENCE.md** (relevant component)
2. Understand: **CODEBASE_DISCOVERY.md** (related sections)
3. Reference: API schemas & tests

### For Integration
1. Review: **QUICK_REFERENCE.md** "API Endpoints"
2. Study: **CODEBASE_DISCOVERY.md** section 8
3. Reference: ackend/schemas.py for validation

### For Debugging
1. Timeline: **ARCHITECTURE_DIAGRAMS.md** (trace execution)
2. Details: **CODEBASE_DISCOVERY.md** (component details)
3. Test: Look for existing test in 	ests/

### For Onboarding
1. Start: **QUICK_REFERENCE.md** (system overview)
2. Deep Dive: **ARCHITECTURE_DIAGRAMS.md** (data flow)
3. Reference: **CODEBASE_DISCOVERY.md** (specific details)

---

## 🔗 Cross-References

### Configuration
- Default: 	radingagents/default_config.py
- Request validation: ackend/schemas.py
- Frontend form: rontend/src/components/analysis/ConfigForm.tsx
- Service: ackend/services/config_service.py

### Data Vendors
- Interface: 	radingagents/dataflows/interface.py
- Frontend selector: rontend/src/components/analysis/ConfigForm.tsx (data_vendor fields)
- Configuration: 	radingagents/default_config.py (data_vendors + tool_vendors)

### Agents
- Schemas: 	radingagents/agents/schemas.py (ResearchPlan, TraderProposal, PortfolioDecision)
- Graph: 	radingagents/graph/setup.py (node creation + wiring)
- Tools: 	radingagents/agents/utils/ (agent_utils.py, core_stock_tools.py, etc.)

### API
- Schemas: ackend/schemas.py (all Pydantic models)
- Routers: ackend/routers/ (endpoint implementations)
- Services: ackend/services/ (business logic)

### LLM
- Catalog: 	radingagents/llm_clients/model_catalog.py
- Factory: 	radingagents/llm_clients/factory.py
- Clients: 	radingagents/llm_clients/*_client.py
- Frontend: rontend/src/lib/model-catalog.ts

---

## 📝 Documentation Maintenance

These documents were generated on **May 3, 2026** by scanning:
- All .py files in 	radingagents/, ackend/, cli/, 	ests/
- All .tsx/.ts files in rontend/src/
- Configuration files and entry points

**To update:** Re-scan codebase if major changes occur to:
- Agent architecture
- API endpoints
- Configuration schema
- Provider support
- Data vendor integrations

---

**Documentation Complete - Ready for Reference**
