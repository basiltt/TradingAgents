# AI Account Manager — Implementation Plan (v2)

## Overview
5 phases, estimated ~4000 lines of backend code + ~1500 lines frontend.

**Database:** PostgreSQL (MVCC, partitioned tables, pg_cron)
**Key Files:** All new except: `backend/main.py` (wiring), `backend/services/close_rule_evaluator.py` (shared lock import)

---

## Phase 1: Database Schema & Data Models

### Task 1.1: PostgreSQL Migration (Alembic)
**File:** `backend/migrations/versions/xxxx_add_ai_manager_tables.py`
**Action:** Create migration with `upgrade()` and `downgrade()`:

**Table 1 — ai_manager_state:**
```sql
CREATE TABLE ai_manager_state (
    account_id UUID PRIMARY KEY REFERENCES trading_accounts(id),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    fsm_state TEXT NOT NULL DEFAULT 'sleeping',
    config JSONB NOT NULL DEFAULT '{}',
    circuit_breaker_count INTEGER DEFAULT 0,
    circuit_breaker_active BOOLEAN DEFAULT FALSE,
    circuit_breaker_half_open_used BOOLEAN DEFAULT FALSE,
    actions_today INTEGER DEFAULT 0,
    actions_this_hour INTEGER DEFAULT 0,
    max_daily_actions INTEGER NOT NULL DEFAULT 30,
    max_hourly_actions INTEGER NOT NULL DEFAULT 10,
    equity_at_day_start NUMERIC(18,8),
    realized_loss_today NUMERIC(18,8) DEFAULT 0,
    token_budget_used_today INTEGER DEFAULT 0,
    last_analysis_at TIMESTAMPTZ,
    last_action_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    counters_reset_at TIMESTAMPTZ,  -- daily reset tracker
    hourly_reset_at TIMESTAMPTZ,  -- hourly reset tracker (separate from daily to avoid shared-timestamp collision)
    kill_switch_active BOOLEAN DEFAULT FALSE,
    strategy_version TEXT DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_fsm_state CHECK (fsm_state IN ('sleeping','monitoring','analyzing','executing','paused','error'))
);
CREATE INDEX idx_ai_state_orphan ON ai_manager_state (fsm_state, heartbeat_at) WHERE fsm_state NOT IN ('sleeping');
CREATE INDEX idx_ai_state_enabled ON ai_manager_state (enabled) WHERE enabled = TRUE;
```

**Table 2 — ai_manager_decisions (PARTITIONED):**
```sql
CREATE TABLE ai_manager_decisions (
    id BIGSERIAL,
    account_id UUID NOT NULL REFERENCES trading_accounts(id),
    timestamp TIMESTAMPTZ NOT NULL,
    evaluation_type TEXT NOT NULL,
    urgency TEXT NOT NULL,
    state_snapshot JSONB NOT NULL,
    action_taken JSONB NOT NULL,
    reasoning TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    graph_path TEXT,
    execution_result JSONB,
    outcome JSONB,
    outcome_label TEXT,
    strategy_version TEXT NOT NULL,
    prev_decision_hash TEXT,
    decision_hash TEXT NOT NULL,
    chain_key_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

CREATE INDEX idx_ai_decisions_account ON ai_manager_decisions(account_id, timestamp DESC)
    INCLUDE (action_taken, confidence, outcome_label, execution_result);
CREATE INDEX idx_ai_decisions_outcome ON ai_manager_decisions(account_id, outcome_label, timestamp DESC);
CREATE UNIQUE INDEX idx_ai_decisions_hash ON ai_manager_decisions(account_id, decision_hash, timestamp);
```

**Table 3 — ai_manager_patterns:**
```sql
CREATE TABLE ai_manager_patterns (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES trading_accounts(id),
    pattern_type TEXT NOT NULL,
    symbol TEXT,
    description TEXT NOT NULL,
    evidence_count INTEGER DEFAULT 1,
    confidence FLOAT DEFAULT 0.5,
    last_validated TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_pattern_description_len CHECK (char_length(description) <= 200)
);
CREATE INDEX idx_ai_patterns_account ON ai_manager_patterns(account_id, active, confidence DESC);
```

**Table 4 — ai_manager_failed_outcomes (dead-letter):**
```sql
CREATE TABLE ai_manager_failed_outcomes (
    id BIGSERIAL PRIMARY KEY,
    decision_id BIGINT NOT NULL,  -- no FK (PG cannot FK to partitioned tables); app-layer integrity
    decision_timestamp TIMESTAMPTZ NOT NULL,  -- stored for efficient join to partitioned table
    execution_result JSONB NOT NULL,
    failure_reason TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    next_retry_at TIMESTAMPTZ,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_failed_outcomes_retry ON ai_manager_failed_outcomes(resolved, next_retry_at) WHERE resolved = FALSE;
-- Note: No FK to ai_manager_decisions because PG does not support FKs referencing partitioned tables.
-- Referential integrity enforced at application layer (decision_id always written by same service).
```

**ALTERs:**
```sql
ALTER TABLE trades ADD COLUMN ai_closed BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN ai_decision_id BIGINT;  -- no FK (partitioned table); app-layer integrity enforced same as ai_manager_failed_outcomes
CREATE INDEX idx_trades_ai_decision_id ON trades(ai_decision_id) WHERE ai_decision_id IS NOT NULL;
ALTER TABLE auto_trade_configs ADD COLUMN ai_manager_config JSONB DEFAULT NULL;
```

**Table 5 — ai_manager_global_state (single-row system state, required by Phase 2 DegradationTierManager):**
```sql
CREATE TABLE ai_manager_global_state (
    key TEXT PRIMARY KEY,
    int_value INTEGER,
    text_value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO ai_manager_global_state (key, int_value) VALUES ('degradation_tier', 0);
```

**Table 6 — security_events and Table 7 — reauth_nonces:** DDL shown in Phase 4 Task 4.1 but MUST be included in this same Phase 1 migration file (pg_cron jobs reference them). See Task 4.1 for full DDL.

**pg_cron jobs (separate idempotent setup script, NOT inside Alembic migration):**
Guard with extension check: `DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN ... END IF; END $$;`
Use `cron.schedule` which is idempotent (updates existing job with same name):
```sql
SELECT cron.schedule('ai_mgr_daily_reset', '0 0 * * *',
    $$UPDATE ai_manager_state SET actions_today=0, realized_loss_today=0, token_budget_used_today=0, equity_at_day_start=NULL, counters_reset_at=NOW() WHERE enabled=TRUE$$);
SELECT cron.schedule('ai_mgr_hourly_reset', '0 * * * *',
    $$UPDATE ai_manager_state SET actions_this_hour=0, hourly_reset_at=NOW() WHERE enabled=TRUE$$);
SELECT cron.schedule('ai_mgr_nonce_cleanup', '*/10 * * * *',
    $$DELETE FROM reauth_nonces WHERE expires_at < NOW()$$);
SELECT cron.schedule('ai_mgr_security_events_purge', '0 3 * * 0',
    $$DELETE FROM security_events WHERE timestamp < NOW() - interval '90 days'$$);
SELECT cron.schedule('ai_mgr_partition_create', '0 0 24 * *',
    $$DO $b$ BEGIN EXECUTE format('CREATE TABLE IF NOT EXISTS ai_manager_decisions_%s PARTITION OF ai_manager_decisions FOR VALUES FROM (%L) TO (%L)', to_char(NOW() + interval '1 month', 'YYYY_MM'), date_trunc('month', NOW() + interval '1 month'), date_trunc('month', NOW() + interval '2 months')); END $b$$$);
```
In environments without pg_cron, these resets must be handled by the application (fallback documented in deployment notes).

