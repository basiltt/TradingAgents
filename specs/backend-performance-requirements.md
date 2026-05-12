---
title: Backend Performance Overhaul — Requirements
feature: backend-performance
version: 1.0
date: 2026-05-12
---

# Backend Performance Overhaul — Requirements

## Problem Statement

When Market Scan runs with 8 parallel analyses, the entire application becomes unresponsive. API endpoints (health checks, UI data, account queries) stop responding. The root cause is that scan execution saturates the shared asyncio thread pool and event loop, starving all other work.

## Context

- Single-user trading tool running on one machine
- FastAPI async backend, React 19 frontend
- PostgreSQL (psycopg2 sync driver) + SQLite (LangGraph checkpoints)
- LangGraph agent execution is fully synchronous, wrapped in asyncio.to_thread()
- 172+ asyncio.to_thread() calls sharing default executor (~8 threads)

---

## Essential Requirements (P0 — Directly Fix Unresponsiveness)

### FR-001: Explicit Thread Pool Executor with Adequate Sizing
Set the default asyncio executor to a `ThreadPoolExecutor(max_workers=32)` at startup via `loop.set_default_executor()`. This immediately increases capacity for the 172+ `asyncio.to_thread()` calls that currently compete over ~8 default threads.

### FR-002: Dedicated Executor for LangGraph Scan Work
Create a separate named `ThreadPoolExecutor` exclusively for LangGraph `graph.stream()` execution. Pass it explicitly to `loop.run_in_executor()` in `analysis_service._execute_graph()`. This prevents scan work from competing with API-serving threads.

### FR-003: Scan Concurrency Cap with Rejection
Enforce a configurable maximum of concurrent scan analyses (default: 6, configurable via `MAX_CONCURRENT_SCANS` env var). When the limit is reached, new scan requests must be rejected immediately with HTTP 429 and a `retry_after` field. The existing `_MAX_CONCURRENT=25` in analysis_service is too high for a single machine.

### FR-004: Migrate PostgreSQL Driver from psycopg2 to asyncpg
Replace all synchronous psycopg2 calls and the `ThreadedConnectionPool` with asyncpg's native async pool. This eliminates thread-per-query overhead for all 172+ DB call sites and frees thread pool capacity for actual blocking work (LangGraph, LLM calls). The `threading.Semaphore(20)` guard becomes unnecessary.

### FR-005: Fix LLM Spacing Race Condition
Move `time.sleep(gap)` inside the lock in `base_client.py:59-74` so the delay and timestamp update are atomic. Currently two threads can both observe the same "safe" timestamp and fire simultaneously.

### FR-006: Non-Blocking CoinGecko Rate Limiter
Rewrite the CoinGecko rate limiter to use `asyncio.sleep()` instead of `time.sleep()`. The current implementation blocks a thread for 60+ seconds on rate limit, directly consuming a thread pool slot during scan workloads. The async version yields the event loop while waiting.

### FR-007: Timeout on parallel_debate future.result()
Add explicit timeout (300s) to all `future.result()` calls in `parallel_debate.py:107,128`. Currently these can hang indefinitely if an LLM call never returns, permanently consuming a thread.

### FR-008: Non-Blocking LLM Rate Limiter
Convert the LLM concurrency gate from `threading.Semaphore` to `asyncio.Semaphore`, acquired in the async layer before dispatching to the thread pool. This prevents threads from being held while waiting for rate limit permits.

---

## High-Value Requirements (P1 — Significant Quality Improvement)

### FR-009: asyncpg Connection Pool Right-Sizing
Configure asyncpg pool with `min_size=2`, `max_size=10` (not 20 — fewer connections reduces PostgreSQL overhead), `command_timeout=10s`, and `max_inactive_connection_lifetime=300s`. Log pool metrics (size, idle, waiters) on a 30s interval for diagnosis.

### FR-010: Per-Statement Query Timeout
Set `statement_timeout = '5s'` on connection checkout for normal queries. Long-running admin queries (migrations) use an explicit raised timeout. Prevents runaway queries from holding pool slots.

### FR-011: Health Endpoint Must Not Block Under Load
The `/health` endpoint must respond within 200ms regardless of scan load. Replace the `asyncio.to_thread(db.health_check)` with an asyncpg pool status check that doesn't acquire a connection. Report `degraded` state when scan concurrency exceeds 75% of limit.

### FR-012: Lifecycle-Managed Debate Executor
Replace the ad-hoc `ThreadPoolExecutor` in `parallel_debate.py` with a module-level executor created at startup and shut down on app teardown. Prevents executor proliferation during parallel scans.

### FR-013: Event Loop Watchdog
Run a lightweight coroutine that measures `asyncio.sleep(0.1)` wall-clock drift every 5s. Log a warning when drift exceeds 500ms, indicating synchronous code has leaked onto the event loop.

### FR-014: Graceful Shutdown with Drain Deadline
On shutdown, stop accepting new scans, allow in-flight analyses up to 30s to complete, then cancel remaining futures and clean up. Zero the in-flight counter and log a summary.

---

## Nice-to-Have Requirements (P2 — Future Improvement)

### FR-015: SQLite Checkpointer Migration
Migrate LangGraph checkpointer from per-ticker SQLite files to PostgreSQL checkpointer (or wrap in dedicated single-thread executor). Low priority since checkpoint I/O is brief and infrequent.

### FR-016: Scan Progress Push via WebSocket
Ensure all scan-level progress (ticker started/completed, overall %) is pushed through the existing event bus → WebSocket pipeline. The REST polling endpoint remains for terminal state only.

### FR-017: Correlation ID Propagation
Thread a request ID through all async boundaries, DB queries, and LLM calls for end-to-end tracing during debugging.

---

## Non-Functional Requirements

### NFR-001: API Responsiveness Under Load
The API must respond to non-scan endpoints within 500ms at p99 while 8 parallel analyses are running. Health endpoint within 200ms.

### NFR-002: Zero Data Loss on Migration
The psycopg2 → asyncpg migration must preserve all existing data. Migration can involve a brief restart (single-user tool, no zero-downtime requirement).

### NFR-003: Configuration via Environment Variables
All new tuning knobs (executor sizes, pool limits, timeouts, concurrency caps) must be configurable via environment variables with sensible defaults that work out of the box.

### NFR-004: Backward-Compatible API
No breaking changes to REST or WebSocket API contracts. Frontend must work without changes (aside from benefiting from improved responsiveness).

---

## Out of Scope

- Microservices architecture
- Kubernetes / container orchestration
- Prometheus / Grafana monitoring stack
- Per-client rate limiting (single-user tool)
- Zero-downtime deployment strategies
- CI performance regression gates
- Repository layer abstraction / ORM
- Full process isolation via multiprocessing (LangGraph is not pickle-safe)

---

## Requirement-to-Root-Cause Traceability

| Root Cause | Requirements |
|------------|-------------|
| Thread pool starvation (~8 default threads, 172+ callers) | FR-001, FR-002, FR-004 |
| No scan concurrency limit | FR-003 |
| Sync DB driver wastes threads | FR-004, FR-009, FR-010 |
| LLM spacing race condition | FR-005 |
| CoinGecko blocks thread 60+ seconds | FR-006 |
| parallel_debate hangs indefinitely | FR-007 |
| Sync LLM semaphore blocks threads | FR-008 |
| Health endpoint blocks under load | FR-011 |
| Executor proliferation in debate | FR-012 |
| No event loop starvation detection | FR-013 |
| Unclean shutdown leaks resources | FR-014 |
