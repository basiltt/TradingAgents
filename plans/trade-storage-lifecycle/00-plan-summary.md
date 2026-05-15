# Implementation Plan: Trade Storage & Lifecycle Tracking

## A. Title and Metadata

- **Plan name:** Trade Storage & Lifecycle Tracking
- **Date:** 2026-05-15
- **Author:** Claude Agent
- **Status:** Draft
- **Related spec:** specs/trade-storage-lifecycle-spec.md
- **Related architecture:** specs/trade-storage-lifecycle-architecture.md
- **Related feature:** Store all trades in DB with full lifecycle tracking including PnL on close
- **Version:** 1.0

## B. Planning Summary

- **What:** Add `trades` and `trade_events` tables, TradeRepository, TradeService, TradeReconciliationService, 6 API endpoints, and WebSocket broadcast integration to track every trade from placement through closure with PnL attribution.
- **Why:** Currently trades placed via the direct endpoint are fire-and-forget — no local record exists after the Bybit API returns.
- **High-level approach:** Database-first (migration → repository → schemas/API → service orchestration → reconciliation → tests). TDD throughout.
- **Key files affected:** `backend/async_persistence.py`, `backend/persistence.py`, `backend/schemas.py`, `backend/routers/accounts.py`, `backend/services/accounts_service.py`, `backend/services/close_positions_service.py`, `backend/services/trading_cycle_engine.py`, `backend/services/close_rule_evaluator.py`, plus 3 new service files.
- **Key risks:** Breaking change to place_trade response shape; dual persistence file sync; close-all position→trade mapping.
- **Key assumptions:** Single-user deployment (A-002), Bybit-only exchange (A-003), existing DB connection pool sufficient.

## C. Source Specification Reference

- **Spec file:** specs/trade-storage-lifecycle-spec.md
- **Architecture file:** specs/trade-storage-lifecycle-architecture.md
- **Spec version:** 1.0 (reviewed 5 rounds, all C/H resolved)
- **Requirement IDs covered:** FR-001 through FR-060, NFR-001 through NFR-014, AC-001 through AC-018

## D. Implementation Strategy

- **Overall approach:** Bottom-up layered implementation — database schema first, then repository (data access), then schemas/API (presentation), then service orchestration (business logic), then background reconciliation, then comprehensive tests.
- **Architecture alignment:** Follows existing patterns — raw SQL migrations in persistence files, services with `db: AsyncAnalysisDB` DI, FastAPI routers, asyncpg for async.
- **Existing patterns to reuse:**
  - Migration pattern from `async_persistence.py` / `persistence.py` (migration_N methods)
  - Service DI pattern from `AccountsService.__init__(self, db, ws_manager)`
  - Router pattern from `backend/routers/accounts.py`
  - Schema pattern from `backend/schemas.py` (Pydantic BaseModel with field_validator)
  - Error pattern: `JSONResponse(status_code=N, content={"detail": "...", "code": "..."})`
- **New patterns introduced:**
  - Cursor-based keyset pagination (new, replacing offset/limit for trade endpoints)
  - In-memory token bucket rate limiter as FastAPI dependency
  - Optimistic locking via version column
  - Post-commit fire-and-forget WebSocket broadcasts owned by TradeService
- **Dependency order:** Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
- **Risk-based sequencing:** Database first (most foundational, hardest to change later), reconciliation last (most complex, depends on all other components).

## E. Phase Breakdown

| Phase | File | Scope | Tasks | Entry Criteria | Exit Criteria |
|-------|------|-------|-------|----------------|---------------|
| 1 | 01-phase-database.md | Migration #25 DDL, triggers, indexes | ~8 | Clean baseline tests | Migration up/down works in both persistence files |
| 2 | 02-phase-repository.md | TradeRepository: CRUD, state machine, optimistic locking, pagination, events | ~15 | Phase 1 complete | All repository unit tests pass |
| 3 | 03-phase-schemas-api.md | Pydantic schemas, 6 API endpoints, rate limiter, cursor validation | ~12 | Phase 2 complete | All API tests pass |
| 4 | 04-phase-service-integration.md | TradeService orchestration, place_trade mod, close flows, WS broadcasts | ~14 | Phase 3 complete | All integration tests pass |
| 5 | 05-phase-reconciliation.md | TradeReconciliationService: background job, startup sweep, advisory locks | ~10 | Phase 4 complete | Reconciliation tests pass |
| 6 | 06-phase-testing.md | Comprehensive test coverage, regression, edge cases, security tests | ~12 | Phase 5 complete | 90%+ coverage, all tests green |

### Cross-Phase Dependencies

- Phase 2 depends on Phase 1 (tables must exist)
- Phase 3 depends on Phase 2 (repository methods called by routes)
- Phase 4 depends on Phase 3 (TradeService uses repository + schemas)
- Phase 5 depends on Phase 2 and Phase 4 (reconciliation uses repository and TradeService patterns)
- Phase 6 depends on all phases (comprehensive testing)

### Shared Interfaces