**Partition management:** Migration MUST create current-month and next-month partitions inline:
```sql
CREATE TABLE ai_manager_decisions_YYYY_MM PARTITION OF ai_manager_decisions
    FOR VALUES FROM ('YYYY-MM-01') TO ('YYYY-MM+1-01');
CREATE TABLE ai_manager_decisions_YYYY_MM_next PARTITION OF ai_manager_decisions
    FOR VALUES FROM ('YYYY-MM+1-01') TO ('YYYY-MM+2-01');
CREATE TABLE ai_manager_decisions_default PARTITION OF ai_manager_decisions DEFAULT;
```
pg_cron job auto-creates next month's partition 7 days in advance. Application-level fallback: `insert_decision()` catches partition-not-found error, calls `_ensure_partition(year, month)` which runs `CREATE TABLE IF NOT EXISTS ... PARTITION OF ...`, then retries the INSERT. DEFAULT partition catches any edge case to prevent hard failures. Fallback logs WARNING metric for ops visibility.

**Downgrade path (`downgrade()`):**
```sql
-- Unschedule pg_cron jobs (guarded same as upgrade)
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    PERFORM cron.unschedule('ai_mgr_daily_reset');
    PERFORM cron.unschedule('ai_mgr_hourly_reset');
    PERFORM cron.unschedule('ai_mgr_nonce_cleanup');
    PERFORM cron.unschedule('ai_mgr_security_events_purge');
    PERFORM cron.unschedule('ai_mgr_partition_create');
END IF; END $$;
-- Drop tables in reverse dependency order (CASCADE handles child partitions)
DROP TABLE IF EXISTS ai_manager_failed_outcomes;
DROP TABLE IF EXISTS ai_manager_patterns;
DROP TABLE IF EXISTS ai_manager_decisions CASCADE;  -- drops all child partitions
DROP TABLE IF EXISTS ai_manager_global_state;
DROP TABLE IF EXISTS reauth_nonces;
DROP TABLE IF EXISTS security_events;
DROP TABLE IF EXISTS ai_manager_state;
-- Remove added columns
ALTER TABLE trades DROP COLUMN IF EXISTS ai_closed;
ALTER TABLE trades DROP COLUMN IF EXISTS ai_decision_id;
ALTER TABLE auto_trade_configs DROP COLUMN IF EXISTS ai_manager_config;
```

### Task 1.2: Pydantic Schemas
**File:** `backend/schemas/ai_manager.py`
**Action:** Create all models with Pydantic Field validation per Amendment AK:
```python
class AIManagerConfig(BaseModel):
    enabled: bool = False
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"
    evaluation_interval_s: int = Field(default=60, ge=30, le=300)
    max_daily_actions: int = Field(default=30, ge=5, le=100)
    max_hourly_actions: int = Field(default=10, ge=2, le=30)
    max_daily_loss_pct: float = Field(default=5.0, ge=1.0, le=25.0)
    daily_profit_target_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)
    min_position_age_s: int = Field(default=300, ge=60, le=3600)
    confidence_threshold: float = Field(default=0.7, ge=0.3, le=0.95)
    max_single_decision_loss_pct: float = Field(default=3.0, ge=0.5, le=10.0)
    dry_run: bool = False
    grace_period_s: int = Field(default=0, ge=0, le=30)
    excluded_symbols: List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]] = Field(default_factory=list, max_length=50)
    locked_positions: List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]] = Field(default_factory=list, max_length=50)
    strategy_version: str = Field(default="default", pattern=r"^[a-zA-Z0-9_\-]{1,50}$")

class PositionAction(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,20}$")
    action: Literal["close", "partial_close", "adjust_tp", "adjust_sl", "hold"]
    close_pct: Optional[int] = Field(default=None, ge=1, le=100)
    new_tp: Optional[Decimal] = Field(default=None, gt=0)
    new_sl: Optional[Decimal] = Field(default=None, gt=0)
    # risk_validation node additionally rejects TP/SL deviating >50% from current market price

class AIManagerAction(BaseModel):
    action_type: Literal["HOLD", "FULL_CLOSE", "PARTIAL_CLOSE", "ADJUST_TP", "ADJUST_SL"]
    positions: List[PositionAction]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=500)
    urgency: Literal["low", "medium", "high", "critical"]

class AIManagerStatus(BaseModel):
    enabled: bool
    state: str
    last_analysis_at: Optional[datetime]
    circuit_breaker: dict
    actions_today: int
    budget_remaining: dict
    degradation_tier: int  # global, from DegradationTierManager.get_tier()
    kill_switch: bool

class AIManagerDecisionResponse(BaseModel):
    id: int
    timestamp: datetime
    action_taken: dict
    reasoning: str
    confidence: float
    urgency: str
    execution_result: Optional[dict]
    outcome: Optional[dict]
    outcome_label: Optional[str]

class AIManagerConfigPatch(BaseModel):
    """For PATCH endpoint. Uses model_fields_set to distinguish omit vs null.
    omit=keep, null=reset to default, present=update."""
    risk_tolerance: Optional[Literal["conservative", "moderate", "aggressive"]] = None
    evaluation_interval_s: Optional[int] = Field(default=None, ge=30, le=300)
    max_daily_actions: Optional[int] = Field(default=None, ge=5, le=100)
    max_hourly_actions: Optional[int] = Field(default=None, ge=2, le=30)
    max_daily_loss_pct: Optional[float] = Field(default=None, ge=1.0, le=25.0)
    daily_profit_target_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)
    min_position_age_s: Optional[int] = Field(default=None, ge=60, le=3600)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.3, le=0.95)
    max_single_decision_loss_pct: Optional[float] = Field(default=None, ge=0.5, le=10.0)
    dry_run: Optional[bool] = None
    grace_period_s: Optional[int] = Field(default=None, ge=0, le=30)
    excluded_symbols: Optional[List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]]] = Field(default=None, max_length=50)
    locked_positions: Optional[List[Annotated[str, Field(max_length=20, pattern=r"^[A-Z0-9]{1,20}$")]]] = Field(default=None, max_length=50)
    # Dispatch: field in model_fields_set + non-None = update; field in model_fields_set + None = reset; field NOT in model_fields_set = keep
```

### Task 1.3: Database Repository
**File:** `backend/services/ai_manager_repository.py`
**Action:** Create async repository:
- `get_state(account_id)` → AIManagerState or None
- `upsert_state(account_id, **fields)` → updated state
- `update_heartbeat(account_id)` → None
- `insert_decision(account_id, decision_data)` → tuple(decision_id, decision_timestamp) (with hash chain, genesis sentinel "0"*64)
  **Atomicity:** The SELECT-latest-hash + INSERT-new-decision MUST execute in a single transaction with `SELECT decision_hash FROM ai_manager_decisions WHERE account_id = $1 ORDER BY timestamp DESC, id DESC LIMIT 1 FOR UPDATE` to serialize chain appends per account.
- `update_decision_outcome(decision_id, decision_timestamp, outcome)` → None (WHERE id=$1 AND timestamp=$2 for partition pruning)
- `record_realized_loss(account_id, loss_amount)` → dict (returns updated totals)
  **SQL:** `UPDATE ai_manager_state SET realized_loss_today = realized_loss_today + $loss WHERE account_id = $1 RETURNING realized_loss_today, equity_at_day_start` (single-statement atomic, matches counter pattern)
