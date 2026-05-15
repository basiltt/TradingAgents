# Phase 1: Database Migration

## Goal
Add migration #25 to both `async_persistence.py` and `persistence.py` containing the full DDL for `trades` and `trade_events` tables, all indexes, triggers, and constraints.

## Entry Criteria
- Baseline tests pass
- No pending migrations

## Files to Modify
- `backend/async_persistence.py` — add `_SCHEMA_V25` constant and `(25, _SCHEMA_V25)` to `_MIGRATIONS`
- `backend/persistence.py` — add identical migration

## Tasks

### TASK-001: Define migration DDL constant
**Requirement IDs:** FR-035, FR-050, NFR-012, NFR-013, NFR-014
**File:** `backend/async_persistence.py`
**Action:** Add `_SCHEMA_V25` string constant before the `_MIGRATIONS` list (after line ~48)

```python
_SCHEMA_V25 = """
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE RESTRICT,
    symbol VARCHAR(30) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('Buy', 'Sell')),
    order_type VARCHAR(10) NOT NULL DEFAULT 'market' CHECK (order_type IN ('market', 'limit')),
    qty NUMERIC(20,8) NOT NULL,
    filled_qty NUMERIC(20,8),
    entry_price NUMERIC(20,8),
    avg_fill_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    stop_loss_price NUMERIC(20,8),
    take_profit_price NUMERIC(20,8),
    leverage INTEGER NOT NULL DEFAULT 1,
    margin_mode VARCHAR(10) DEFAULT 'isolated' CHECK (margin_mode IN ('cross', 'isolated')),
    position_idx INTEGER NOT NULL DEFAULT 0,
    mark_price_at_open NUMERIC(20,8),
    capital_pct NUMERIC(8,4),
    base_capital NUMERIC(20,8),
    signal_direction VARCHAR(4) CHECK (signal_direction IN ('buy', 'sell')),
    trade_direction VARCHAR(8) CHECK (trade_direction IN ('straight', 'reverse')),
    take_profit_pct NUMERIC(8,4),
    stop_loss_pct NUMERIC(8,4),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'open', 'partially_filled', 'closing', 'partially_closed', 'closed', 'failed', 'cancelled')),
    order_id VARCHAR(50),
    order_link_id VARCHAR(50),
    close_reason VARCHAR(20)
        CHECK (close_reason IN ('take_profit', 'stop_loss', 'manual_single', 'manual_close_all',
               'rule_triggered', 'cycle_target', 'cycle_drawdown', 'external', 'liquidation', 'adl')),
    close_rule_id UUID REFERENCES close_rules(id) ON DELETE SET NULL,
    parent_trade_id UUID REFERENCES trades(id) ON DELETE RESTRICT,
    realized_pnl NUMERIC(20,8),
    realized_pnl_pct NUMERIC(12,4),
    fees NUMERIC(20,8) DEFAULT 0,
    net_pnl NUMERIC(20,8),
    source VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'cycle')),
    source_id INTEGER REFERENCES trading_cycles(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}' CHECK (octet_length(metadata::text) < 8192),
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_source_id CHECK (
        (source = 'cycle' AND source_id IS NOT NULL) OR
        (source = 'manual' AND source_id IS NULL)
    )
);

CREATE INDEX idx_trades_account_status_created ON trades(account_id, status, created_at DESC, id DESC);
CREATE INDEX idx_trades_account_created ON trades(account_id, created_at DESC, id DESC);
CREATE INDEX idx_trades_account_opened ON trades(account_id, opened_at DESC, id DESC);
CREATE INDEX idx_trades_account_closed ON trades(account_id, closed_at DESC NULLS LAST, id DESC);
CREATE INDEX idx_trades_account_pnl ON trades(account_id, realized_pnl DESC NULLS LAST, id DESC);
CREATE INDEX idx_trades_account_symbol ON trades(account_id, symbol, created_at DESC, id DESC);
CREATE INDEX idx_trades_order_id ON trades(order_id) WHERE order_id IS NOT NULL;
CREATE INDEX idx_trades_active ON trades(account_id) WHERE status IN ('open', 'partially_filled', 'closing', 'partially_closed');
CREATE INDEX idx_trades_source ON trades(source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX idx_trades_parent ON trades(parent_trade_id) WHERE parent_trade_id IS NOT NULL;
CREATE UNIQUE INDEX idx_trades_order_link_id ON trades(order_link_id) WHERE order_link_id IS NOT NULL;
CREATE INDEX idx_trades_archived ON trades(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX idx_trades_pending_orphan ON trades(created_at) WHERE status = 'pending' AND order_id IS NULL;

CREATE OR REPLACE FUNCTION update_trades_updated_at() RETURNS TRIGGER AS $t$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$t$ LANGUAGE plpgsql;
CREATE TRIGGER trg_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_trades_updated_at();

CREATE TABLE IF NOT EXISTS trade_events (
    id BIGSERIAL PRIMARY KEY,
    trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE RESTRICT,
    event_type VARCHAR(30) NOT NULL
        CHECK (event_type IN ('placed', 'filled', 'partially_filled', 'tp_triggered', 'sl_triggered',
               'close_requested', 'closed', 'failed', 'cancelled', 'amended', 'reconciled')),
    old_status VARCHAR(20) CHECK (old_status IS NULL OR old_status IN ('pending','open','partially_filled','closing','partially_closed','closed','failed','cancelled')),
    new_status VARCHAR(20) CHECK (new_status IS NULL OR new_status IN ('pending','open','partially_filled','closing','partially_closed','closed','failed','cancelled')),
    fill_qty NUMERIC(20,8),
    fill_price NUMERIC(20,8),
    actor VARCHAR(20) NOT NULL DEFAULT 'system'
        CHECK (actor IN ('system', 'user', 'rule_engine', 'cycle_engine', 'reconciliation', 'exchange')),
    payload JSONB DEFAULT '{}' CHECK (octet_length(payload::text) < 8192),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_events_trade_id ON trade_events(trade_id, created_at);

CREATE OR REPLACE FUNCTION prevent_trade_events_mutation() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'trade_events: UPDATE is prohibited';
    END IF;
    IF TG_OP = 'DELETE' AND current_setting('app.purge_mode', 'false') <> 'true' THEN
        RAISE EXCEPTION 'trade_events: DELETE requires purge_mode';
    END IF;
    RETURN OLD;
END;
$t$ LANGUAGE plpgsql;
CREATE TRIGGER trg_trade_events_immutable BEFORE UPDATE OR DELETE ON trade_events
    FOR EACH ROW EXECUTE FUNCTION prevent_trade_events_mutation()
""".strip()
```

