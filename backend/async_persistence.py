"""Async PostgreSQL persistence layer using asyncpg with connection pooling."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import asyncpg

logger = logging.getLogger(__name__)

# ── Schema & Migrations (identical to persistence.py) ──────────────────

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed','cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL CHECK(started_at ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}'),
    completed_at TEXT CHECK(completed_at IS NULL OR completed_at ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}'),
    error TEXT,
    instance_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON analysis_runs(ticker, analysis_date);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON analysis_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS report_sections (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, section)
);

CREATE INDEX IF NOT EXISTS idx_reports_run_id ON report_sections(run_id)
""".strip()

_SCHEMA_V25_TABLES = """
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
    source VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'cycle', 'scanner')),
    source_id INTEGER REFERENCES trading_cycles(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}' CHECK (octet_length(metadata::text) < 8192),
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_source_id CHECK (
        (source = 'cycle' AND source_id IS NOT NULL) OR
        (source = 'manual' AND source_id IS NULL) OR
        (source = 'scanner')
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
CREATE INDEX idx_trade_events_trade_id ON trade_events(trade_id, created_at)
""".strip()


async def _schema_v26_triggers(conn) -> None:
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


_MigrationSQL = Union[str, Callable[[Any], Coroutine[Any, Any, None]]]


async def _fix_source_constraint(conn) -> None:
    """Drop all CHECK constraints on trades.source column and re-add with correct values."""
    rows = await conn.fetch("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute att ON att.attnum = ANY(con.conkey) AND att.attrelid = con.conrelid
        WHERE con.conrelid = 'trades'::regclass
          AND att.attname = 'source'
          AND con.contype = 'c'
          AND con.conname != 'chk_source_id'
    """)
    for row in rows:
        await conn.execute(f'ALTER TABLE trades DROP CONSTRAINT {row["conname"]}')
    await conn.execute(
        "ALTER TABLE trades ADD CONSTRAINT trades_source_check "
        "CHECK (source IN ('manual', 'cycle', 'scanner'))"
    )


async def _fix_close_rules_constraints(conn) -> None:
    # 1. Find and drop existing check constraints on close_rules.trigger_type
    rows = await conn.fetch("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute att ON att.attnum = ANY(con.conkey) AND att.attrelid = con.conrelid
        WHERE con.conrelid = 'close_rules'::regclass
          AND att.attname = 'trigger_type'
          AND con.contype = 'c'
    """)
    for row in rows:
        await conn.execute(f'ALTER TABLE close_rules DROP CONSTRAINT {row["conname"]}')
    
    # 2. Add new check constraint allowing BREAKEVEN_TIMEOUT and MAX_DURATION
    await conn.execute("""
        ALTER TABLE close_rules ADD CONSTRAINT close_rules_trigger_type_check
        CHECK (trigger_type IN (
            'BALANCE_BELOW', 'BALANCE_ABOVE',
            'EQUITY_DROP_PCT', 'EQUITY_RISE_PCT',
            'PNL_BELOW', 'PNL_ABOVE',
            'BREAKEVEN_TIMEOUT', 'MAX_DURATION'
        ))
    """)

    # 3. Alter reference_value column to VARCHAR(100)
    await conn.execute("ALTER TABLE close_rules ALTER COLUMN reference_value TYPE VARCHAR(100)")