- `get_recent_decisions(account_id, limit=15)` → List[dict] (for memory injection)
  Projection: SELECT id, account_id, timestamp, action_taken, confidence, outcome_label only (index-only scan via INCLUDE index, no heap fetch of state_snapshot)
- `get_decisions_page(account_id, cursor, limit, outcome_filter)` → (List[dict], next_cursor)
  Cursor is composite keyset: base64-encoded `{id, timestamp}`. Query uses `WHERE (timestamp, id) < ($ts, $id)` for partition pruning.
- `get_patterns(account_id, active=True, limit=5)` → List[dict]
- `upsert_pattern(account_id, pattern_data)` → pattern_id
- `count_active_patterns(account_id)` → int
- `deactivate_lowest_confidence_pattern(account_id)` → None
- `increment_actions_atomic(account_id)` → bool (True if within budget)
  ```sql
  UPDATE ai_manager_state
  SET actions_today = actions_today + 1, actions_this_hour = actions_this_hour + 1, updated_at = NOW()
  WHERE account_id = $1 AND actions_today < max_daily_actions AND actions_this_hour < max_hourly_actions
  RETURNING account_id;
  ```
- `record_realized_loss(account_id, loss_amount)` → dict (returns updated totals)
- `increment_token_budget_atomic(account_id, tokens_used, max_tokens)` → bool
  ```sql
  UPDATE ai_manager_state SET token_budget_used_today = token_budget_used_today + $tokens
  WHERE account_id = $1 AND token_budget_used_today + $tokens <= $max
  RETURNING account_id;
  ```
- `set_kill_switch(account_id, active)` → None
- `set_global_kill(active)` → None
- `reset_kill_switch(account_id)` → None
- `sync_config_columns(account_id, config)` → None (denormalize max_daily/hourly in SAME UPDATE as config JSONB write — single atomic statement, not two separate calls)
- Dead-letter operations:
  - `insert_failed_outcome(decision_id, result, reason)` → id
  - `get_pending_retries(limit=10)` → List[dict]
  - `increment_retry(id)` → None
  - `mark_resolved(id, reason)` → None

---

## Phase 2: Core Service — FSM + Lifecycle

### Task 2.1: Position Lock Registry (Shared)
**File:** `backend/services/position_lock_registry.py`
**Action:** Create shared singleton:
```python
class PositionLockRegistry:
    """Shared per-position lock between AIManager and CloseRuleEvaluator."""
    def __init__(self):
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._last_used: Dict[Tuple[str, str], float] = {}

    async def acquire(self, account_id: str, symbol: str, timeout: float = 30.0) -> bool:
        """Acquire lock with TTL. Returns False if timeout exceeded."""

    def release(self, account_id: str, symbol: str):
        """Release lock."""

    def cleanup_account(self, account_id: str):
        """Remove all locks for account (called on SLEEPING transition)."""

    async def evict_stale(self, max_idle_s: float = 300.0):
        """Remove locks unused for >5min AND not currently held (check lock.locked()). 
        Protected by internal asyncio.Lock to avoid evict-vs-acquire race."""
```
Wire into both AIAccountManagerService and CloseRuleEvaluator (modify CloseRuleEvaluator to import and use).

### Task 2.2: Priority LLM Scheduler
**File:** `backend/services/ai_manager_llm_scheduler.py`
**Action:** Create multi-lane priority scheduler per Amendments K/V:
```python
class PriorityLLMScheduler:
    """3 FAST reserved + 7 shared STANDARD/DEEP slots (per spec Amendment K)."""
    def __init__(self):
        self._fast_sem = asyncio.Semaphore(3)
        self._general_sem = asyncio.Semaphore(7)  # shared by STANDARD and DEEP
        self._account_inflight: Dict[str, int] = {}  # max 1 per account
        self._account_queued: Dict[str, int] = {}  # max 1 per account
        self._general_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._deep_active: int = 0  # soft cap at 2 for DEEP within the 7

    async def acquire(self, account_id: str, urgency: str) -> bool:
        """Acquire slot. Returns False if rejected (queue full, account limit).
        RACE PROTECTION: Reserve per-account slot (increment _account_inflight) BEFORE awaiting 
        semaphore. If semaphore acquire fails/cancels → decrement in try/finally.
        Same pattern for _deep_active soft cap."""
        # Per-account: max 1 in-flight + 1 queued
        # FAST: never queues, if all 3 full → degrade to Tier 2
        # STANDARD/DEEP: share 7 slots, queue with round-robin, shed if >60s old
        # DEEP: soft cap 2 concurrent within shared pool; queue max 5, downgrade to STANDARD if full

    def release(self, account_id: str, urgency: str):
        """Release slot back to pool. Token-guarded: tracks per-acquire UUID in a set, 
        only calls sem.release() if token exists (prevents double-release inflating semaphore)."""

    @asynccontextmanager
    async def slot(self, account_id: str, urgency: str):
        """Context manager: acquire on entry, release on exit (even on exception). Use in _evaluate()."""

    # AC-003-4 burst behavior: "50 accounts <5s" applies to steady state.
    # Under burst (all 50 simultaneous): STANDARD queue wait > 5s → degrade to rule-based HOLD
    # immediately rather than queue for 30s. Deterministic fast degradation, not silent shedding.
```

### Task 2.3: AI Account Manager Service (Orchestrator)
**File:** `backend/services/ai_account_manager_service.py`
**Action:** Create class:
```python
class AIAccountManagerService:
    def __init__(self, accounts_service, close_positions_service,
                 ws_manager, ai_manager_repo, market_data_cache,
                 position_lock_registry, llm_scheduler):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._compiled_graph = None  # Set in start()
        self._account_locks: Dict[str, asyncio.Lock] = {}  # Per-account lock for enable/disable/restart lifecycle serialization

    async def start(self):
        """Compile LangGraph ONCE. Load enabled managers (stagger 5/s). Start health sweep."""
        self._compiled_graph = build_decision_graph().compile()
        # Query all enabled accounts, spawn staggered (5/second)
        # Start 30s health sweep loop

    async def shutdown(self):
        """Set cancel event on all tasks, await with 5s timeout, force-cancel survivors. Deregister all WS listeners."""

    async def _health_sweep(self):
        """Every 30s: check task.done(), detect orphans (heartbeat >120s), restart failed 
        (deregister old listener first, cleanup_account locks, then spawn new). Call lock_registry.evict_stale().
        Also: opportunistic DELETE FROM reauth_nonces WHERE expires_at < NOW() (app-layer fallback for pg_cron-free envs).
        Also: check hourly_reset_at — if > 1h old, reset actions_this_hour and set hourly_reset_at=NOW(); check counters_reset_at — if > 24h old, reset daily counters (actions_today, realized_loss_today, token_budget_used_today, equity_at_day_start) and set counters_reset_at=NOW().
        (App-layer fallback for all pg_cron counter reset jobs.)
        Also: ensure current-month and next-month partitions exist for ai_manager_decisions (prevents pg_cron SPOF)."""

    async def _startup_reconciliation(self):
        """On boot: load circuit breaker state from DB for each account (count, active, last_action_at).
        Scan for stranded decisions: rows with execution_result IS NULL AND created_at < NOW() - interval '2 min' → insert into ai_manager_failed_outcomes with failure_reason='crash_recovery'.
        All tasks start SLEEPING, position detection wakes them.
        Single-worker assertion: abort if multiple uvicorn workers detected."""

    async def enable(self, account_id: str, config: AIManagerConfig):
        """Acquires per-account lock (_account_locks[account_id]) before checking/mutating _tasks dict and WS listeners."""
    async def disable(self, account_id: str):
        """Acquires per-account lock. Cancel task, deregister WS listener, set state to sleeping."""
    async def pause(self, account_id: str, duration_hours: Optional[float]):
    async def resume(self, account_id: str):
    async def kill(self, account_id: str):
    async def global_kill(self):
    async def update_config(self, account_id: str, config: AIManagerConfig):
        """Validate, store, sync denormalized columns. Notify running task via reload_config() if active."""
    async def get_status(self, account_id: str) -> AIManagerStatus:

    @classmethod
    def create(cls, app_state) -> "AIAccountManagerService":
        """Factory for DI/testing."""
```