**Important note on dollar quoting:** The existing migrations use `"""..."""` Python strings. PostgreSQL `$$` delimiters inside Python triple-quoted strings work fine. However, the migration runner splits on `;` — so trigger functions that contain `;` inside the function body MUST use `$t$` (or similar) delimiters instead of `$$`, and the entire migration must be executed as a single `conn.execute(sql)` call rather than split on `;`.

**CRITICAL:** The existing migration runner (line 393-396) splits SQL on `;` and executes each statement separately. Trigger function bodies contain internal `;` which would break the split. Two options:
1. Use `$t$` delimiters and handle the split — but the runner would still break on `;` inside `$t$...$t$`
2. **Better:** Execute migration 25 as a single `conn.execute()` call without splitting

Since the runner splits on `;`, we need to either:
- Modify the runner to handle dollar-quoted blocks (risky — touches all migrations)
- OR: Split migration 25 into separate entries (25 for tables+indexes, 26 for trigger functions) where each entry is `;`-safe

**Decision:** Use two migrations: 25 for tables+indexes (`;`-safe), 26 for trigger functions (executed without `;`-split). See TASK-002.

### TASK-002: Split migration into `;`-safe parts
**File:** `backend/async_persistence.py`

Actually, reviewing the runner more carefully — it uses `conn.transaction()` per migration and splits on `;`. The trigger CREATE statements contain `;` inside function bodies. The cleanest fix:

**Approach:** Add migration 25 for CREATE TABLE + indexes (all `;`-splittable), and migration 26 for the trigger functions using a raw execute approach. However, since we can't change the runner, we need to avoid `;` inside function bodies.

**Alternative approach:** Use single-line trigger functions (no internal `;`):
```sql
CREATE OR REPLACE FUNCTION update_trades_updated_at() RETURNS TRIGGER AS $t$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END $t$ LANGUAGE plpgsql
```
This works because `BEGIN ... END` without a trailing `;` before `$t$` is valid in PostgreSQL's function body.

Wait — the existing code at line 49 uses `_SCHEMA_V1` which contains full CREATE TABLE statements with `;` separators, and the runner splits on `;`. So `;` inside CHECK constraints etc. are fine since they don't contain actual `;`. The problem is ONLY the trigger function bodies.

**Final decision:** Split into:
- `_SCHEMA_V25_TABLES` — CREATE TABLE + indexes (`;`-separated, safe for runner)
- `_SCHEMA_V25_TRIGGERS` — Trigger functions (single statements, no internal `;` by using single-line syntax)

Use migrations (25, tables) and (26, triggers).

### TASK-003: Add migration entries to _MIGRATIONS list
**File:** `backend/async_persistence.py`
**Action:** Add to `_MIGRATIONS` list (after line 314):

```python
    (25, _SCHEMA_V25_TABLES),
    (26, _SCHEMA_V25_TRIGGERS),
]
```

The `_SCHEMA_V25_TABLES` constant contains:
- CREATE TABLE trades (full DDL, no triggers)
- All 13 indexes
- CREATE TABLE trade_events (full DDL)
- 1 index on trade_events

The `_SCHEMA_V25_TRIGGERS` constant is a Python callable (not a string) because the `prevent_trade_events_mutation()` function body contains internal `;` which the runner's `sql.split(";")` would break on. The runner must be updated to support callable migrations.

**Runner modification (line ~393 of async_persistence.py):**
```python
# Before:
for version, sql in _MIGRATIONS:
    ...
    for stmt in sql.split(";"):
        ...

# After:
for version, sql in _MIGRATIONS:
    ...
    if callable(sql):
        await sql(conn)
    else:
        for stmt in sql.split(";"):
            ...
```

**Same change in persistence.py** (sync version uses `cursor.execute`):
```python
if callable(sql):
    sql(cursor)
else:
    for stmt in sql.split(";"):
        ...
```

**Migration 26 as callable:**
```python
async def _schema_v26_triggers(conn):
    await conn.execute("""
        CREATE OR REPLACE FUNCTION update_trades_updated_at() RETURNS TRIGGER AS $t$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $t$ LANGUAGE plpgsql
    """)
    await conn.execute("""
        CREATE TRIGGER trg_trades_updated_at BEFORE UPDATE ON trades
        FOR EACH ROW EXECUTE FUNCTION update_trades_updated_at()
    """)
    await conn.execute("""
        CREATE OR REPLACE FUNCTION prevent_trade_events_mutation() RETURNS TRIGGER AS $t$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'trade_events: UPDATE is prohibited';
            END IF;
            IF TG_OP = 'DELETE' AND current_setting('app.purge_mode', 'false') <> 'true' THEN
                RAISE EXCEPTION 'trade_events: DELETE requires purge_mode';
            END IF;
            RETURN OLD;
        END;
        $t$ LANGUAGE plpgsql
    """)
    await conn.execute("""
        CREATE TRIGGER trg_trade_events_immutable BEFORE UPDATE OR DELETE ON trade_events
        FOR EACH ROW EXECUTE FUNCTION prevent_trade_events_mutation()
    """)

def _schema_v26_triggers_sync(cursor):
    # Same statements using cursor.execute() for sync persistence
    cursor.execute("CREATE OR REPLACE FUNCTION update_trades_updated_at() ...")
    cursor.execute("CREATE TRIGGER trg_trades_updated_at ...")
    cursor.execute("CREATE OR REPLACE FUNCTION prevent_trade_events_mutation() ...")
    cursor.execute("CREATE TRIGGER trg_trade_events_immutable ...")
```

**Migration entries:**
```python
    (25, _SCHEMA_V25_TABLES),
    (26, _schema_v26_triggers),  # callable, not string
]
```

### TASK-004: Add identical migrations to persistence.py
**Requirement IDs:** Same as TASK-001/003
**File:** `backend/persistence.py`
**Action:** Add the same `_SCHEMA_V25_TABLES` and `_SCHEMA_V25_TRIGGERS` constants and migration entries.

Find the `_MIGRATIONS` list in `persistence.py` and verify it also uses the `;`-split runner pattern. Add identical entries. The DDL must be byte-identical between both files.

**Implementation:** Define the constants in a shared location OR copy them. Since existing code copies, follow that pattern — copy the constants.

### TASK-005: Write migration tests
**File:** `tests/test_trade_migration.py`
**Tests:**
1. `test_migration_25_creates_trades_table` — Run migrations, verify `trades` table exists with expected columns
2. `test_migration_25_creates_trade_events_table` — Verify `trade_events` table exists
3. `test_migration_25_indexes_exist` — Query `pg_indexes` for all 14 indexes
4. `test_migration_26_triggers_exist` — Query `pg_trigger` for both triggers
5. `test_trade_events_immutability` — Insert a trade_event, try UPDATE → expect exception. Try DELETE without purge_mode → expect exception.
6. `test_trade_events_purge_mode_delete` — SET app.purge_mode = 'true', DELETE → succeeds
7. `test_trades_updated_at_trigger` — Insert trade, UPDATE, verify updated_at changed
8. `test_trades_check_constraints` — Insert with invalid status → expect constraint violation
9. `test_trades_fk_constraints` — Insert with non-existent account_id → expect FK violation
10. `test_close_rules_id_type_compatible` — Verify close_rules.id column type matches trades.close_rule_id (both UUID). If close_rules.id is INTEGER, the trades DDL must be adjusted before migration runs.

## Exit Criteria
- Both persistence files have migration 25+26
- All migration tests pass
- Existing tests still pass
- Tables, indexes, triggers verified via tests

## Verification Commands
```bash
python -m pytest tests/test_trade_migration.py -x -q --tb=short
python -m pytest tests/ -x -q --tb=short  # regression
```

## Rollback
```sql
DROP TRIGGER IF EXISTS trg_trade_events_immutable ON trade_events;
DROP FUNCTION IF EXISTS prevent_trade_events_mutation();
DROP TRIGGER IF EXISTS trg_trades_updated_at ON trades;
DROP FUNCTION IF EXISTS update_trades_updated_at();
DROP TABLE IF EXISTS trade_events;
DROP TABLE IF EXISTS trades;
```

## Traceability
| Task | FRs | NFRs | ACs |
|------|-----|------|-----|
| TASK-001/002/003 | FR-035, FR-050 | NFR-012, NFR-013, NFR-014 | AC-015 |
| TASK-004 | Same | Same | Same |
| TASK-005 | FR-035, FR-050 | NFR-012 | AC-015 |