**TradeRepository (Phase 2, consumed by Phases 3-5):**
- `create_trade(conn, trade_data: dict) -> dict`
- `get_trade(conn, account_id: str, trade_id: str) -> dict | None`
- `list_trades(conn, account_id: str, filters: dict, cursor: str | None, limit: int) -> dict`
- `get_open_trades(conn, account_id: str) -> list[dict]`
- `get_trade_stats(conn, account_id: str) -> dict`
- `update_trade_status(conn, trade_id: str, account_id: str, old_version: int, new_status: str, updates: dict) -> dict | None`
- `close_trade(conn, trade_id: str, account_id: str, version: int, close_data: dict) -> dict | None`
- `create_trade_event(conn, event_data: dict) -> dict`
- `reconcile_close(conn, trade_id: str, account_id: str, close_data: dict) -> dict`

**TradeService (Phase 4, consumed by Phase 4 integration):**
- `close_single_trade(account_id: str, trade_id: str, qty: float | None) -> dict`
- `cancel_trade(account_id: str, trade_id: str) -> dict`

**Schemas (Phase 3, consumed by Phases 3-5):**
- `TradeResponse`, `TradeDetailResponse`, `TradeListResponse`, `TradeStatsResponse`, `TradeEventResponse`, `TradeCloseRequest`

### Global Constants

- **Project root:** `c:\Users\ttbasil\Desktop\Projects\PublicProjects\TradingAgents`
- **Backend root:** `backend/`
- **Test root:** `tests/`
- **Migration number:** 25
- **Advisory lock key:** (7001, 1)
- **Rate limit:** 10 req/s per account
- **Reconciliation interval:** 60 seconds
- **Orphan timeout:** 5 minutes

## G. File-Level Change Plan

| File | Action | Purpose | Phase |
|------|--------|---------|-------|
| `backend/async_persistence.py` | Modify | Add migration_25 (trades + trade_events DDL) | 1 |
| `backend/persistence.py` | Modify | Add migration_25 (identical DDL) | 1 |
| `backend/services/trade_repository.py` | Create | TradeRepository class | 2 |
| `backend/schemas.py` | Modify | Add Trade* schemas, TradeCloseRequest | 3 |
| `backend/routers/accounts.py` | Modify | Add 6 trade endpoints, rate limiter dep | 3 |
| `backend/services/trade_service.py` | Create | TradeService orchestration | 4 |
| `backend/services/accounts_service.py` | Modify | Insert trade on place_trade, add get_client() | 4 |
| `backend/services/close_positions_service.py` | Modify | Call TradeService for position→trade close mapping | 4 |
| `backend/services/trading_cycle_engine.py` | Modify | Insert trade with source=cycle | 4 |
| `backend/services/close_rule_evaluator.py` | Modify | Pass rule_id through to close service | 4 |
| `backend/services/account_ws_manager.py` | Modify | Add trade event broadcast methods | 4 |
| `backend/services/trade_reconciliation.py` | Create | TradeReconciliationService class | 5 |
| `backend/main.py` | Modify | Wire DI for TradeRepository, TradeService, TradeReconciliationService, startup task | 4, 5 |
| `tests/test_trade_repository.py` | Create | Repository unit tests | 2 |
| `tests/test_trade_api.py` | Create | API endpoint tests | 3 |
| `tests/test_trade_service.py` | Create | Service integration tests | 4 |
| `tests/test_trade_reconciliation.py` | Create | Reconciliation tests | 5 |
| `tests/test_trade_lifecycle.py` | Create | Full lifecycle integration tests | 6 |

## H. API Change Plan

| Endpoint | Method | Phase | Notes |
|----------|--------|-------|-------|
| `/accounts/{account_id}/trades` | GET | 3 | New — paginated trade list |
| `/accounts/{account_id}/trades/open` | GET | 3 | New — open trades only |
| `/accounts/{account_id}/trades/stats` | GET | 3 | New — cached aggregate stats |
| `/accounts/{account_id}/trades/{trade_id}` | GET | 3 | New — trade detail with events |
| `/accounts/{account_id}/trades/{trade_id}/close` | POST | 3 | New — close/partial close |
| `/accounts/{account_id}/trades/{trade_id}/cancel` | POST | 3 | New — cancel pending/partial |
| `/accounts/{account_id}/trade` (existing) | POST | 4 | Modified — now returns TradeResponse (breaking) |

## I. Database/Migration Plan

- **Migration #25** in both `async_persistence.py` and `persistence.py`
- **Tables:** `trades` (UUID PK, 40+ columns), `trade_events` (BIGSERIAL PK, append-only)
- **Indexes:** 13 on trades, 1 on trade_events
- **Triggers:** `trg_trades_updated_at` (BEFORE UPDATE), `trg_trade_events_immutable` (BEFORE UPDATE/DELETE with purge flag)
- **Rollback DDL:** DROP triggers → DROP functions → DROP trade_events → DROP trades (data-destructive)
- **Full DDL:** See specs/trade-storage-lifecycle-architecture.md Section 4

## R. Traceability Matrix (Summary)

See each phase file for detailed task-to-requirement mapping. All 60 FRs, 14 NFRs, and 18 ACs are covered across the 6 phases.

## S. Definition of Done

- [ ] All 6 phases implemented and committed
- [ ] Migration #25 works up/down in both persistence files
- [ ] All 60 FRs implemented
- [ ] All 18 ACs verified
- [ ] All tests pass (unit, integration, API)
- [ ] 90%+ test coverage on new code
- [ ] No unresolved Critical/High review findings
- [ ] Existing tests still pass (regression)