### Task 2.4: Per-Account Task (FSM Engine)
**File:** `backend/services/ai_manager_task.py`
**Action:** Create:
```python
class AIManagerTask:
    def __init__(self, account_id, service_refs, config, compiled_graph):
        self.state = "sleeping"
        self._cancel_event = asyncio.Event()

    async def run(self):
        """Main loop with heartbeat in ALL states (60s in SLEEPING, eval-cycle in others)."""
        # SLEEPING: 60s heartbeat-only loop, wait for position event
        # MONITORING: evaluation timer (relative, resets after completion per Amendment AC)
        # On urgent signal: immediate evaluation (respects 15s per-symbol cooldown)

    async def _on_ws_event(self, account_id: str, event_type: str, data: dict):
        """Filter by own account_id. Update latest-snapshot buffer."""

    async def _evaluate(self):
        """Run compiled graph with `await compiled_graph.ainvoke(state_dict)`. Uses scheduler.slot() context manager (try/finally release).
        All graph nodes MUST be async def. ainvoke() required for async node functions in asyncio context."""
        # Preflight → data_agg → signal_detect → [enrich] → action → validate → execute

    async def _execute_action(self, action: AIManagerAction):
        """Grace period → stale-price recheck → WAL audit → lock → execute → log."""
        # 1. If grace_period_s > 0: emit pending_action, wait, check cancel
        # 2. Re-validate stale price (Amendment C leverage-scaled threshold)
        # 3. WAL audit write (FAIL-CLOSED):
        #    - Attempt INSERT decision audit record
        #    - On failure: retry up to 3x with exponential backoff (100ms, 500ms, 2s)
        #    - If all 3 retries fail: DISCARD action (default HOLD), emit alert, return
        #    - NO execution proceeds without persisted audit record
        # 4. Acquire position lock via PositionLockRegistry (skip if held)
        # 5. Re-check kill switch (Amendment P — TOCTOU defense)
        # 6. Execute via ClosePositionsService
        # 7. UPDATE decision with execution_result (dead-letter on failure)

    def _check_urgent_signals(self, current, previous) -> Optional[str]:
        """PnL velocity >2%/30s, RSI divergence, funding flip, volatility spike."""

    async def _daily_loss_check(self, realized_loss: float):
        """Amendment G: if cumulative > max_daily_loss_pct → PAUSED."""
```

### Task 2.5: WS Event Integration
**In:** `ai_manager_task.py` + `ai_account_manager_service.py`
**Action:** Register ONE global listener on `AIAccountManagerService` (not per-task). Service maintains `Dict[str, AIManagerTask]` and dispatches to correct task via O(1) dict lookup by account_id. Callback signature matches existing API: `async def _on_ws_event(self, account_id: str, wallet_data: dict)`. Deregistration on shutdown/disable. Buffer pattern: latest-snapshot per account, PnL velocity computed on 1.5s debounce-fire only (Amendment W).

### Task 2.6: Circuit Breaker
**File:** `backend/services/ai_manager_circuit_breaker.py`
**Action:** Create per Amendment E (precise loss definition):
```python
class AIManagerCircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: int = 3600, repo=None):
        # repo injected for DB persistence of state changes
        ...
    async def record_outcome(self, account_id: str, realized_pnl: float, action_type: str):
        """Only FULL_CLOSE/PARTIAL_CLOSE with negative PnL (incl fees) count as loss.
        Persists updated count/active to DB via await repo.upsert_state() after every change."""
    def is_tripped(self, account_id: str) -> bool:
    async def check_cooldown(self, account_id: str) -> bool:
        """If cooldown elapsed → HALF_OPEN. Uses atomic DB CAS to allow exactly 1 action:
        UPDATE ai_manager_state SET circuit_breaker_half_open_used=TRUE 
        WHERE account_id=$1 AND circuit_breaker_active=TRUE AND circuit_breaker_half_open_used=FALSE
        RETURNING account_id. Only coroutine whose UPDATE returns a row proceeds."""
    async def reset(self, account_id: str):
        """Reset breaker to CLOSED. Persists via await repo.upsert_state(circuit_breaker_count=0, active=False, half_open_used=False)."""
```

### Task 2.7: Dead-Letter Retry Job
**In:** `ai_account_manager_service.py` (background loop)
**Action:** Every 60s, query `get_pending_retries()`, attempt outcome write, increment retry on failure, mark resolved after max retries (alert operator). Exponential backoff (30s, 60s, 120s, 240s, 480s).

### Task 2.8: Degradation Tier Manager
**File:** `backend/services/ai_manager_degradation.py`
**Action:** Create degradation state machine:
```python
class DegradationTierManager:
    """4 tiers: Nominal(0) → Degraded(1) → Conservative(2) → Safe(3).
    Scope: GLOBAL (LLM/exchange availability are system-wide signals, not per-account).
    Transitions: LLM timeout >15s → tier 1, LLM unavailable 10s → tier 2, exchange API down → tier 3.
    Recovery: 5min sustained health (hysteresis) → step down one tier.
    Per-tier behavior: tier 1 = skip DEEP, tier 2 = rule-based only, tier 3 = HOLD all.
    DB persistence: writes current tier to a single-row system_state or config, NOT per-account.
    CONCURRENCY: All state mutations guarded by asyncio.Lock (up to 50 tasks call check_health concurrently)."""
    
    def __init__(self):
        self._lock = asyncio.Lock()  # serializes all tier transitions and hysteresis counter updates

    async def check_health(self, event: str):
        """Called after LLM/exchange calls. event in ['success', 'timeout', 'unavailable', 'exchange_down'].
        Global scope — no account_id needed. Acquires self._lock before reading/writing tier or counter.
        Persists tier changes to ai_manager_global_state via async DB write."""
    
    def get_tier(self) -> int:
        """Returns current global degradation tier."""
    
    def should_use_llm(self, tier: int) -> bool:
```
Wired into `AIManagerTask._evaluate()` — check tier before LLM call.

### Task 2.9: Pattern Generation Scheduler
**In:** `ai_account_manager_service.py` (background loop started in `start()`)
**Action:** Every 24h, iterate all enabled accounts with jitter (hash(account_id) % 3600 seconds offset), call `memory.generate_patterns(account_id)` for each. Prevents thundering herd on DB.

---

## Phase 3: Decision Engine (LangGraph)