async def _add_ai_manager_tables(conn) -> None:
    """Migration 33: AI Account Manager tables."""
    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_state (
    account_id TEXT PRIMARY KEY REFERENCES trading_accounts(id),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    fsm_state TEXT NOT NULL DEFAULT 'sleeping',
    config JSONB NOT NULL DEFAULT '{}',
    circuit_breaker_count INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_active BOOLEAN NOT NULL DEFAULT FALSE,
    circuit_breaker_half_open_used BOOLEAN NOT NULL DEFAULT FALSE,
    actions_today INTEGER NOT NULL DEFAULT 0,
    actions_this_hour INTEGER NOT NULL DEFAULT 0,
    max_daily_actions INTEGER NOT NULL DEFAULT 30,
    max_hourly_actions INTEGER NOT NULL DEFAULT 10,
    equity_at_day_start NUMERIC(18,8),
    realized_loss_today NUMERIC(18,8) NOT NULL DEFAULT 0,
    realized_profit_today NUMERIC(18,8) NOT NULL DEFAULT 0,
    token_budget_used_today INTEGER NOT NULL DEFAULT 0,
    last_analysis_at TIMESTAMPTZ,
    last_action_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    counters_reset_at TIMESTAMPTZ,
    hourly_reset_at TIMESTAMPTZ,
    kill_switch_active BOOLEAN NOT NULL DEFAULT FALSE,
    strategy_version TEXT DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_fsm_state CHECK (fsm_state IN ('sleeping','monitoring','analyzing','executing','paused','error'))
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_state_orphan ON ai_manager_state (fsm_state, heartbeat_at) WHERE fsm_state NOT IN ('sleeping')
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_state_enabled ON ai_manager_state (enabled) WHERE enabled = TRUE
    """)

    # Emergency close state persistence (added for restart recovery)
    await conn.execute("ALTER TABLE ai_manager_state ADD COLUMN IF NOT EXISTS emergency_ref_equity NUMERIC(18,8)")
    await conn.execute("ALTER TABLE ai_manager_state ADD COLUMN IF NOT EXISTS emergency_cooldown_until TIMESTAMPTZ")
    await conn.execute("ALTER TABLE ai_manager_state ADD COLUMN IF NOT EXISTS emergency_closed_symbols JSONB DEFAULT '{}'")

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_decisions (
    id BIGSERIAL,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
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
) PARTITION BY RANGE (timestamp)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_decisions_account ON ai_manager_decisions(account_id, timestamp DESC) INCLUDE (action_taken, confidence, outcome_label, execution_result)
    """)
    await conn.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_decisions_hash ON ai_manager_decisions(account_id, decision_hash, timestamp)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_decisions_outcome ON ai_manager_decisions(account_id, outcome_label, timestamp DESC)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_decisions_stranded ON ai_manager_decisions(created_at) WHERE execution_result IS NULL
    """)

    # Create default partition to catch any edge cases
    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_decisions_default PARTITION OF ai_manager_decisions DEFAULT
    """)

    # Create current month and next month partitions
    await conn.execute("""
DO $$ BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS ai_manager_decisions_%s PARTITION OF ai_manager_decisions FOR VALUES FROM (%L) TO (%L)',
        to_char(date_trunc('month', NOW()), 'YYYY_MM'),
        date_trunc('month', NOW()),
        date_trunc('month', NOW()) + interval '1 month'
    );
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS ai_manager_decisions_%s PARTITION OF ai_manager_decisions FOR VALUES FROM (%L) TO (%L)',
        to_char(date_trunc('month', NOW()) + interval '1 month', 'YYYY_MM'),
        date_trunc('month', NOW()) + interval '1 month',
        date_trunc('month', NOW()) + interval '2 months'
    );
END $$
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_patterns (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
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
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_patterns_account ON ai_manager_patterns(account_id, active, confidence DESC)
    """)
    await conn.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_patterns_natural_key ON ai_manager_patterns(account_id, pattern_type, COALESCE(symbol, '')) WHERE active = TRUE
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_failed_outcomes (
    id BIGSERIAL PRIMARY KEY,
    decision_id BIGINT NOT NULL,
    decision_timestamp TIMESTAMPTZ NOT NULL,
    execution_result JSONB NOT NULL,
    failure_reason TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    next_retry_at TIMESTAMPTZ,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_failed_outcomes_retry ON ai_manager_failed_outcomes(resolved, next_retry_at) WHERE resolved = FALSE
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_global_state (
    key TEXT PRIMARY KEY,
    int_value INTEGER,
    text_value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
    """)
    await conn.execute("""
INSERT INTO ai_manager_global_state (key, int_value) VALUES ('degradation_tier', 0) ON CONFLICT (key) DO NOTHING
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_logs (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL DEFAULT 'general',
    message TEXT NOT NULL,
    details JSONB,
    CONSTRAINT chk_log_level CHECK (level IN ('debug','info','warning','error','critical'))
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_logs_account_ts ON ai_manager_logs(account_id, timestamp DESC)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_ai_logs_level ON ai_manager_logs(account_id, level, timestamp DESC)
    """)

    # --- Enhanced AI Manager tables ---
    await conn.execute(
        "ALTER TABLE ai_manager_state ADD COLUMN IF NOT EXISTS sweep_state JSONB DEFAULT '{}'"
    )

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_regime_history (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    symbol TEXT NOT NULL,
    regime TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    detail JSONB NOT NULL,
    duration_s INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_regime_history_lookup
    ON ai_manager_regime_history(account_id, symbol, created_at DESC)
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_correlation_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    portfolio_heat FLOAT NOT NULL,
    matrix JSONB NOT NULL,
    clusters JSONB NOT NULL,
    position_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_correlation_snapshots_lookup
    ON ai_manager_correlation_snapshots(account_id, created_at DESC)
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_sweep_events (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    direction TEXT NOT NULL,
    swept_level NUMERIC(18,8),
    original_sl NUMERIC(18,8),
    defense_action TEXT,
    recovery_price NUMERIC(18,8),
    duration_ms INTEGER,
    outcome TEXT,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_sweep_events_lookup
    ON ai_manager_sweep_events(account_id, symbol, created_at DESC)
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_orderbook_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    symbol TEXT NOT NULL,
    imbalance_ratio FLOAT NOT NULL,
    spread_bps FLOAT NOT NULL,
    depth_ratio FLOAT NOT NULL,
    bid_clusters JSONB NOT NULL,
    ask_clusters JSONB NOT NULL,
    spoofing_flags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_lookup
    ON ai_manager_orderbook_snapshots(account_id, symbol, created_at DESC)
    """)

    # --- AI Manager Dashboard Enhancement tables ---
    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_llm_calls (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    call_id UUID NOT NULL,
    evaluation_cycle_id UUID NOT NULL,
    node_name TEXT NOT NULL DEFAULT 'action_generation',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    urgency_tier TEXT NOT NULL,
    action_returned TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    reasoning_preview TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_llm_calls_account_time
    ON ai_manager_llm_calls(account_id, timestamp DESC, id)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_llm_calls_cycle
    ON ai_manager_llm_calls(evaluation_cycle_id)
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS ai_manager_market_commentary (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    commentary_type TEXT NOT NULL CHECK (commentary_type IN ('template', 'llm')),
    regime_label TEXT NOT NULL,
    day_score INTEGER CHECK (day_score IS NULL OR (day_score >= 0 AND day_score <= 100)),
    day_score_label TEXT CHECK (day_score_label IS NULL OR day_score_label IN ('good', 'neutral', 'caution', 'danger')),
    summary_text TEXT NOT NULL CHECK (char_length(summary_text) <= 4000),
    symbols_referenced TEXT[] NOT NULL DEFAULT '{}'
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_commentary_account_time
    ON ai_manager_market_commentary(account_id, generated_at DESC)
    """)

    await conn.execute("""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'auto_trade_configs') THEN
        ALTER TABLE auto_trade_configs ADD COLUMN IF NOT EXISTS ai_manager_config JSONB DEFAULT NULL;
    END IF;
END $$;
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    account_id TEXT,
    actor_user_id TEXT NOT NULL,
    actor_ip INET,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    success BOOLEAN NOT NULL,
    detail JSONB
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events(event_type, timestamp DESC)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_security_events_actor ON security_events(actor_user_id, timestamp DESC)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_security_events_bf ON security_events(actor_user_id, event_type, timestamp DESC) WHERE success = FALSE
    """)

    await conn.execute("""
CREATE TABLE IF NOT EXISTS reauth_nonces (
    actor_user_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (actor_user_id, nonce)
)
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_reauth_nonces_expires ON reauth_nonces(expires_at)
    """)

    # Add ai_closed column to trades
    await conn.execute("""
ALTER TABLE trades ADD COLUMN IF NOT EXISTS ai_closed BOOLEAN DEFAULT FALSE
    """)
    await conn.execute("""
ALTER TABLE trades ADD COLUMN IF NOT EXISTS ai_decision_id BIGINT
    """)
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_trades_ai_decision_id ON trades(ai_decision_id) WHERE ai_decision_id IS NOT NULL
    """)



async def _create_backtest_tables(conn) -> None:
    """Migration 38: Backtesting system tables (kline cache + backtest runs/results/trades)."""
    # Kline cache — partitioned by month for fast range queries
    await conn.execute("""
CREATE TABLE IF NOT EXISTS kline_cache (
    symbol       TEXT NOT NULL,
    interval     TEXT NOT NULL,
    open_time    TIMESTAMPTZ NOT NULL,
    open         DOUBLE PRECISION NOT NULL,
    high         DOUBLE PRECISION NOT NULL,
    low          DOUBLE PRECISION NOT NULL,
    close        DOUBLE PRECISION NOT NULL,
    volume       DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, open_time)
) PARTITION BY RANGE (open_time)
""")
    # Default partition (catch-all for unexpected dates)
    await conn.execute("""
CREATE TABLE IF NOT EXISTS kline_cache_default PARTITION OF kline_cache DEFAULT
""")
    # Create monthly partitions ±6 months from now
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    for offset in range(-6, 7):
        month_start = (now.replace(day=1) + timedelta(days=32 * offset)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        part_name = f"kline_cache_{month_start.strftime('%Y_%m')}"
        await conn.execute(f"""
CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF kline_cache
    FOR VALUES FROM ('{month_start.strftime('%Y-%m-%d')}') TO ('{month_end.strftime('%Y-%m-%d')}')
""")

    # Coverage tracking for fast gap detection
    await conn.execute("""
CREATE TABLE IF NOT EXISTS kline_cache_coverage (
    symbol       TEXT NOT NULL,
    interval     TEXT NOT NULL,
    date         DATE NOT NULL,
    candle_count SMALLINT NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, interval, date)
)
""")

    # Backtest runs — lifecycle tracking
    await conn.execute("""
CREATE TABLE IF NOT EXISTS backtest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','completed','failed','cancelled')),
    config          JSONB NOT NULL,
    scan_source     JSONB NOT NULL,
    progress_pct    SMALLINT NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status
    ON backtest_runs(status) WHERE status IN ('pending','running')
""")
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created
    ON backtest_runs(created_at DESC)
""")

    # Backtest results — 1:1 with runs
    await conn.execute("""
CREATE TABLE IF NOT EXISTS backtest_results (
    run_id      UUID PRIMARY KEY REFERENCES backtest_runs(id) ON DELETE CASCADE,
    metrics     JSONB NOT NULL,
    equity_curve JSONB NOT NULL,
    summary     JSONB NOT NULL DEFAULT '{}',
    warnings    JSONB NOT NULL DEFAULT '[]'
)
""")

    # Backtest trades — individual simulated trades
    await conn.execute("""
CREATE TABLE IF NOT EXISTS backtest_trades (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('Buy','Sell')),
    entry_price     NUMERIC(20,8) NOT NULL,
    exit_price      NUMERIC(20,8),
    qty             NUMERIC(30,8) NOT NULL,
    leverage        SMALLINT NOT NULL,
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    pnl             NUMERIC(20,8),
    pnl_pct         NUMERIC(12,4),
    fees_paid       NUMERIC(20,8),
    close_reason    TEXT,
    mfe_pct         NUMERIC(12,4),
    mae_pct         NUMERIC(12,4),
    signal_score    SMALLINT,
    signal_confidence TEXT,
    scan_id         TEXT,
    metadata        JSONB DEFAULT '{}'
)
""")
    await conn.execute("""
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id)
""")


_SCHEMA_DEBUG_V42 = """
CREATE TABLE IF NOT EXISTS debug_runs (
    id BIGSERIAL PRIMARY KEY,
    scan_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (trigger_source IN ('scheduled','manual','run_now','unknown')),
    schedule_id TEXT,
    schedule_execution_id BIGINT,
    scan_started_at TIMESTAMPTZ,
    scan_completed_at TIMESTAMPTZ,
    exec_started_at TIMESTAMPTZ,
    exec_completed_at TIMESTAMPTZ,
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    total_symbols INT NOT NULL DEFAULT 0,
    completed_symbols INT NOT NULL DEFAULT 0,
    failed_symbols INT NOT NULL DEFAULT 0,
    num_accounts INT NOT NULL DEFAULT 0,
    phase_reached TEXT,
    dropped_event_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_runs_scan ON debug_runs(scan_id);
CREATE INDEX IF NOT EXISTS idx_debug_runs_created ON debug_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_debug_runs_schedule ON debug_runs(schedule_id, created_at DESC);
CREATE TABLE IF NOT EXISTS debug_account_traces (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    account_label TEXT,
    execution_mode TEXT,
    final_stopped_reason TEXT,
    gate_that_stopped TEXT,
    rescued_by_recheck BOOLEAN NOT NULL DEFAULT FALSE,
    base_capital NUMERIC(20,8),
    equity_at_start NUMERIC(20,8),
    positions_at_start_count INT,
    trades_executed INT NOT NULL DEFAULT 0,
    trades_failed INT NOT NULL DEFAULT 0,
    trades_skipped INT NOT NULL DEFAULT 0,
    rules_created JSONB NOT NULL DEFAULT '[]',
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_acct_run ON debug_account_traces(run_id);
CREATE INDEX IF NOT EXISTS idx_debug_acct_account ON debug_account_traces(account_id, created_at DESC);
CREATE TABLE IF NOT EXISTS debug_lifecycle_events (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    seq INT NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT 'unknown',
    event_type TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_life_run_acct ON debug_lifecycle_events(run_id, account_id, seq);
CREATE TABLE IF NOT EXISTS debug_symbol_decisions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'unknown',
    symbol TEXT NOT NULL,
    scan_score INT,
    scan_confidence TEXT,
    scan_direction TEXT,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason_detail JSONB NOT NULL DEFAULT '{}',
    order_id TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_sym_run_acct ON debug_symbol_decisions(run_id, account_id);
CREATE INDEX IF NOT EXISTS idx_debug_sym_symbol ON debug_symbol_decisions(symbol, ts DESC);
CREATE TABLE IF NOT EXISTS debug_exchange_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES debug_runs(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    gate TEXT NOT NULL,
    positions JSONB NOT NULL DEFAULT '[]',
    position_count INT NOT NULL DEFAULT 0,
    wallet JSONB NOT NULL DEFAULT '{}',
    equity NUMERIC(20,8),
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_debug_snap_run_acct ON debug_exchange_snapshots(run_id, account_id, gate);
CREATE TABLE IF NOT EXISTS debug_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    tracing_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    retention_days INT NOT NULL DEFAULT 60 CHECK (retention_days BETWEEN 1 AND 3650),
    symbol_decision_cap INT NOT NULL DEFAULT 200 CHECK (symbol_decision_cap BETWEEN 0 AND 100000),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO debug_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING
"""


_MIGRATIONS: list[tuple[int, _MigrationSQL]] = [
    (1, _SCHEMA_V1),
    (2, "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS asset_type TEXT NOT NULL DEFAULT 'stock' CHECK(asset_type IN ('stock','crypto'))"),
    (3, "CREATE INDEX IF NOT EXISTS idx_runs_asset_type_started ON analysis_runs(asset_type, started_at DESC)"),
    (4, """
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','completed','failed','cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
)
"""),
    (5, """
CREATE TABLE IF NOT EXISTS scan_results (
    id SERIAL PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('completed','failed','cancelled','unknown')),
    direction TEXT NOT NULL DEFAULT 'hold' CHECK(direction IN ('buy','sell','hold')),
    confidence TEXT NOT NULL DEFAULT 'none' CHECK(confidence IN ('high','moderate','low','none')),
    score INTEGER NOT NULL DEFAULT 0 CHECK(score BETWEEN -10 AND 10),
    decision_summary TEXT NOT NULL DEFAULT '',
    UNIQUE(scan_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON scan_results(scan_id)
"""),
    (6, """
ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS signal_source TEXT NOT NULL DEFAULT 'unknown'
"""),
    (7, """
CREATE TABLE IF NOT EXISTS trading_accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('demo', 'live')),
    api_key_masked TEXT NOT NULL,
    api_key_encrypted BYTEA NOT NULL,
    api_secret_encrypted BYTEA NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    bybit_uid TEXT,
    last_connected_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON trading_accounts(is_active) WHERE deleted_at IS NULL
"""),
    (8, """
CREATE TABLE IF NOT EXISTS closed_pnl_records (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_entry_price REAL NOT NULL,
    avg_exit_price REAL NOT NULL,
    closed_pnl REAL NOT NULL,
    leverage REAL NOT NULL DEFAULT 1,
    created_time INTEGER NOT NULL,
    bybit_order_id TEXT NOT NULL,
    UNIQUE(account_id, bybit_order_id)
);
CREATE INDEX IF NOT EXISTS idx_closed_pnl_account_time ON closed_pnl_records(account_id, created_time DESC)
"""),
    (9, """
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    equity REAL NOT NULL DEFAULT 0,
    wallet_balance REAL NOT NULL DEFAULT 0,
    available_balance REAL NOT NULL DEFAULT 0,
    unrealised_pnl REAL NOT NULL DEFAULT 0,
    realised_pnl REAL NOT NULL DEFAULT 0,
    positions_count INTEGER NOT NULL DEFAULT 0,
    margin_used REAL NOT NULL DEFAULT 0,
    cumulative_pnl REAL NOT NULL DEFAULT 0,
    daily_return_pct REAL NOT NULL DEFAULT 0,
    peak_equity REAL NOT NULL DEFAULT 0,
    drawdown_pct REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(account_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_account_date ON daily_snapshots(account_id, snapshot_date DESC)
"""),
    (10, """
ALTER TABLE trading_accounts ADD COLUMN IF NOT EXISTS include_in_analytics BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS high_freq_snapshots (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity REAL NOT NULL,
    unrealised_pnl REAL NOT NULL,
    realised_pnl REAL NOT NULL,
    balance REAL NOT NULL,
    position_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hf_snapshots_account_ts ON high_freq_snapshots(account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_hf_snapshots_ts ON high_freq_snapshots(ts)
"""),
    (11, """
ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
"""),
    (12, """
CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'swing' CHECK(category IN ('scalping','intraday','swing','positional','grid','dca','hedging','arbitrage')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('active','paused','archived','draft')),
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
CREATE INDEX IF NOT EXISTS idx_strategies_category ON strategies(category)
"""),
    (13, """
CREATE TABLE IF NOT EXISTS scheduled_scans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK(schedule_type IN ('once','interval','daily','weekly','cron')),
    schedule_config JSONB NOT NULL DEFAULT '{}',
    scan_config JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','error')),
    timezone TEXT NOT NULL DEFAULT 'UTC',
    next_run_at TEXT,
    last_run_at TEXT,
    last_scan_id TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_scans_status_next ON scheduled_scans(status, next_run_at)
"""),
    (14, """
CREATE TABLE IF NOT EXISTS schedule_executions (
    id SERIAL PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES scheduled_scans(id) ON DELETE CASCADE,
    scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK(status IN ('started','completed','failed','skipped_busy','skipped_no_key','cancelled')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_executions_lookup ON schedule_executions(schedule_id, started_at DESC)
"""),
    (15, """
ALTER TABLE scans ADD COLUMN IF NOT EXISTS schedule_id TEXT;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS triggered_by TEXT NOT NULL DEFAULT 'manual' CHECK(triggered_by IN ('manual','scheduled','run_now'))
"""),
    (16, """
CREATE INDEX IF NOT EXISTS idx_scans_schedule_id ON scans(schedule_id) WHERE schedule_id IS NOT NULL
"""),
    (17, """
CREATE TABLE IF NOT EXISTS close_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    trigger_type VARCHAR(30) NOT NULL CHECK(trigger_type IN ('BALANCE_BELOW','BALANCE_ABOVE','EQUITY_DROP_PCT','EQUITY_RISE_PCT','PNL_BELOW','PNL_ABOVE')),
    threshold_value NUMERIC(20,8) NOT NULL,
    reference_value NUMERIC(20,8),
    status VARCHAR(15) NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','triggered','executed','expired')),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_close_rules_status_account ON close_rules(status, account_id)
"""),
    (18, """
CREATE TABLE IF NOT EXISTS close_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    rule_id UUID REFERENCES close_rules(id),
    trigger_source VARCHAR(10) NOT NULL CHECK(trigger_source IN ('manual','rule')),
    total_positions INT NOT NULL DEFAULT 0,
    closed_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    results JSONB NOT NULL DEFAULT '[]',
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_close_executions_account ON close_executions(account_id, executed_at DESC)
"""),
    (19, "ALTER TABLE closed_pnl_records ALTER COLUMN created_time TYPE BIGINT"),
    (20, """
CREATE TABLE IF NOT EXISTS trading_cycles (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','placing_trades','running','stopping','completed','stopped','failed')),
    trade_direction VARCHAR(10) NOT NULL CHECK (trade_direction IN ('straight','reverse')),
    leverage INTEGER NOT NULL CHECK (leverage BETWEEN 1 AND 125),
    capital_pct NUMERIC(5,2) NOT NULL CHECK (capital_pct > 0 AND capital_pct <= 100),
    take_profit_pct NUMERIC(6,2) CHECK (take_profit_pct > 0 AND take_profit_pct <= 1000),
    stop_loss_pct NUMERIC(6,2) CHECK (stop_loss_pct > 0 AND stop_loss_pct <= 1000),
    min_score INTEGER NOT NULL DEFAULT 3 CHECK (min_score BETWEEN -10 AND 10),
    min_confidence VARCHAR(10) NOT NULL DEFAULT 'moderate'
        CHECK (min_confidence IN ('none','low','moderate','high')),
    signal_filter VARCHAR(4) NOT NULL DEFAULT 'both'
        CHECK (signal_filter IN ('buy','sell','both')),
    max_trades INTEGER NOT NULL CHECK (max_trades BETWEEN 1 AND 20),
    target_type VARCHAR(10) NOT NULL CHECK (target_type IN ('percentage','amount')),
    target_value NUMERIC(12,2) NOT NULL CHECK (target_value > 0),
    max_drawdown_pct NUMERIC(5,2) NOT NULL CHECK (max_drawdown_pct > 0 AND max_drawdown_pct <= 100),
    initial_equity NUMERIC(14,4),
    final_pnl NUMERIC(14,4),
    stop_reason VARCHAR(200),
    trades_placed INTEGER NOT NULL DEFAULT 0,
    trades_failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_account_status ON trading_cycles(account_id, status);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_created ON trading_cycles(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_cycles_scan_id ON trading_cycles(scan_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_cycle ON trading_cycles(account_id)
    WHERE status IN ('pending','placing_trades','running','stopping');
CREATE INDEX IF NOT EXISTS idx_trading_cycles_stuck ON trading_cycles(status, created_at)
    WHERE status IN ('running','placing_trades','stopping')
"""),
    (21, """
CREATE TABLE IF NOT EXISTS cycle_trades (
    id SERIAL PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES trading_cycles(id) ON DELETE RESTRICT,
    symbol VARCHAR(30) NOT NULL,
    order_id VARCHAR(50),
    order_link_id VARCHAR(50),
    side VARCHAR(4) NOT NULL CHECK (side IN ('Buy','Sell')),
    qty NUMERIC(18,8),
    entry_price NUMERIC(18,8),
    status VARCHAR(15) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','submitted','filled','failed','cancelled')),
    error_msg VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cycle_trades_cycle_id ON cycle_trades(cycle_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cycle_trades_order_link_id ON cycle_trades(order_link_id)
    WHERE order_link_id IS NOT NULL
"""),
    (22, """
ALTER TABLE close_rules ADD COLUMN IF NOT EXISTS cycle_id INTEGER REFERENCES trading_cycles(id) ON DELETE RESTRICT;
ALTER TABLE close_rules DROP CONSTRAINT IF EXISTS close_rules_status_check;
ALTER TABLE close_rules ADD CONSTRAINT close_rules_status_check
    CHECK (status IN ('active','paused','triggered','executed','expired','pending_activation'));
CREATE INDEX IF NOT EXISTS idx_close_rules_cycle_id ON close_rules(cycle_id) WHERE cycle_id IS NOT NULL
"""),
    (23, """
CREATE INDEX IF NOT EXISTS idx_scans_started_desc ON scans(started_at DESC)
"""),
    (24, """
ALTER TABLE scheduled_scans DROP CONSTRAINT IF EXISTS scheduled_scans_status_check;
ALTER TABLE scheduled_scans ADD CONSTRAINT scheduled_scans_status_check
    CHECK (status IN ('active','paused','completed','error','cancelled'))
"""),
    (25, _SCHEMA_V25_TABLES),
    (26, _schema_v26_triggers),
    (27, """
CREATE TABLE IF NOT EXISTS dead_letter (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    attempt_count INTEGER DEFAULT 1,
    max_retries INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','retrying','exhausted','resolved')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_retried_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_dead_letter_status ON dead_letter(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_dead_letter_operation ON dead_letter(operation);
"""),
    (28, "ALTER TABLE scans ADD COLUMN IF NOT EXISTS auto_trade_results JSONB NOT NULL DEFAULT '[]'"),
    (29, "ALTER TABLE scans ADD COLUMN IF NOT EXISTS auto_trade_summaries JSONB NOT NULL DEFAULT '[]'"),
    (30, """
ALTER TABLE trades DROP CONSTRAINT IF EXISTS chk_source_id;
ALTER TABLE trades ADD CONSTRAINT chk_source_id CHECK (
    (source = 'cycle' AND source_id IS NOT NULL) OR
    (source = 'manual' AND source_id IS NULL) OR
    (source = 'scanner')
);
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_source_check;
ALTER TABLE trades ADD CONSTRAINT trades_source_check CHECK (source IN ('manual', 'cycle', 'scanner'))
"""),
    (31, _fix_source_constraint),
    (32, _fix_close_rules_constraints),
    (33, _add_ai_manager_tables),
    (34, """
CREATE TABLE IF NOT EXISTS ai_manager_llm_calls (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    call_id UUID NOT NULL,
    evaluation_cycle_id UUID NOT NULL,
    node_name TEXT NOT NULL DEFAULT 'action_generation',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    urgency_tier TEXT NOT NULL,
    action_returned TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    reasoning_preview TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_account_time
    ON ai_manager_llm_calls(account_id, timestamp DESC, id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_cycle
    ON ai_manager_llm_calls(evaluation_cycle_id);
CREATE TABLE IF NOT EXISTS ai_manager_market_commentary (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    commentary_type TEXT NOT NULL CHECK (commentary_type IN ('template', 'llm')),
    regime_label TEXT NOT NULL,
    day_score INTEGER CHECK (day_score IS NULL OR (day_score >= 0 AND day_score <= 100)),
    day_score_label TEXT CHECK (day_score_label IS NULL OR day_score_label IN ('good', 'neutral', 'caution', 'danger')),
    summary_text TEXT NOT NULL CHECK (char_length(summary_text) <= 4000),
    symbols_referenced TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_commentary_account_time
    ON ai_manager_market_commentary(account_id, generated_at DESC)
"""),
    (35, """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS scan_result_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_trades_scan_result_id ON trades(scan_result_id) WHERE scan_result_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS signal_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID NOT NULL UNIQUE REFERENCES trades(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    symbol VARCHAR(30) NOT NULL,
    direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
    confidence_score INTEGER,
    confidence_tier VARCHAR(10) CHECK (confidence_tier IN ('high', 'moderate', 'low')),
    signal_source VARCHAR(10),
    regime_at_entry VARCHAR(15) CHECK (regime_at_entry IS NULL OR regime_at_entry IN ('trending_up', 'trending_down', 'ranging', 'volatile')),
    regime_confidence NUMERIC(4,2),
    entry_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    hold_duration_minutes INTEGER,
    realized_pnl_pct NUMERIC(12,4),
    net_pnl NUMERIC(20,8),
    fees NUMERIC(20,8),
    close_reason VARCHAR(20),
    benchmark_bnh_pnl_pct NUMERIC(12,4),
    benchmark_random_expected_pnl NUMERIC(12,4),
    is_win BOOLEAN NOT NULL,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sp_account_closed ON signal_performance(account_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sp_symbol_closed ON signal_performance(symbol, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sp_confidence ON signal_performance(confidence_score);
CREATE INDEX IF NOT EXISTS idx_sp_regime ON signal_performance(regime_at_entry);
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(30) NOT NULL,
    regime VARCHAR(15) NOT NULL CHECK (regime IN ('trending_up', 'trending_down', 'ranging', 'volatile')),
    adx NUMERIC(8,4),
    atr_pct NUMERIC(8,4),
    bb_width_pct NUMERIC(8,4),
    llm_confirmed BOOLEAN DEFAULT FALSE,
    llm_regime VARCHAR(15),
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rs_symbol_time ON regime_snapshots(symbol, classified_at DESC);
CREATE TABLE IF NOT EXISTS decay_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(30) NOT NULL,
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('warning', 'critical')),
    message TEXT NOT NULL,
    metric_value NUMERIC(12,4),
    threshold NUMERIC(12,4),
    window_trades INTEGER,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""),
    (36, """
CREATE TABLE IF NOT EXISTS symbol_sectors (
    symbol VARCHAR(30) PRIMARY KEY,
    sector VARCHAR(15) NOT NULL DEFAULT 'other',
    source VARCHAR(10) NOT NULL DEFAULT 'static'
        CHECK (source IN ('static', 'coingecko', 'llm', 'manual')),
    coingecko_categories TEXT,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ss_sector ON symbol_sectors(sector);
CREATE INDEX IF NOT EXISTS idx_ss_classified ON symbol_sectors(classified_at)
"""),
    (37, """
ALTER TABLE close_rules DROP CONSTRAINT IF EXISTS close_rules_trigger_type_check;
ALTER TABLE close_rules ADD CONSTRAINT close_rules_trigger_type_check
    CHECK (trigger_type IN (
        'BALANCE_BELOW', 'BALANCE_ABOVE',
        'EQUITY_DROP_PCT', 'EQUITY_DROP_PCT_SMART', 'EQUITY_RISE_PCT',
        'PNL_BELOW', 'PNL_ABOVE',
        'BREAKEVEN_TIMEOUT', 'MAX_DURATION',
        'TRAILING_PROFIT', 'PAUSE_TRADING'
    ))
"""),
    (38, _create_backtest_tables),
    (39, """ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS analysis_price NUMERIC(20,8)"""),
    (40, """
-- Widen backtest_trades percent columns: mfe_pct/pnl_pct are leverage-scaled
-- (value × leverage, up to 125×) and can exceed NUMERIC(8,4)'s 9999.9999 cap on
-- a large favorable move, which would crash _persist_results and lose a
-- completed simulation. NUMERIC(12,4) matches realized_pnl_pct elsewhere.
ALTER TABLE backtest_trades ALTER COLUMN pnl_pct TYPE NUMERIC(12,4);
ALTER TABLE backtest_trades ALTER COLUMN mfe_pct TYPE NUMERIC(12,4);
ALTER TABLE backtest_trades ALTER COLUMN mae_pct TYPE NUMERIC(12,4);
-- Widen qty: it is a UNIT COUNT (notional / price). For an ultra-cheap token at
-- the Bybit price floor (~1e-8) the worst-case is notional(~1.25e10) / 1e-8 ≈
-- 1.25e18 units, which overflows NUMERIC(20,8) (max ~1e12). NUMERIC(30,8) (max
-- ~1e22) covers it with headroom.
ALTER TABLE backtest_trades ALTER COLUMN qty TYPE NUMERIC(30,8);
"""),
    (41, """
-- The trades list reads filter by run_id and sort by entry_time (default) or pnl,
-- over up to _MAX_SIGNALS (50k) rows per run. The single (run_id) index forces an
-- in-memory sort of every matching row on each page. Composite indexes let Postgres
-- satisfy the ORDER BY from the index. IF NOT EXISTS keeps this idempotent.
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_entry
    ON backtest_trades(run_id, entry_time);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_pnl
    ON backtest_trades(run_id, pnl);
"""),
    # v42 — auto-trade debug tracing tables (renumbered from the branch's v38 to
    # resolve a version collision with the backtesting feature, which already
    # owns v38–v41 and is applied to the live DB).
    (42, _SCHEMA_DEBUG_V42),
]


def _default_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://user:pass@localhost:5432/tradingagents"
        )
    return dsn


class AsyncAnalysisDB:

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _default_dsn()
        self._instance_id = str(uuid.uuid4())
        self._pool: asyncpg.Pool | None = None
        self._sync_pool = None
        self._closed = False
        self._sync_sem: threading.Semaphore | None = None

    @property
    def pool(self) -> "asyncpg.Pool":
        if self._closed:
            raise RuntimeError("Database connection is closed")
        if self._pool is None:
            raise RuntimeError("Database not connected; call connect() first")
        return self._pool

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=int(os.environ.get("DB_POOL_MIN", "2")),
            max_size=int(os.environ.get("DB_POOL_MAX", "10")),
            command_timeout=int(os.environ.get("DB_COMMAND_TIMEOUT", "10")),
            max_inactive_connection_lifetime=300,
            timeout=10,
        )
        # Sync bridge for graph executor threads
        import psycopg2.pool
        _sync_max = int(os.environ.get("DB_SYNC_POOL_MAX", os.environ.get("GRAPH_EXECUTOR_WORKERS", "8")))
        self._sync_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=_sync_max, dsn=self._dsn, connect_timeout=10,
        )
        self._sync_sem = threading.Semaphore(_sync_max)
        await self._apply_migrations()

    @asynccontextmanager
    async def _transaction(self):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def _apply_migrations(self) -> None:
        # Use a dedicated connection (not pool) for advisory lock
        conn = await asyncpg.connect(dsn=self._dsn)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL DEFAULT 0)"
            )
            # Advisory lock prevents concurrent migration from multiple instances
            await conn.execute("SELECT pg_advisory_lock(8675309)")
            try:
                row = await conn.fetchrow("SELECT version FROM schema_version")
                if row is None:
                    await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
                    current = 0
                else:
                    current = row["version"]

                max_version = _MIGRATIONS[-1][0] if _MIGRATIONS else 0
                if current > max_version:
                    raise RuntimeError(
                        f"Database schema v{current} is newer than this application "
                        f"supports (max v{max_version}). Please upgrade the application."
                    )

                if current >= max_version:
                    return

                for version, sql in _MIGRATIONS:
                    if version <= current:
                        continue
                    async with conn.transaction():
                        if callable(sql):
                            await sql(conn)
                        else:
                            for stmt in sql.split(";"):
                                stmt = stmt.strip()
                                if stmt:
                                    await conn.execute(stmt)
                        await conn.execute(
                            "UPDATE schema_version SET version = $1", version
                        )
            finally:
                await conn.execute("SELECT pg_advisory_unlock(8675309)")
        finally:
            await conn.close()

    # ── Health / lifecycle ──────────────────────────────────────────

    def is_healthy(self) -> bool:
        return self._pool is not None and not self._pool.is_closing()

    async def close(self):
        self._closed = True
        if self._sync_pool:
            self._sync_pool.closeall()
        if self._pool:
            await self._pool.close()

    # ── Sync bridge (for graph executor threads) ───────────────────

    @contextmanager
    def _get_sync_conn(self):
        if self._closed:
            raise RuntimeError("Database is shutting down")
        if not self._sync_sem.acquire(timeout=10):
            raise RuntimeError("Sync connection pool exhausted (timeout=10s)")
        try:
            conn = self._sync_pool.getconn()
            try:
                yield conn
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                close = getattr(conn, "closed", 0) != 0
                self._sync_pool.putconn(conn, close=close)
        finally:
            self._sync_sem.release()

    def sync_save_report_section(self, run_id, section, content):
        with self._get_sync_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO report_sections (run_id, section, content) VALUES (%s, %s, %s) "
                "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                (run_id, section, content),
            )
            conn.commit()

    def sync_update_run_status(self, run_id, status, error, completed_at):
        with self._get_sync_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE analysis_runs SET status=%s, error=%s, completed_at=%s "
                "WHERE run_id=%s AND status='running'",
                (status, error, completed_at, run_id),
            )
            conn.commit()

    # ── Pure helpers (no DB) ───────────────────────────────────────

    @staticmethod
    def _deserialize_strategy(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("config"), str):
            d["config"] = json.loads(d["config"])
        return d

    @staticmethod
    def _deserialize_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        for k in ("schedule_config", "scan_config"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return d

    def _serialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DB row to JSON-safe dict."""
        result = {}
        for k, v in dict(row).items():
            if isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, date):
                result[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                result[k] = str(v)
            elif isinstance(v, Decimal):
                result[k] = str(v)
            else:
                result[k] = v
        return result

    # ── Analysis Runs ──────────────────────────────────────────────

    async def insert_run(self, run: Dict[str, Any]) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                run["run_id"],
                run["ticker"],
                run["analysis_date"],
                run["status"],
                run.get("config", "{}"),
                run["started_at"],
                self._instance_id,
                run.get("asset_type", "stock"),
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Run {run['run_id']} already exists")

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        completed_at: Optional[str],
    ) -> bool:
        result = await self.pool.execute(
            "UPDATE analysis_runs SET status=$1, error=$2, completed_at=$3 "
            "WHERE run_id=$4 AND status='running'",
            status, error, completed_at, run_id,
        )
        return int(result.split()[-1]) > 0

    async def save_report_section(self, run_id: str, section: str, content: str) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO report_sections (run_id, section, content) VALUES ($1, $2, $3) "
                "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                run_id, section, content,
            )
        except asyncpg.UniqueViolationError:
            pass

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT * FROM analysis_runs WHERE run_id=$1", run_id
        )
        return dict(row) if row else None

    async def list_runs(
        self,
        page: int = 1,
        limit: int = 20,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        limit = min(max(limit, 1), 10000)
        conditions: list[str] = []
        params: list[Any] = []
        idx = 0

        if ticker:
            idx += 1
            conditions.append(f"ticker = ${idx}")
            params.append(ticker)
        if status:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)
        if from_date:
            idx += 1
            conditions.append(f"analysis_date >= ${idx}")
            params.append(from_date)
        if to_date:
            idx += 1
            conditions.append(f"analysis_date <= ${idx}")
            params.append(to_date)
        if asset_type:
            idx += 1
            conditions.append(f"asset_type = ${idx}")
            params.append(asset_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * limit

        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM analysis_runs {where}", *params
        )
        rows = await self.pool.fetch(
            f"SELECT run_id, ticker, analysis_date, status, started_at, "
            f"completed_at, asset_type, config FROM analysis_runs {where} "
            f"ORDER BY started_at DESC LIMIT ${idx + 1} OFFSET ${idx + 2}",
            *params, limit, offset,
        )
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def get_report_sections(self, run_id: str) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM report_sections WHERE run_id=$1 ORDER BY id", run_id
        )
        return [dict(r) for r in rows]

    async def recover_orphans(self) -> int:
        result = await self.pool.execute(
            "UPDATE analysis_runs SET status='failed', "
            "error='Server restarted — orphaned run' "
            "WHERE status='running'"
        )
        return int(result.split()[-1])

    async def get_checkpoint_exists(self, ticker: str, date: str) -> bool:
        row = await self.pool.fetchrow(
            "SELECT 1 FROM analysis_runs WHERE ticker=$1 AND analysis_date=$2 LIMIT 1",
            ticker, date,
        )
        return row is not None

    async def delete_run(self, run_id: str) -> bool:
        result = await self.pool.execute(
            "DELETE FROM analysis_runs WHERE run_id=$1", run_id
        )
        return int(result.split()[-1]) > 0

    async def delete_all_runs(self) -> int:
        result = await self.pool.execute("DELETE FROM analysis_runs")
        return int(result.split()[-1])

    async def delete_all_checkpoints(self) -> int:
        result = await self.pool.execute(
            "DELETE FROM analysis_runs "
            "WHERE status IN ('completed', 'failed', 'cancelled')"
        )
        return int(result.split()[-1])

    async def delete_ticker_checkpoints(self, ticker: str) -> int:
        result = await self.pool.execute(
            "DELETE FROM analysis_runs "
            "WHERE ticker=$1 AND status IN ('completed', 'failed', 'cancelled')",
            ticker,
        )
        return int(result.split()[-1])

    async def checkpoint(self) -> None:
        pass

    async def health_check(self) -> str:
        try:
            await self.pool.fetchval("SELECT 1")
            return "ok"
        except Exception:
            return "degraded"

    # ── Scanner persistence ──────────────────────────────────────────

    async def insert_scan(self, scan: Dict[str, Any]) -> None:
        await self.pool.execute(
            "INSERT INTO scans "
            "(scan_id, status, config, total, completed, failed, started_at, schedule_id, triggered_by) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            scan["scan_id"],
            scan.get("status", "running"),
            scan.get("config", "{}"),
            scan.get("total", 0),
            scan.get("completed", 0),
            scan.get("failed", 0),
            scan["started_at"],
            scan.get("schedule_id"),
            scan.get("triggered_by", "manual"),
        )

    async def update_scan(self, scan_id: str, **fields: Any) -> None:
        allowed = {"status", "total", "completed", "failed", "completed_at", "auto_trade_results", "auto_trade_summaries"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(scan_id)
        await self.pool.execute(
            f"UPDATE scans SET {', '.join(parts)} WHERE scan_id=${len(params)}",
            *params,
        )

    async def insert_scan_result(self, scan_id: str, result: Dict[str, Any]) -> Optional[int]:
        direction = result.get("direction", "hold")
        if direction not in ("buy", "sell", "hold"):
            logger.error("insert_scan_result: invalid direction %r — forcing hold", direction)
            direction = "hold"
        confidence = result.get("confidence", "none")
        if confidence not in ("high", "moderate", "low", "none"):
            logger.error("insert_scan_result: invalid confidence %r — forcing none", confidence)
            confidence = "none"
        score = int(result.get("score", 0))
        score = max(-10, min(10, score))
        status = result.get("status", "failed")
        if status not in ("completed", "failed", "cancelled", "unknown"):
            logger.warning("insert_scan_result: invalid status %r — forcing unknown", status)
            status = "unknown"

        # analysis_price (v39) anchors the backtest's price-drift filter to the price
        # the signal was generated at. It is read back by BacktestService.load_signals;
        # if it is not persisted here the drift filter silently no-ops in backtests
        # (every row NULL), diverging from live trading. Coerce defensively: only a
        # positive finite number is stored, otherwise NULL.
        _analysis_price = result.get("analysis_price")
        try:
            _analysis_price = float(_analysis_price) if _analysis_price is not None else None
            if _analysis_price is not None and not (_analysis_price > 0):
                _analysis_price = None
        except (TypeError, ValueError):
            _analysis_price = None

        row = await self.pool.fetchrow(
            "INSERT INTO scan_results "
            "(scan_id, ticker, run_id, status, direction, confidence, "
            "score, decision_summary, signal_source, analysis_price) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
            "ON CONFLICT (scan_id, ticker) DO UPDATE SET "
            "run_id = EXCLUDED.run_id, status = EXCLUDED.status, "
            "direction = EXCLUDED.direction, confidence = EXCLUDED.confidence, "
            "score = EXCLUDED.score, decision_summary = EXCLUDED.decision_summary, "
            "signal_source = EXCLUDED.signal_source, "
            "analysis_price = COALESCE(EXCLUDED.analysis_price, scan_results.analysis_price) "
            "RETURNING id",
            scan_id,
            result["ticker"],
            result.get("run_id"),
            status,
            direction,
            confidence,
            score,
            result.get("decision_summary", ""),
            result.get("signal_source", "unknown"),
            _analysis_price,
        )
        return row["id"] if row else None

    async def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT * FROM scans WHERE scan_id=$1", scan_id
        )
        if not row:
            return None
        scan = dict(row)
        results = await self.pool.fetch(
            "SELECT id, ticker, run_id, status, direction, confidence, score, "
            "decision_summary, signal_source "
            "FROM scan_results WHERE scan_id=$1 ORDER BY ABS(score) DESC",
            scan_id,
        )
        scan["results"] = [dict(r) for r in results]
        return scan

    async def list_scans(self) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT scan_id, status, config, total, completed, failed, "
            "started_at, completed_at, schedule_id, triggered_by "
            "FROM scans ORDER BY started_at DESC LIMIT 50"
        )
        scans = [dict(r) for r in rows]
        if not scans:
            return []
        scan_ids = [s["scan_id"] for s in scans]
        counts = await self.pool.fetch(
            "SELECT scan_id, direction, COUNT(*) as cnt "
            "FROM scan_results WHERE scan_id = ANY($1) "
            "GROUP BY scan_id, direction",
            scan_ids,
        )
        counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
        for row in counts:
            counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
        for scan in scans:
            scan["results"] = []
            scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
        return scans

    async def get_scan_completed_tickers(self, scan_id: str) -> set[str]:
        rows = await self.pool.fetch(
            "SELECT ticker FROM scan_results WHERE scan_id=$1", scan_id
        )
        return {r["ticker"] for r in rows}

    async def increment_scan_counter(self, scan_id: str, field: str) -> None:
        if field not in ("completed", "failed"):
            return
        await self.pool.execute(
            f"UPDATE scans SET {field} = {field} + 1 WHERE scan_id=$1",
            scan_id,
        )

    async def get_running_scans(self) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM scans WHERE status='running'"
        )
        return [dict(r) for r in rows]

    async def delete_scan(self, scan_id: str) -> Dict[str, Any]:
        """Delete a scan and cascade-delete its associated analysis runs."""
        async with self._transaction() as conn:
            run_rows = await conn.fetch(
                "SELECT run_id FROM scan_results WHERE scan_id=$1 AND run_id IS NOT NULL",
                scan_id,
            )
            run_ids = [r["run_id"] for r in run_rows]

            deleted_sections = 0
            deleted_analyses = 0
            if run_ids:
                result = await conn.execute(
                    "DELETE FROM report_sections WHERE run_id = ANY($1)", run_ids
                )
                deleted_sections = int(result.split()[-1])
                result = await conn.execute(
                    "DELETE FROM analysis_runs WHERE run_id = ANY($1)", run_ids
                )
                deleted_analyses = int(result.split()[-1])

            result = await conn.execute(
                "DELETE FROM scan_results WHERE scan_id=$1", scan_id
            )
            deleted_results = int(result.split()[-1])

            result = await conn.execute(
                "DELETE FROM scans WHERE scan_id=$1", scan_id
            )
            scan_deleted = int(result.split()[-1])

        if scan_deleted == 0:
            return {}
        return {
            "deleted_results": deleted_results,
            "deleted_analyses": deleted_analyses,
            "deleted_sections": deleted_sections,
        }

    async def get_scan_analysis_count(self, scan_id: str) -> int:
        return await self.pool.fetchval(
            "SELECT COUNT(*) FROM scan_results WHERE scan_id=$1 AND run_id IS NOT NULL",
            scan_id,
        )

    # ── Trading Accounts persistence ────────────────────────────────────

    async def insert_account(self, account: Dict[str, Any]) -> None:
        await self.pool.execute(
            "INSERT INTO trading_accounts "
            "(id, label, account_type, api_key_masked, api_key_encrypted, "
            "api_secret_encrypted, key_version, is_active, bybit_uid, "
            "last_connected_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
            account["id"],
            account["label"],
            account["account_type"],
            account["api_key_masked"],
            account["api_key_encrypted"],
            account["api_secret_encrypted"],
            account.get("key_version", 1),
            1,
            account.get("bybit_uid"),
            account.get("last_connected_at"),
            account["created_at"],
            account["updated_at"],
        )

    async def list_accounts(self) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT id, label, account_type, api_key_masked, is_active, "
            "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
            "include_in_analytics "
            "FROM trading_accounts WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT id, label, account_type, api_key_masked, is_active, "
            "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
            "include_in_analytics "
            "FROM trading_accounts WHERE id=$1 AND deleted_at IS NULL",
            account_id,
        )
        return dict(row) if row else None

    async def get_account_credentials(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT id, account_type, api_key_encrypted, api_secret_encrypted "
            "FROM trading_accounts WHERE id=$1 AND deleted_at IS NULL",
            account_id,
        )
        if not row:
            return None
        d = dict(row)
        # asyncpg returns memoryview for BYTEA — convert to bytes
        d["api_key_encrypted"] = bytes(d["api_key_encrypted"])
        d["api_secret_encrypted"] = bytes(d["api_secret_encrypted"])
        return d

    async def update_account(self, account_id: str, **fields: Any) -> bool:
        allowed = {"label", "is_active", "bybit_uid", "last_connected_at", "last_error", "include_in_analytics"}
        nullable = {"last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed and (v is not None or k in nullable)}
        if not updates:
            return False
        updates["updated_at"] = fields.get("updated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(account_id)
        result = await self.pool.execute(
            f"UPDATE trading_accounts SET {', '.join(parts)} WHERE id=${len(params)} AND deleted_at IS NULL",
            *params,
        )
        return int(result.split()[-1]) > 0

    async def rotate_account_credentials(
        self, account_id: str, api_key_masked: str,
        api_key_encrypted: bytes, api_secret_encrypted: bytes, updated_at: str,
    ) -> bool:
        result = await self.pool.execute(
            "UPDATE trading_accounts SET api_key_masked=$1, api_key_encrypted=$2, "
            "api_secret_encrypted=$3, last_error=NULL, updated_at=$4 "
            "WHERE id=$5 AND deleted_at IS NULL",
            api_key_masked, api_key_encrypted, api_secret_encrypted, updated_at, account_id,
        )
        return int(result.split()[-1]) > 0

    async def soft_delete_account(self, account_id: str, deleted_at: str) -> bool:
        result = await self.pool.execute(
            "UPDATE trading_accounts SET deleted_at=$1, is_active=0, updated_at=$1 "
            "WHERE id=$2 AND deleted_at IS NULL",
            deleted_at, account_id,
        )
        return int(result.split()[-1]) > 0

    async def remove_account_from_scheduled_scans(self, account_id: str) -> List[str]:
        """Remove an account from all scheduled scan auto_trade_configs. Returns list of modified schedule IDs."""
        modified_ids: List[str] = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with self._transaction() as conn:
            rows = await conn.fetch(
                "SELECT id, scan_config FROM scheduled_scans "
                "WHERE scan_config->'auto_trade_configs' IS NOT NULL AND status IN ('active','paused')"
            )
            for row in rows:
                scan_config = row["scan_config"] if isinstance(row["scan_config"], dict) else json.loads(row["scan_config"])
                configs = scan_config.get("auto_trade_configs") or []
                if not isinstance(configs, list):
                    continue
                filtered = [c for c in configs if c.get("account_id") != account_id]
                if len(filtered) < len(configs):
                    scan_config["auto_trade_configs"] = filtered
                    await conn.execute(
                        "UPDATE scheduled_scans SET scan_config=$1, updated_at=$2 WHERE id=$3",
                        json.dumps(scan_config), now, row["id"],
                    )
                    modified_ids.append(row["id"])
        return modified_ids

    # ── Closed PnL persistence ──────────────────────────────────────────

    async def insert_closed_pnl_records(self, account_id: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        inserted = 0
        for rec in records:
            try:
                await self.pool.execute(
                    "INSERT INTO closed_pnl_records "
                    "(account_id, symbol, side, qty, avg_entry_price, avg_exit_price, "
                    "closed_pnl, leverage, created_time, bybit_order_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
                    "ON CONFLICT (account_id, bybit_order_id) DO NOTHING",
                    account_id,
                    rec["symbol"],
                    rec["side"],
                    float(rec["qty"]),
                    float(rec["avgEntryPrice"]),
                    float(rec["avgExitPrice"]),
                    float(rec["closedPnl"]),
                    float(rec.get("leverage", 1)),
                    int(rec["createdTime"]),
                    rec["orderId"],
                )
                inserted += 1
            except asyncpg.UniqueViolationError:
                pass
            except Exception:
                logger.exception("Failed to insert closed PnL record: %s", rec.get("orderId"))
        return inserted

    async def get_closed_pnl(
        self, account_id: str, start_time: int, end_time: int,
        page: int = 1, limit: int = 50,
    ) -> Dict[str, Any]:
        offset = (page - 1) * limit
        total = await self.pool.fetchval(
            "SELECT COUNT(*) FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3",
            account_id, start_time, end_time,
        )
        rows = await self.pool.fetch(
            "SELECT * FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3 "
            "ORDER BY created_time DESC LIMIT $4 OFFSET $5",
            account_id, start_time, end_time, limit, offset,
        )
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    async def get_closed_pnl_summary(
        self, account_id: str, start_time: int, end_time: int,
    ) -> Dict[str, Any]:
        rows = await self.pool.fetch(
            "SELECT closed_pnl FROM closed_pnl_records "
            "WHERE account_id=$1 AND created_time>=$2 AND created_time<=$3",
            account_id, start_time, end_time,
        )
        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }
        vals = [r["closed_pnl"] for r in rows]
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v < 0]
        total_pnl = sum(vals)
        total_count = len(vals)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0.0
        avg_win = str(sum(wins) / win_count) if wins else "0"
        avg_loss = str(abs(sum(losses) / loss_count)) if losses else "0"
        return {
            "total_pnl": str(total_pnl),
            "total_count": total_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }

    async def get_portfolio_pnl_summary(
        self, start_time: int, end_time: int,
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        sql = (
            "SELECT cpr.closed_pnl FROM closed_pnl_records cpr "
            "JOIN trading_accounts ta ON ta.id = cpr.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND cpr.created_time>=$1 AND cpr.created_time<=$2"
        )
        params: list = [start_time, end_time]
        if account_type:
            sql += " AND ta.account_type = $3"
            params.append(account_type)
        rows = await self.pool.fetch(sql, *params)

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }
        vals = [r["closed_pnl"] for r in rows]
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v < 0]
        total_pnl = sum(vals)
        total_count = len(vals)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0.0
        avg_win = str(sum(wins) / win_count) if wins else "0"
        avg_loss = str(abs(sum(losses) / loss_count)) if losses else "0"
        return {
            "total_pnl": str(total_pnl),
            "total_count": total_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }

    async def get_latest_closed_pnl_time(self, account_id: str) -> Optional[int]:
        val = await self.pool.fetchval(
            "SELECT MAX(created_time) FROM closed_pnl_records WHERE account_id=$1",
            account_id,
        )
        return val if val else None

    # ── Daily Snapshots ────────────────────────────────────────────────

    async def upsert_daily_snapshot(self, snapshot: Dict[str, Any]) -> None:
        snap_date = snapshot["snapshot_date"]
        if isinstance(snap_date, str):
            snap_date = date.fromisoformat(snap_date)
        await self.pool.execute(
            "INSERT INTO daily_snapshots "
            "(account_id, snapshot_date, equity, wallet_balance, available_balance, "
            "unrealised_pnl, realised_pnl, positions_count, margin_used, "
            "cumulative_pnl, daily_return_pct, peak_equity, drawdown_pct) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
            "ON CONFLICT (account_id, snapshot_date) DO UPDATE SET "
            "equity = EXCLUDED.equity, wallet_balance = EXCLUDED.wallet_balance, "
            "available_balance = EXCLUDED.available_balance, "
            "unrealised_pnl = EXCLUDED.unrealised_pnl, "
            "realised_pnl = EXCLUDED.realised_pnl, "
            "positions_count = EXCLUDED.positions_count, "
            "margin_used = EXCLUDED.margin_used, "
            "cumulative_pnl = EXCLUDED.cumulative_pnl, "
            "daily_return_pct = EXCLUDED.daily_return_pct, "
            "peak_equity = EXCLUDED.peak_equity, "
            "drawdown_pct = EXCLUDED.drawdown_pct, "
            "updated_at = now()",
            snapshot["account_id"],
            snap_date,
            snapshot.get("equity", 0),
            snapshot.get("wallet_balance", 0),
            snapshot.get("available_balance", 0),
            snapshot.get("unrealised_pnl", 0),
            snapshot.get("realised_pnl", 0),
            snapshot.get("positions_count", 0),
            snapshot.get("margin_used", 0),
            snapshot.get("cumulative_pnl", 0),
            snapshot.get("daily_return_pct", 0),
            snapshot.get("peak_equity", 0),
            snapshot.get("drawdown_pct", 0),
        )

    async def get_daily_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        sd = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        ed = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        rows = await self.pool.fetch(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 AND snapshot_date>=$2 AND snapshot_date<=$3 "
            "ORDER BY snapshot_date ASC",
            account_id, sd, ed,
        )
        return [dict(r) for r in rows]

    async def get_all_account_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sd = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        ed = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        sql = (
            "SELECT ds.* FROM daily_snapshots ds "
            "JOIN trading_accounts ta ON ta.id = ds.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND ds.snapshot_date>=$1 AND ds.snapshot_date<=$2 "
        )
        params: list = [sd, ed]
        if account_type:
            sql += "AND ta.account_type = $3 "
            params.append(account_type)
        sql += "ORDER BY ds.snapshot_date ASC"
        rows = await self.pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def get_latest_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 ORDER BY snapshot_date DESC LIMIT 1",
            account_id,
        )
        return dict(row) if row else None

    async def get_previous_snapshot(self, account_id: str, before_date: Any) -> Optional[Dict[str, Any]]:
        if isinstance(before_date, str):
            before_date = date.fromisoformat(before_date)
        row = await self.pool.fetchrow(
            "SELECT * FROM daily_snapshots "
            "WHERE account_id=$1 AND snapshot_date < $2 "
            "ORDER BY snapshot_date DESC LIMIT 1",
            account_id, before_date,
        )
        return dict(row) if row else None

    # ── High-Frequency Snapshots ──────────────────────────────────────

    async def get_hf_snapshots(
        self, account_id: str, since_ts: datetime,
    ) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM high_freq_snapshots "
            "WHERE account_id=$1 AND ts >= $2 "
            "ORDER BY ts ASC",
            account_id, since_ts,
        )
        return [dict(r) for r in rows]

    async def get_all_hf_snapshots(
        self, since_ts: datetime, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT hf.* FROM high_freq_snapshots hf "
            "JOIN trading_accounts ta ON ta.id = hf.account_id "
            "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
            "AND ta.include_in_analytics = TRUE "
            "AND hf.ts >= $1 "
        )
        params: list = [since_ts]
        if account_type:
            sql += "AND ta.account_type = $2 "
            params.append(account_type)
        sql += "ORDER BY hf.ts ASC"
        rows = await self.pool.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def insert_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        batch_ts = datetime.now(timezone.utc)
        args = [
            (s["account_id"], batch_ts, s["equity"], s["unrealised_pnl"],
             s["realised_pnl"], s["balance"], s.get("position_count", 0))
            for s in snapshots
        ]
        async with self._transaction() as conn:
            await conn.executemany(
                "INSERT INTO high_freq_snapshots "
                "(account_id, ts, equity, unrealised_pnl, realised_pnl, balance, position_count) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                args,
            )
        return len(args)

    _VALID_SNAPSHOT_TABLES = {"daily_snapshots", "high_freq_snapshots"}

    async def cleanup_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        idx = 0
        if account_id:
            idx += 1
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
        if before_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts < (${idx}::date + INTERVAL '1 day')")
            else:
                conditions.append(f"snapshot_date <= ${idx}")
            params.append(before_ts)
        if after_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts >= ${idx}::date")
            else:
                conditions.append(f"snapshot_date >= ${idx}")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        result = await self.pool.execute(
            f"DELETE FROM {table} WHERE {where}", *params
        )
        return int(result.split()[-1])

    async def cleanup_old_hf_snapshots(self, max_age_days: int = 1095) -> int:
        result = await self.pool.execute(
            "DELETE FROM high_freq_snapshots WHERE ts < NOW() - make_interval(days => $1)",
            max_age_days,
        )
        return int(result.split()[-1])

    async def count_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        idx = 0
        if account_id:
            idx += 1
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
        if before_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts < (${idx}::date + INTERVAL '1 day')")
            else:
                conditions.append(f"snapshot_date <= ${idx}")
            params.append(before_ts)
        if after_ts:
            idx += 1
            if is_hf:
                conditions.append(f"ts >= ${idx}::date")
            else:
                conditions.append(f"snapshot_date >= ${idx}")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        return await self.pool.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", *params
        )

    # ── Strategies ──────────────────────────────────────────────────

    async def insert_strategy(self, strategy: Dict[str, Any]) -> None:
        await self.pool.execute(
            "INSERT INTO strategies (id, name, description, category, status, config, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            strategy["id"], strategy["name"], strategy.get("description", ""),
            strategy.get("category", "swing"), strategy.get("status", "draft"),
            json.dumps(strategy.get("config", {})),
            strategy["created_at"], strategy["updated_at"],
        )

    async def list_strategies(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions = []
        params: list = []
        idx = 0
        if status:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)
        if category:
            idx += 1
            conditions.append(f"category = ${idx}")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "TRUE"
        rows = await self.pool.fetch(
            f"SELECT id, name, description, category, status, config, created_at, updated_at "
            f"FROM strategies WHERE {where} ORDER BY updated_at DESC",
            *params,
        )
        return [self._deserialize_strategy(r) for r in rows]

    async def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT id, name, description, category, status, config, created_at, updated_at "
            "FROM strategies WHERE id = $1",
            strategy_id,
        )
        if not row:
            return None
        return self._deserialize_strategy(row)

    async def update_strategy(self, strategy_id: str, **fields: Any) -> bool:
        allowed = {"name", "description", "category", "status", "config"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and not isinstance(updates["config"], str):
            updates["config"] = json.dumps(updates["config"])
        updates["updated_at"] = datetime.now(timezone.utc)
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k} = ${i}")
            params.append(v)
        params.append(strategy_id)
        result = await self.pool.execute(
            f"UPDATE strategies SET {', '.join(parts)} WHERE id = ${len(params)}",
            *params,
        )
        return int(result.split()[-1]) > 0

    async def delete_strategy(self, strategy_id: str) -> bool:
        result = await self.pool.execute(
            "DELETE FROM strategies WHERE id = $1", strategy_id
        )
        return int(result.split()[-1]) > 0

    # ── Scheduled Scans ──────────────────────────────────────────────

    async def insert_scheduled_scan(self, data: Dict[str, Any]) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO scheduled_scans "
                "(id, name, schedule_type, schedule_config, scan_config, status, "
                "timezone, next_run_at, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                data["id"],
                data["name"],
                data["schedule_type"],
                json.dumps(data["schedule_config"]),
                json.dumps(data["scan_config"]),
                data.get("status", "active"),
                data.get("timezone", "UTC"),
                data.get("next_run_at"),
                data["created_at"],
                data["updated_at"],
            )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"Scheduled scan {data['id']} already exists")

    async def update_scheduled_scan(self, schedule_id: str, fields: Dict[str, Any]) -> None:
        allowed = {
            "name", "schedule_type", "schedule_config", "scan_config",
            "status", "timezone", "next_run_at", "last_run_at",
            "last_scan_id", "consecutive_failures", "updated_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        for k in ("schedule_config", "scan_config"):
            if k in updates and isinstance(updates[k], dict):
                updates[k] = json.dumps(updates[k])
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(schedule_id)
        await self.pool.execute(
            f"UPDATE scheduled_scans SET {', '.join(parts)} WHERE id=${len(params)}",
            *params,
        )

    async def delete_scheduled_scan(self, schedule_id: str) -> bool:
        result = await self.pool.execute(
            "DELETE FROM scheduled_scans WHERE id=$1", schedule_id
        )
        return int(result.split()[-1]) > 0

    async def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM scheduled_scans ORDER BY created_at DESC"
        )
        return [self._deserialize_schedule(r) for r in rows]

    async def get_scheduled_scan(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT * FROM scheduled_scans WHERE id=$1", schedule_id
        )
        return self._deserialize_schedule(row) if row else None

    async def get_due_scheduled_scans(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = await self.pool.fetch(
            "SELECT * FROM scheduled_scans "
            "WHERE status='active' AND next_run_at <= $1 "
            "ORDER BY next_run_at ASC LIMIT 5",
            now,
        )
        return [self._deserialize_schedule(r) for r in rows]

    async def claim_scheduled_scan(
        self, schedule_id: str, old_next: str, new_next: Optional[str]
    ) -> bool:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self.pool.execute(
            "UPDATE scheduled_scans "
            "SET next_run_at=$1, last_run_at=$2, updated_at=$2 "
            "WHERE id=$3 AND next_run_at=$4 AND status='active'",
            new_next, now, schedule_id, old_next,
        )
        return int(result.split()[-1]) > 0

    async def insert_schedule_execution(self, data: Dict[str, Any]) -> int:
        return await self.pool.fetchval(
            "INSERT INTO schedule_executions "
            "(schedule_id, scan_id, status, started_at, completed_at, error_message) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            data["schedule_id"],
            data.get("scan_id"),
            data["status"],
            data["started_at"],
            data.get("completed_at"),
            data.get("error_message"),
        )

    async def update_schedule_execution(self, exec_id: int, fields: Dict[str, Any]) -> None:
        allowed = {"scan_id", "status", "completed_at", "error_message"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k}=${i}")
            params.append(v)
        params.append(exec_id)
        await self.pool.execute(
            f"UPDATE schedule_executions SET {', '.join(parts)} WHERE id=${len(params)}",
            *params,
        )

    async def list_schedule_executions(
        self, schedule_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            "SELECT * FROM schedule_executions "
            "WHERE schedule_id=$1 ORDER BY started_at DESC LIMIT $2",
            schedule_id, limit,
        )
        return [dict(r) for r in rows]

    async def cleanup_old_executions(self, days: int = 90, min_keep: int = 100) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self.pool.execute(
            "DELETE FROM schedule_executions "
            "WHERE started_at < $1 "
            "AND id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER (PARTITION BY schedule_id ORDER BY started_at DESC) AS rn "
            "    FROM schedule_executions"
            "  ) ranked WHERE rn <= $2"
            ")",
            cutoff, min_keep,
        )
        return int(result.split()[-1])

    async def update_scan_schedule_link(
        self, scan_id: str, schedule_id: str, triggered_by: str
    ) -> None:
        await self.pool.execute(
            "UPDATE scans SET schedule_id=$1, triggered_by=$2 WHERE scan_id=$3",
            schedule_id, triggered_by, scan_id,
        )

    async def count_scheduled_scans(self) -> int:
        return await self.pool.fetchval("SELECT COUNT(*) FROM scheduled_scans")

    async def mark_orphaned_executions(self) -> int:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self.pool.execute(
            "UPDATE schedule_executions SET status='failed', "
            "completed_at=$1, error_message='Server restarted during execution' "
            "WHERE status='started' AND started_at < $2",
            now, threshold,
        )
        return int(result.split()[-1])

    # ── Close Rules ──────────────────────────────────────────────

    async def insert_close_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "trigger_type", "threshold_value", "reference_value",
                "status", "expires_at", "cycle_id"]
        vals = {c: rule.get(c) for c in cols}
        if vals.get("status") is None:
            vals["status"] = "active"
        if vals.get("reference_value") is not None:
            ref_val = vals["reference_value"]
            if isinstance(ref_val, datetime):
                vals["reference_value"] = ref_val.isoformat()
            else:
                vals["reference_value"] = str(ref_val)
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(f"${i}" for i in range(1, len(vals) + 1))
        row = await self.pool.fetchrow(
            f"INSERT INTO close_rules ({col_names}) VALUES ({placeholders}) RETURNING *",
            *vals.values(),
        )
        return self._serialize_row(row)

    async def list_close_rules(self, account_id: str) -> list:
        rows = await self.pool.fetch(
            "SELECT * FROM close_rules WHERE account_id = $1 ORDER BY created_at DESC",
            account_id,
        )
        return [self._serialize_row(r) for r in rows]

    async def get_close_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT * FROM close_rules WHERE id = $1", rule_id
        )
        if not row:
            return None
        return self._serialize_row(row)

    async def update_close_rule(self, rule_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"trigger_type", "threshold_value", "reference_value", "status", "expires_at", "triggered_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return None
        if updates.get("reference_value") is not None:
            ref_val = updates["reference_value"]
            if isinstance(ref_val, datetime):
                updates["reference_value"] = ref_val.isoformat()
            else:
                updates["reference_value"] = str(ref_val)
        for dt_field in ("expires_at", "triggered_at"):
            if dt_field in updates and isinstance(updates[dt_field], str):
                updates[dt_field] = datetime.fromisoformat(updates[dt_field])
        updates["updated_at"] = datetime.now(timezone.utc)
        parts = []
        params = []
        for i, (k, v) in enumerate(updates.items(), 1):
            parts.append(f"{k} = ${i}")
            params.append(v)
        params.append(rule_id)
        row = await self.pool.fetchrow(
            f"UPDATE close_rules SET {', '.join(parts)} WHERE id = ${len(params)} RETURNING *",
            *params,
        )
        if not row:
            return None
        return self._serialize_row(row)

    async def atomic_trigger_rule(self, rule_id: str) -> bool:
        """Atomically set rule status to 'triggered' only if currently 'active'. Returns True if transitioned."""
        row = await self.pool.fetchrow(
            "UPDATE close_rules SET status = 'triggered', triggered_at = now(), updated_at = now() "
            "WHERE id = $1 AND status = 'active' RETURNING id",
            rule_id,
        )
        return row is not None

    async def deactivate_rules_for_account(self, account_id: str, exclude_rule_id: str | None = None) -> int:
        """Deactivate all active/paused rules for an account (e.g. after a rule triggers a close-all).
        Preserves PAUSE_TRADING and TRAILING_PROFIT rules which have independent lifecycles.
        Returns the number of rules deactivated."""
        type_exclusion = " AND trigger_type NOT IN ('PAUSE_TRADING', 'TRAILING_PROFIT')"
        if exclude_rule_id:
            result = await self.pool.execute(
                "UPDATE close_rules SET status = 'expired', updated_at = now() "
                "WHERE account_id = $1 AND id != $2 AND status IN ('active', 'paused', 'triggered')"
                + type_exclusion,
                account_id, exclude_rule_id,
            )
        else:
            result = await self.pool.execute(
                "UPDATE close_rules SET status = 'expired', updated_at = now() "
                "WHERE account_id = $1 AND status IN ('active', 'paused', 'triggered')"
                + type_exclusion,
                account_id,
            )
        return int(result.split()[-1])

    async def delete_close_rule(self, rule_id: str) -> bool:
        async with self._transaction() as conn:
            await conn.execute("DELETE FROM close_executions WHERE rule_id = $1", rule_id)
            result = await conn.execute("DELETE FROM close_rules WHERE id = $1", rule_id)
        return int(result.split()[-1]) > 0

    async def delete_all_rules_for_account(self, account_id: str, *, preserve_pause: bool = False) -> int:
        """Delete all close rules (and their executions) for an account."""
        type_filter = " AND trigger_type != 'PAUSE_TRADING'" if preserve_pause else ""
        async with self._transaction() as conn:
            await conn.execute(
                "DELETE FROM close_executions WHERE rule_id IN "
                f"(SELECT id FROM close_rules WHERE account_id = $1{type_filter})",
                account_id,
            )
            result = await conn.execute(
                f"DELETE FROM close_rules WHERE account_id = $1{type_filter}", account_id,
            )
        return int(result.split()[-1])

    async def delete_non_executed_rules_for_account(self, account_id: str) -> int:
        """Delete non-executed rules for an account (keeps executed ones for history)."""
        async with self._transaction() as conn:
            await conn.execute(
                "DELETE FROM close_executions WHERE rule_id IN "
                "(SELECT id FROM close_rules WHERE account_id = $1 AND status != 'executed')",
                account_id,
            )
            result = await conn.execute(
                "DELETE FROM close_rules WHERE account_id = $1 AND status != 'executed'",
                account_id,
            )
        return int(result.split()[-1])

    async def list_active_rules(self) -> list:
        """Fetch all active rules for non-deleted, active accounts."""
        rows = await self.pool.fetch(
            "SELECT cr.* FROM close_rules cr "
            "JOIN trading_accounts ta ON cr.account_id = ta.id "
            "WHERE cr.status = 'active' AND ta.deleted_at IS NULL "
            "AND ta.is_active = 1 "
            "AND (cr.expires_at IS NULL OR cr.expires_at > now()) "
            "ORDER BY cr.account_id, cr.created_at",
        )
        return [self._serialize_row(r) for r in rows]

    async def list_active_rules_for_account(self, account_id: str) -> list:
        """Fetch all active, non-expired rules for a specific account."""
        rows = await self.pool.fetch(
            "SELECT * FROM close_rules WHERE account_id = $1 AND status = 'active' "
            "AND (expires_at IS NULL OR expires_at > now()) "
            "ORDER BY created_at",
            account_id,
        )
        return [self._serialize_row(r) for r in rows]

    async def recover_stuck_triggered_rules(self, max_age_seconds: int = 120) -> int:
        """Revert rules stuck in 'triggered' state for longer than max_age_seconds."""
        result = await self.pool.execute(
            "UPDATE close_rules SET status = 'active', triggered_at = NULL "
            "WHERE status = 'triggered' "
            "AND triggered_at < now() - interval '1 second' * $1",
            max_age_seconds,
        )
        return int(result.split()[-1])

    async def count_active_rules_by_account(self) -> Dict[str, int]:
        """Return {account_id: count} for all accounts with active rules."""
        rows = await self.pool.fetch(
            "SELECT account_id::text, COUNT(*) as cnt FROM close_rules "
            "WHERE status = 'active' GROUP BY account_id",
        )
        return {r["account_id"]: r["cnt"] for r in rows}

    async def get_active_targets_by_account(self) -> Dict[str, list]:
        """Return {account_id: [{trigger_type, threshold_value, reference_value}]} for active rules."""
        rows = await self.pool.fetch(
            "SELECT account_id::text, trigger_type, threshold_value, reference_value "
            "FROM close_rules WHERE status = 'active' ORDER BY account_id, created_at",
        )
        result: Dict[str, list] = {}
        for r in rows:
            result.setdefault(r["account_id"], []).append({
                "trigger_type": r["trigger_type"],
                "threshold_value": str(r["threshold_value"]) if r["threshold_value"] is not None else None,
                "reference_value": str(r["reference_value"]) if r["reference_value"] is not None else None,
            })
        return result

    async def count_rules_for_account(self, account_id: str) -> int:
        return await self.pool.fetchval(
            "SELECT COUNT(*) FROM close_rules WHERE account_id = $1 AND status IN ('active', 'paused')",
            account_id,
        )

    # ── Close Executions ─────────────────────────────────────────

    async def insert_close_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        cols = ["account_id", "rule_id", "trigger_source", "total_positions",
                "closed_count", "failed_count", "results"]
        vals = {c: execution.get(c) for c in cols}
        if vals.get("results") is not None and not isinstance(vals["results"], str):
            vals["results"] = json.dumps(vals["results"])
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(f"${i}" for i in range(1, len(vals) + 1))
        row = await self.pool.fetchrow(
            f"INSERT INTO close_executions ({col_names}) VALUES ({placeholders}) RETURNING *",
            *vals.values(),
        )
        return self._serialize_row(row)

    async def list_close_executions(self, account_id: str, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        offset = (page - 1) * limit
        total = await self.pool.fetchval(
            "SELECT COUNT(*) FROM close_executions WHERE account_id = $1",
            account_id,
        )
        rows = await self.pool.fetch(
            "SELECT * FROM close_executions WHERE account_id = $1 "
            "ORDER BY executed_at DESC LIMIT $2 OFFSET $3",
            account_id, limit, offset,
        )
        return {
            "items": [self._serialize_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }
