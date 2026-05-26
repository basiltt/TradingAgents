# AI Account Manager — Implementation Progress

## Adaptations from Plan Validation
- Migration: embedded in `backend/async_persistence.py` as #33 (not Alembic)
- `account_id` is TEXT (not UUID) — all FKs reference `trading_accounts(id)` as TEXT
- Database: raw asyncpg pool queries (not SQLAlchemy ORM)
- Schemas: new file `backend/ai_manager_schemas.py` (existing `schemas.py` is 1239 lines)
- `AutoTradeConfig` in `backend/schemas.py`: add `ai_manager_enabled: bool = False`

---

## Phase 1: Database Schema & Data Models

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| 1.1 | Migration #33 (all tables) | DONE | 8 tables + indexes + partitions |
| 1.2 | Pydantic schemas | DONE | 16 tests pass |
| 1.3 | Repository (async_persistence pattern) | DONE | 10 tests pass |

## Phase 2: Core Service — FSM + Lifecycle

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| 2.1 | Position Lock Registry | DONE | 7 tests pass |
| 2.2 | Priority LLM Scheduler | DONE | 7 tests pass |
| 2.3 | AI Account Manager Service | DONE | Orchestrator with health sweep, dead-letter, pattern loops |
| 2.4 | Per-Account Task (FSM) | DONE | 13 tests pass |
| 2.5 | WS Event Integration | DONE | Integrated in service + task (dispatch by account_id) |
| 2.6 | Circuit Breaker | DONE | 6 tests pass |
| 2.7 | Dead-Letter Retry | DONE | Loop in service, retries with max exhaustion |
| 2.8 | Degradation Tier Manager | DONE | 10 tests pass |
| 2.9 | Pattern Generation Scheduler | DONE | 24h loop stub in service |

## Phase 3: Decision Engine (LangGraph)

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| 3.1 | Decision Graph Definition | IN_PROGRESS | Stub graph created, full LangGraph nodes pending |
| 3.2 | Context Builder (Prompt Assembly) | PENDING | |
| 3.3 | Memory Service | PENDING | |
| 3.4 | Signal Detection | PENDING | |
| 3.5 | Daily Loss Enforcement | PENDING | |

## Phase 4: API Endpoints + WebSocket Events

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| 4.1 | REST Router | PENDING | |
| 4.2 | WebSocket Event Broadcasting | PENDING | |
| 4.3 | Service Wiring (main.py) | PENDING | |

## Phase 5: Frontend Integration

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| 5.1 | Redux Slice | PENDING | |
| 5.2 | AI Manager Card | PENDING | |
| 5.3 | Decision Log | PENDING | |
| 5.4 | Config Panel | PENDING | |
| 5.5 | Performance Panel | PENDING | |