### Task 3.1: Decision Graph Definition
**File:** `backend/services/ai_manager_graph.py`
**Action:** Define LangGraph StateGraph compiled ONCE at service startup (Amendment AH):
```python
def build_decision_graph() -> StateGraph:
    graph = StateGraph(AIManagerGraphState)
    # REENTRANCE: CompiledGraph.ainvoke() with distinct state dicts is concurrency-safe for asyncio
    # (each invocation creates its own execution context; no shared mutable state between invocations).
    # Startup assertion: verify via 2 concurrent ainvoke() with different account states → no cross-contamination.
    graph.add_node("preflight", preflight_node)
    graph.add_node("data_aggregation", data_aggregation_node)
    graph.add_node("signal_detection", signal_detection_node)
    graph.add_node("context_enrichment", context_enrichment_node)
    graph.add_node("action_generation", action_generation_node)
    graph.add_node("risk_validation", risk_validation_node)
    graph.add_node("output", output_node)
    graph.add_node("error_fallback", error_fallback_node)
    # Conditional edges...
    return graph
```

Nodes:
- **preflight**: check circuit breaker, budget (atomic), kill switch, active cycle, cold-start rules (Amendment F: if <10 decisions → elevated thresholds)
- **data_aggregation**: fetch positions (3s cache), wallet, indicators (45s cache, force-refresh on urgent per Amendment AB), memory context (last 15 summarized per Amendment U), reconcile vs exchange (Amendment J)
- **signal_detection**: classify FAST/STANDARD/DEEP; cold-start accounts restricted to FAST/STANDARD only
- **context_enrichment**: (skip for FAST) multi-TF analysis, correlation, regime; 20s hard timeout (Amendment V)
- **action_generation**: LLM call via scheduler, structured output, temperature=0, 30s timeout; retry once on malformed, then HOLD
- **risk_validation**: loss cap (Amendment B), leverage-drift (Amendment C), position sanity, rate limit, locked_positions filter
- **output**: emit AIManagerAction or HOLD
- **error_fallback**: any node failure → HOLD, increment failure counter, log

### Task 3.2: LLM Prompt Assembly
**File:** `backend/services/ai_manager_prompts.py`
**Action:**
- `build_system_prompt()` → immutable system prompt (from spec Section 6)
- `build_context_prompt(positions, wallet, indicators, memory, patterns)` → user message
- `sanitize_for_injection(text)` → NFC-normalize, strip chars outside allowlist, block instruction-like sequences (Amendment O)
- `validate_regime(regime: str)` → must be in `["trending_up", "trending_down", "ranging", "volatile"]`; default "ranging" on invalid
- `validate_market_session(session: str)` → must be in `["asia", "europe", "us", "overlap"]`; default "unknown" on invalid
- `truncate_to_token_budget(prompt, max_tokens=4000)` → trimmed (Amendment U priority: oldest episodic → extra TFs → extra positions)
- Cold-start injection: "This is a new account with limited history. Be conservative." (Amendment F)
- Risk tolerance → parameter mapping (Amendment M table)
- Post-assembly: re-scan concatenated memory fields for instruction-like patterns
- `sanitize_llm_output(text)` → strip HTML/script tags from reasoning field before persistence (prevents stored XSS)

### Task 3.3: Memory System
**File:** `backend/services/ai_manager_memory.py`
**Action:**
```python
class AIManagerMemory:
    async def get_episodic_context(self, account_id, limit=15) -> List[dict]:
        """Summarized: action, symbol, confidence, outcome_label only (not full snapshot)."""

    async def get_semantic_patterns(self, account_id, limit=5) -> List[dict]:
        """Active patterns sorted by confidence, max 200 chars each."""

    async def record_decision(self, account_id, decision_data) -> tuple[int, datetime]:
        """Write-ahead audit. Returns (decision_id, decision_timestamp) for partition-aware outcome updates.
        Hash chain: HMAC-SHA256(settings.DECISION_CHAIN_HMAC_KEY, "|".join([prev_hash, str(id), account_id, timestamp.isoformat(), action_type, f"{confidence:.4f}"])).
        Field delimiter "|" prevents ambiguity from variable-length field concatenation.
        Genesis sentinel: GENESIS_PREV_HASH = "0" * 64 (used when prev_decision_hash IS NULL — first decision for account).
        Confidence serialized as fixed 4-decimal string to avoid float representation drift.
        Server-side key stored outside DB, rotated quarterly. chain_key_version tracks which key was used."""

    async def record_outcome(self, account_id, decision_id, decision_timestamp, outcome):
        """Link outcome. WHERE id=$1 AND timestamp=$2 for partition pruning. On DB failure → dead-letter table."""

    async def generate_patterns(self, account_id):
        """24h background job. Respects 50-pattern cap (deactivate lowest confidence if at limit).
        All LLM-generated pattern descriptions passed through sanitize_for_injection() then truncated to 200 chars before DB storage.
        Truncation order: sanitize → truncate[:200] (sanitize first to avoid re-expansion via normalization).
        DB constraint: CHECK (char_length(description) <= 200)."""
        # Uses pg advisory lock to prevent multi-instance execution
```

### Task 3.4: Signal Detection (Urgency Classifier)
**File:** `backend/services/ai_manager_evaluator.py`
**Action:** Lightweight non-LLM classifier:
- PnL velocity: >2% in 30s → FAST urgent
- RSI divergence: crosses 70/30 threshold → urgent
- Funding rate flip: sign changed → urgent
- Volatility spike: 1m candle body > 2x ATR → urgent
- Per-symbol urgent cooldown: 15s minimum between urgent triggers (Amendment AN R2 Fix 7)
- Otherwise: STANDARD (or DEEP if conflicting signals)

### Task 3.5: Daily Loss Enforcement
**In:** `ai_manager_task.py` (called after execution)
**Action:** After every AI-initiated close:
- Calculate realized PnL (incl fees 0.06% taker + funding)
- Call `record_realized_loss(account_id, loss_amount)`
- **equity_at_day_start NULL handling:** If NULL (after midnight reset, before first eval), fetch current equity from exchange and set atomically: `UPDATE ai_manager_state SET equity_at_day_start = $1 WHERE account_id = $2 AND equity_at_day_start IS NULL RETURNING account_id` (only first writer wins; concurrent attempts are no-ops). Never divide by NULL/zero.
- If cumulative > `max_daily_loss_pct * equity_at_day_start` → transition to PAUSED, discard pending, emit alert
- If `daily_profit_target_pct` set and cumulative realized profit ≥ target → transition to SLEEPING (target reached), emit `ai_manager.alert` with reason
- If daily_loss + unrealized > kill_switch_threshold → permanent disable

---

## Phase 4: API Endpoints + WebSocket Events

### Task 4.1: REST Router
**File:** `backend/routers/ai_manager.py`
**Action:** FastAPI router with all endpoints:
- `POST /accounts/{id}/ai-manager/enable` → 200 (idempotent, no 409)
- `POST /accounts/{id}/ai-manager/disable` → 200 (idempotent)
- `GET /accounts/{id}/ai-manager/status` → AIManagerStatus
- `PATCH /accounts/{id}/ai-manager/config` → PATCH semantics (Amendment AL)
- `POST /accounts/{id}/ai-manager/pause` → 200
- `POST /accounts/{id}/ai-manager/resume` → 200
- `POST /accounts/{id}/ai-manager/kill` → 200 (idempotent)
- `POST /accounts/{id}/ai-manager/kill/reset` → requires re-authentication middleware (`backend/middleware/reauth.py`): accepts `X-Reauth-Token` header with short-lived TOTP code only (no password hashes), validates against user's TOTP secret (stored encrypted via application-level AES-256-GCM encryption with KMS-held key in `users.totp_secret_enc BYTEA` column, decrypted at validation time only), single-use (replay protection via DB-stored nonce table `reauth_nonces(actor_user_id, nonce)` composite PK, TTL 5min, atomic INSERT...ON CONFLICT DO NOTHING RETURNING pattern), returns 401 on invalid/expired/replayed. Brute-force protection (3/hr, exponential lockout after 5 failures). All attempts (success+failure) logged to `security_events` table.
- `POST /accounts/{id}/ai-manager/cancel-pending` → cancel grace period action
- `POST /accounts/{id}/ai-manager/positions/{symbol}/lock` → lock position from AI
- `DELETE /accounts/{id}/ai-manager/positions/{symbol}/lock` → unlock
- `GET /accounts/{id}/ai-manager/decisions?limit=50&cursor=<id>&outcome=` → cursor-based pagination
- `GET /accounts/{id}/ai-manager/performance?period=7d` → metrics
- `POST /ai-manager/global-kill` → requires FastAPI dependency `require_operator_role` (checks JWT role claim) + MFA verification (same reauth middleware). Returns 403 if not operator, 401 if MFA invalid. All attempts logged to `security_events` table.

Auth: account ownership check on all per-account endpoints. Rate limits per Amendment N. Brute-force lockout counters derived from `security_events` table: (1) first check `SELECT MAX((detail->>'lockout_until')::timestamptz) FROM security_events WHERE actor_user_id=$1 AND event_type=$2 AND detail->>'lockout_until' IS NOT NULL` — if NOW() < that value → 401 with Retry-After header immediately; (2) then count `SELECT COUNT(*) FROM security_events WHERE actor_user_id=$1 AND event_type=$2 AND success=FALSE AND timestamp > NOW() - interval '1 hour'` — compute and write next lockout_until on new failures. Keyed on `(actor_user_id, endpoint)` — not per-IP. `detail` field in security_events MUST NOT contain raw TOTP values — only `{attempt_count, lockout_until, failure_reason_code}`.

**Rate limits (inline from Amendment N):**
| Category | Limit |
|----------|-------|
| Read endpoints (status, decisions, performance) | 60/min/user |
| State-changing (enable, disable, pause, resume, config) | 10/min/user, config 10/hr/account |
| Elevated-privilege (kill, kill/reset, global-kill) | 5/min/user + brute-force protection |

**Security events table** (in migration):
```sql
CREATE TABLE security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    account_id UUID,
    actor_user_id UUID NOT NULL,
    actor_ip INET,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    success BOOLEAN NOT NULL,
    detail JSONB
);
CREATE INDEX idx_security_events_type ON security_events(event_type, timestamp DESC);
CREATE INDEX idx_security_events_actor ON security_events(actor_user_id, timestamp DESC);
CREATE INDEX idx_security_events_bf ON security_events(actor_user_id, event_type, timestamp DESC) WHERE success = FALSE;
```

**Reauth nonces table** (in same migration):
```sql
CREATE TABLE reauth_nonces (
    actor_user_id UUID NOT NULL,
    nonce TEXT NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (actor_user_id, nonce)
);
CREATE INDEX idx_reauth_nonces_expires ON reauth_nonces(expires_at);
-- Nonce consumption MUST use atomic INSERT:
-- INSERT INTO reauth_nonces (actor_user_id, nonce, expires_at) VALUES ($1, $2, NOW() + interval '5 minutes')
-- ON CONFLICT (actor_user_id, nonce) DO NOTHING RETURNING nonce;
-- Zero rows returned = replay → 401. PK unique-violation from concurrent requests also maps to 401.
```

**Table 6 — ai_manager_global_state:** Defined in Phase 1 Task 1.1 (required by Phase 2 DegradationTierManager).

### Task 4.2: WebSocket Event Broadcasting
**In:** `ai_account_manager_service.py` / `ai_manager_task.py`
**Action:** Emit events (server-side filtered by account ownership).
**Payload spec:** All decision events serialize ONLY `AIManagerDecisionResponse` fields. NEVER include `state_snapshot`, `graph_path`, or raw `execution_result` internals in WS payloads.
Events:
- `ai_manager.state_change`
- `ai_manager.decision`
- `ai_manager.execution`
- `ai_manager.alert`
- `ai_manager.degradation`
- `ai_manager.pending_action` (grace period countdown)
- `ai_manager.health` (every 30s while active, stop when SLEEPING)

### Task 4.3: Service Wiring (main.py)
**File:** `backend/main.py` (modify)
**Action:**
- Instantiate PositionLockRegistry (shared singleton)
- Instantiate PriorityLLMScheduler
- Instantiate AIAccountManagerService with all deps
- Startup order: Database → AccountWSManager → CloseRuleEvaluator → AIAccountManagerService
- Call `ai_manager_service.start()` on startup
- Call `ai_manager_service.shutdown()` on shutdown (5s timeout)
- Register router: `app.include_router(ai_manager_router, prefix="/api/v1")`
- Wire PositionLockRegistry into CloseRuleEvaluator:
  - Modify `CloseRuleEvaluator.__init__` to accept `position_lock_registry: Optional[PositionLockRegistry] = None` (backward-compatible)
  - In CloseRuleEvaluator's close flow, call `registry.acquire(account_id, symbol, timeout=3.0)` before closing and `registry.release()` after
  - **On acquire() returning False:** ABORT the close for that symbol, log WARNING with account_id/symbol, emit `ai_manager.alert` event so operator is aware. Do NOT proceed with close (prevents double-close race).
  - Pass registry instance in main.py: `CloseRuleEvaluator(..., position_lock_registry=lock_registry)`

---

## Phase 5: Frontend Integration

### Task 5.1: Redux Slice
**File:** `frontend/src/store/aiManagerSlice.ts`
**Action:** State, thunks, WS handlers for all events. Cursor-based pagination for decisions.

### Task 5.2: AI Manager Card Component
**File:** `frontend/src/components/ai-manager/AIManagerCard.tsx`
**Action:** Per-account status card with animated state indicator, last decision, actions today, circuit breaker status. Enable/disable toggle, pause/kill buttons.

### Task 5.3: Decision Log Component
**File:** `frontend/src/components/ai-manager/DecisionLog.tsx`
**Action:** Chronological feed, expandable details, virtual scrolling, cursor-based load-more.

### Task 5.4: Config Panel Component
**File:** `frontend/src/components/ai-manager/ConfigPanel.tsx`
**Action:** Form with all config fields, validation per Amendment AK bounds, risk_tolerance presets, confirmation dialog. Position lock/unlock UI.

### Task 5.5: Performance Panel Component
**File:** `frontend/src/components/ai-manager/PerformancePanel.tsx`
**Action:** Metrics display, daily P&L chart (7d/30d), win rate, profit factor.

---

## Dependency Order

```
Phase 1 (DB + Models)
  → Phase 2 (Service + FSM + Lock Registry + Scheduler)
    → Phase 3 (Decision Engine + Memory + Prompts)
      → Phase 4 (API + Events + Wiring)
        → Phase 5 (Frontend)
```

Phase 4 Task 4.1 router stubs (returning 501) can start after Phase 2 for frontend unblocking.

---

## Test Strategy (TDD per phase)

### Phase 1 Tests:
- Migration up/down idempotency
- Partition creation and routing (initial 2 partitions exist, INSERT routes correctly)
- Schema validation (all Pydantic models with edge values)
- Repository: atomic counter increment (within budget → True, exceeded → False)
- Repository: hash chain integrity on sequential inserts
- Repository: hash chain concurrent insert serialization (2 concurrent insert_decision for same account → chain is linear, not forked)
- Repository: record_realized_loss atomic concurrent correctness (N concurrent calls summing to daily_limit+epsilon → limit fires exactly once)
- Repository: cursor-based pagination correctness
- Dead-letter: insert, retry, resolve lifecycle
- Dead-letter: max retries exhausted → resolved=TRUE + failure_reason + alert
- pg_cron logic testability: cron functions extracted as callable SQL, tested directly in CI without pg_cron extension
- pg_cron daily reset includes token_budget_used_today: (1) account at max token budget → reset → preflight budget check passes, (2) reset is idempotent
- Atomic counter concurrent correctness: N concurrent calls where budget=N-1 → exactly N-1 succeed (asyncio.gather against real DB)
- Application-level partition fallback: INSERT with future-month timestamp → partition auto-created, INSERT succeeds

### Phase 2 Tests:
- **FSM transitions:** all valid transitions, invalid transition rejection
- **Kill switch:** activation halts in-flight (AC-007-3), global kill (AC-007-4), kill at preflight (AC-004-5), re-check at execution (Amendment P)
- **Circuit breaker:** loss counting per Amendment E (fees inclusive, partial PnL, ADJUST never counts), CLOSED→OPEN→HALF_OPEN, cooldown auto-reset
- **Circuit breaker HALF_OPEN outcomes:** (1) allows exactly 1 action then blocks, (2) loss during HALF_OPEN → back to OPEN, (3) win during HALF_OPEN → RESET to CLOSED, (4) concurrent attempt during single-action window blocked
- **Circuit breaker rehydration:** restart with DB showing count=3 active=TRUE → breaker remains tripped post-restart, no actions allowed until cooldown
- **Position lock:** concurrent AI + CloseRuleEvaluator on same symbol (one wins, other skips with audit), TTL expiry, cleanup on sleep
- **LLM scheduler:** FAST gets slot when STANDARD full, 50 accounts under 5s latency, admission control, DEEP queue cap, round-robin fairness
- **LLM scheduler burst degradation:** all 50 accounts simultaneous → accounts beyond slot capacity degrade to rule-based HOLD within 5s (not queue for 30s)
- **WAL fail-closed:** DB write succeeds → execute, DB fails 3x → DISCARD + alert, no execution without audit
- **Health sweep:** detect dead tasks, restart orphans, heartbeat updates in SLEEPING
- **Shutdown:** 5s timeout, force-cancel, no leaked executions
- **Daily loss limit:** breach → PAUSED, escalation to kill, reset at 00:00 UTC
- **Daily loss — equity NULL atomic init:** (1) NULL at eval start → fetches exchange equity and sets atomically, (2) two concurrent evals with NULL → only one sets (CAS via WHERE IS NULL RETURNING), (3) exchange returns error during NULL fetch → enters Degraded tier, no ZeroDivisionError
- **Daily profit target → SLEEPING:** (1) profit reaches target → SLEEPING + alert emitted, (2) target=None → never fires, (3) profit target and loss limit both set — reaching profit takes precedence over continued evaluation
- **Hourly counter reset without pg_cron:** health sweep detects counters_reset_at > 1h old → resets actions_this_hour → subsequent increment_actions_atomic succeeds
- **Degradation tier rehydration:** restart with DB showing degradation_tier=2 → DegradationTierManager initializes at tier 2, skips LLM on first eval (rule-based path)
- **Degradation tiers:** Nominal→Degraded on LLM timeout >15s, Degraded→Conservative on LLM unavailable (10s), Conservative→Safe on exchange API down, recovery with hysteresis (5min sustained health), rule-based fallback behavior per tier
- **LLM scheduler fairness:** (1) 50 accounts contending — no account waits more than 2 consecutive rounds, (2) queue shedding at 60s discards + notifies, (3) DEEP-to-STANDARD downgrade when DEEP queue full, (4) per-account max 1 in-flight + 1 queued enforced
- **Position lock TOCTOU:** (1) urgent + timer evaluation arrive simultaneously for same account — only one proceeds, (2) user cancels grace period while lock being acquired, (3) lock TTL expiry mid-execution — post-TTL acquirer must re-verify position state
- **Kill switch TOCTOU:** (1) preflight passes → grace period → kill activated during grace → re-check catches it → blocked, (2) kill activated between re-check and exchange API call (narrow window — document as accepted residual risk)
- **Startup reconciliation:** (1) crash recovery — service starts with stale `fsm_state=MONITORING` in DB, verifies position still exists, resumes correctly; (2) duplicate task prevention — `start()` called twice for same account_id, second call is no-op; (3) stale fsm_state — DB says EXECUTING but no task running, health sweep detects and recovers; (4) stranded decisions — rows with execution_result IS NULL and created_at > 2min old → inserted into dead-letter on startup
- **WAL + lock interplay:** WAL audit write succeeds but position lock acquisition times out (another actor holds it) → decision_result={skipped: "lock_timeout"}, audit record marked accordingly, no execution attempted
- **equity_at_day_start NULL window:** (1) pg_cron resets counters at 00:00 UTC, first evaluation at 00:00:01 encounters NULL equity → fetches from exchange and sets; (2) exchange API fails during NULL equity fetch → enters Degraded tier, retries on next eval cycle
- **Single-worker assertion:** startup with WEB_CONCURRENCY>1 or --workers>1 → abort with clear error message
- **Dead-letter max retries exhausted:** after 5 failures, record marked resolved=TRUE with failure_reason, operator alert emitted exactly once
- **WS listener lifecycle:** disable → listener deregistered (no ghost callbacks), health-sweep restart → old listener removed before new registered
- **Config hot-reload:** PATCH config while task in MONITORING → task picks up new config on next eval cycle (via reload_config())
- **LLM scheduler slot leak:** exception during graph execution → slot released via context manager (verify semaphore count unchanged after N failed evals)
- **dry_run mode:** (1) dry_run=True → exchange call skipped, (2) decision still persisted with dry_run marker, (3) WS event emitted with {dry_run: true}, (4) toggle dry_run=False mid-operation → next eval executes real
- **Daily profit target:** (1) profit reaches target → SLEEPING, (2) target=None → no action, (3) target reached mid-grace-period → pending cancelled
- **Degradation tier transitions:** (1) Nominal→Degraded on LLM timeout >15s, (2) Degraded→Conservative on unavailable 10s, (3) Conservative→Safe on exchange down, (4) recovery hysteresis: 5min sustained → step down, (5) 4min50s health + brief failure → does NOT recover (window resets)
- **PositionLockRegistry evict_stale:** (1) idle >300s → evicted, (2) idle 299s → not evicted, (3) currently-held lock → NOT evicted, (4) after eviction → key re-acquirable
- **Dead-letter backoff intervals:** parameterized test for retry_count [0-4] → assert next_retry_at = now + [30, 60, 120, 240, 480]

### Phase 3 Tests:
- **Graph nodes:** each node unit tested:
  - preflight: rejects on kill/budget/circuit
  - data_agg: reconciles exchange state
  - signal_detection: classifies correctly
  - risk_validation: (1) aggregate loss below threshold passes, (2) at threshold passes, (3) above threshold REJECTED and logged, (4) locked position filtered out, (5) leverage-drift above threshold discards action, (6) actions_today >= max_daily_actions → REJECTED "daily_action_limit_reached", (7) actions_this_hour >= max_hourly_actions → REJECTED "hourly_action_limit_reached", (8) daily_loss + unrealized > kill_switch_threshold → permanent disable triggered
  - action_generation: structured output parsed correctly
  - output: emits correct AIManagerAction
  - error_fallback: any failure → HOLD + increment counter
- **LLM output symbol validation (Amendment AM):** (1) CLOSE for symbol in account positions → passes, (2) CLOSE for unknown symbol → rejected with reason, (3) mixed valid+hallucinated → hallucinated stripped, valid proceeds, (4) empty symbol field → rejected
- **LLM output sanitization:** reasoning with HTML/script tags → stripped before persistence
- **excluded_symbols filtering:** (1) symbol in excluded_symbols → filtered before action_generation, (2) symbol in both excluded and locked → filtered (no error), (3) PATCH excluded_symbols → respected on next eval
- **generate_patterns advisory lock:** (1) concurrent call blocked when lock held, (2) exits cleanly (not errors), (3) exception mid-run → lock released
- **generate_patterns description truncation:** (1) LLM returns 201-char description → stored as 200 chars, (2) sanitize_for_injection called before truncation, (3) advisory lock released even when truncation needed
- **TP/SL price sanity:** (1) TP/SL within 50% of market price → passes, (2) TP/SL >50% deviation → rejected with reason
- **LLM malformed retry:** (1) first malformed + second malformed → HOLD emitted (not error_fallback), decision persisted with reason; (2) first malformed + second valid → action proceeds from second response
- **PnL velocity 1.5s debounce (Amendment W):** two WS events 0.5s apart → _check_urgent_signals called once; two events 2.0s apart → called twice
- **validate_regime/validate_market_session:** (1) "bull" → "ranging", (2) "trending_up" → passthrough, (3) "US" → "unknown", (4) "europe" → passthrough
- **Graph reentrance:** 2 concurrent ainvoke() with different account states → no cross-contamination of action outputs
- **Cold-start:** <10 decisions → 0.85 threshold, no DEEP, conservative prompt
- **Prompt assembly:** token budget respected (4000 max), truncation order correct, sanitization blocks injection patterns
- **Memory:** hash chain computation, episodic summary (not full snapshot), pattern cap (50), invalidation at confidence <0.4
- **Urgency:** PnL velocity detection, RSI divergence, funding flip, 15s per-symbol cooldown:
  (1) PnL velocity at exactly 2%/30s boundary → triggers urgent; (2) two urgent signals for same symbol within 15s → second suppressed; (3) urgent signal while eval in-flight → queued (not dropped); (4) cooldown expires after 15s → next signal proceeds
- **Grace period:** emit pending_action, cancel prevents execution, stale-price recheck after expiry (Amendment C)
- **Context enrichment timeout:** (1) completes in <20s → proceeds; (2) exceeds 20s → proceeds to action_generation with regime marked "unavailable" (not error_fallback); (3) partial enrichment on timeout marked clearly in prompt
- **Reconciliation:** exchange truth overrides stale working memory (Amendment J)
- **Prompt injection adversarial:** (1) Unicode homoglyphs in symbol name (e.g. Cyrillic "а" vs Latin "a") are normalized before injection; (2) split injection across multiple memory entries (partial system prompt override spread across episodic memories) is blocked by per-entry sanitization; (3) `\n\nSystem:` override attempt in position notes is stripped; (4) oversized input (>4000 tokens) is truncated per priority order, not rejected
- **Hash chain verification:** (1) first decision for account uses GENESIS_PREV_HASH ("0"*64) as prev_hash input; (2) sequential inserts produce valid chain (hash_n = HMAC-SHA256(KEY, "|".join([prev_hash, id, account, timestamp, action, confidence]))); (3) tampered record detected (modify one record, verify chain breaks on next read — recomputation without key fails); (3) chain spans partition boundaries correctly (first record of new partition references last record of previous); (4) broken chain triggers alert + blocks new writes until operator resolves; (5) key version column ensures old records verify against their original key after rotation

### Phase 4 Tests:
- All endpoints happy path + error cases + auth ownership
- Idempotency: double-enable returns 200 (not 409)
- PATCH config: omit=keep (field not in model_fields_set), null=reset, array=replace, present value=update
- PATCH config bounds validation: (1) max_daily_actions=-1 → 422, (2) max_daily_actions above upper bound → 422, (3) invalid risk_tolerance string → 422, (4) confidence outside [0.3, 0.95] → 422
- Kill/reset re-auth: (1) missing X-Reauth-Token → 401, (2) wrong credential → 401, (3) valid credential → proceeds, (4) replay (reused nonce) → 401, (5) brute-force protection (3/hr, lockout after 5 failures)
- Global kill auth: (1) non-operator role → 403, (2) operator without MFA → 401, (3) operator + valid MFA → 200, (4) expired MFA token → 401
- Global kill integration: N enabled accounts → POST global-kill → all kill_switch_active=TRUE, all tasks stopped, N state_change WS events emitted
- Cancel-pending: (1) active grace period → cancelled + 200, (2) no pending action → 200 with {cancelled: false}, (3) non-owner → 403, (4) cancel simultaneous with execution → deterministic response code
- Position lock/unlock: (1) lock symbol → AI skips it, (2) duplicate lock → 200 (idempotent), (3) unlock re-enables, (4) lock symbol not in positions → 404
- Cursor pagination: correct ordering, boundary conditions, composite keyset decoding
- WS events: server-side account ownership filtering
- WS payload sanitization: ai_manager.decision event does NOT contain state_snapshot, graph_path, or execution_result keys (all 6 event types verified)
- Performance endpoint: (1) period=7d returns correct window, (2) period=30d, (3) no decisions → zeroed metrics, (4) invalid period → 422
- Security events: kill/reset attempt creates audit record (success and failure)
- Security events detail sanitization: after kill/reset attempt, detail JSONB contains only {attempt_count, lockout_until, failure_reason_code} — no raw TOTP values
- Brute-force lockout_until enforcement: (1) lockout_until in future → 401 with Retry-After, (2) lockout_until in past + count below threshold → proceeds
- CloseRuleEvaluator backward compat: registry=None → close flow works without error (no regression)
- Rate limit enforcement: (1) 61st read in 1min → 429, (2) 11th config PATCH in 1hr → 429, (3) 6th elevated call in 1min → 429, (4) window expiry → next call allowed
- Double-enable idempotency: enable twice → assert exactly one WS entry in task dict, one listener registration
- Concurrent enable+disable race: enable and disable for same account_id fired concurrently → after both complete, account is deterministic (fully enabled or fully disabled), no ghost tasks or orphaned WS listeners
- Cursor auth isolation: user A cursor submitted to user B's decisions → returns 0 rows; malformed cursor → 422

### Phase 5 Tests:
- Component render tests (status states, decision log entries)
- Redux slice: state transitions, thunk error handling
- WS event handling: state_change updates UI, pending_action shows countdown
- ConfigPanel: (1) renders all fields, (2) valid submit, (3) out-of-bounds values show validation error, (4) null reset clears field
- PerformancePanel: (1) renders with data, (2) empty state, (3) period selector switches data
