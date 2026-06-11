"""PostgreSQL persistence layer with migration framework and connection resilience."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Generator, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

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


def _schema_v26_triggers_sync(cur) -> None:
    cur.execute("""
        CREATE OR REPLACE FUNCTION update_trades_updated_at() RETURNS TRIGGER AS $t$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $t$ LANGUAGE plpgsql
    """)
    cur.execute("""
        CREATE TRIGGER trg_trades_updated_at BEFORE UPDATE ON trades
        FOR EACH ROW EXECUTE FUNCTION update_trades_updated_at()
    """)
    cur.execute("""
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
    cur.execute("""
        CREATE TRIGGER trg_trade_events_immutable BEFORE UPDATE OR DELETE ON trade_events
        FOR EACH ROW EXECUTE FUNCTION prevent_trade_events_mutation()
    """)
def _fix_source_constraint_sync(cur) -> None:
    """Drop all CHECK constraints on trades.source column and re-add with correct values."""
    cur.execute("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute att ON att.attnum = ANY(con.conkey) AND att.attrelid = con.conrelid
        WHERE con.conrelid = 'trades'::regclass
          AND att.attname = 'source'
          AND con.contype = 'c'
          AND con.conname != 'chk_source_id'
    """)
    rows = cur.fetchall()
    for row in rows:
        conname = row[0] if isinstance(row, (tuple, list)) else row["conname"]
        cur.execute(f'ALTER TABLE trades DROP CONSTRAINT {conname}')
    cur.execute(
        "ALTER TABLE trades ADD CONSTRAINT trades_source_check "
        "CHECK (source IN ('manual', 'cycle', 'scanner'))"
    )


def _fix_close_rules_constraints_sync(cur) -> None:
    # 1. Find and drop existing check constraints on close_rules.trigger_type
    cur.execute("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute att ON att.attnum = ANY(con.conkey) AND att.attrelid = con.conrelid
        WHERE con.conrelid = 'close_rules'::regclass
          AND att.attname = 'trigger_type'
          AND con.contype = 'c'
    """)
    rows = cur.fetchall()
    for row in rows:
        conname = row[0] if isinstance(row, (tuple, list)) else row["conname"]
        cur.execute(f'ALTER TABLE close_rules DROP CONSTRAINT {conname}')

    # 2. Add new check constraint allowing BREAKEVEN_TIMEOUT and MAX_DURATION
    cur.execute("""
        ALTER TABLE close_rules ADD CONSTRAINT close_rules_trigger_type_check
        CHECK (trigger_type IN (
            'BALANCE_BELOW', 'BALANCE_ABOVE',
            'EQUITY_DROP_PCT', 'EQUITY_RISE_PCT',
            'PNL_BELOW', 'PNL_ABOVE',
            'BREAKEVEN_TIMEOUT', 'MAX_DURATION'
        ))
    """)

    # 3. Alter reference_value column to VARCHAR(100)
    cur.execute("ALTER TABLE close_rules ALTER COLUMN reference_value TYPE VARCHAR(100)")


_MIGRATIONS: list[tuple[int, "str | Callable[[Any], None]"]] = [
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
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','triggered','executed','expired')),
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
    (26, _schema_v26_triggers_sync),
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
    (31, _fix_source_constraint_sync),
    (32, _fix_close_rules_constraints_sync),
    (33, """
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
    (34, """
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
    (35, """
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
]
def _default_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://user:pass@localhost:5432/tradingagents"
        )
    return dsn


class AnalysisDB:
    """Synchronous (psycopg2) persistence layer — twin of AsyncAnalysisDB.

    Used by graph-executor threads and legacy/test paths. The async layer owns
    schema migrations in production; this sync layer is a coexisting consumer and
    skips migrating past its own version tail. Wraps a threaded connection pool.
    """

    _POOL_MAX = max(2, min(200, int(os.environ.get("DB_POOL_MAX", "20") or "20")))
    _POOL_TIMEOUT = max(5, min(300, int(os.environ.get("DB_POOL_TIMEOUT", "30") or "30")))

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _default_dsn()
        self._instance_id = str(uuid.uuid4())
        self._closed = False
        self._lock = threading.Lock()
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=self._POOL_MAX,
            dsn=self._dsn,
            connect_timeout=10,
        )
        self._semaphore = threading.Semaphore(self._POOL_MAX)
        try:
            self._apply_migrations()
        except Exception:
            self._pool.closeall()
            raise

    @contextmanager
    def _get_conn(self) -> Generator[Any, None, None]:
        if self._closed:
            raise psycopg2.pool.PoolError("database pool is shutting down")
        if not self._semaphore.acquire(timeout=self._POOL_TIMEOUT):
            raise psycopg2.pool.PoolError(
                f"Timed out waiting for a database connection ({self._POOL_TIMEOUT}s)"
            )
        try:
            conn = self._pool.getconn()
        except Exception:
            self._semaphore.release()
            raise
        try:
            yield conn
        finally:
            try:
                if conn.closed:
                    self._pool.putconn(conn, close=True)
                else:
                    conn.rollback()
                    self._pool.putconn(conn)
            except Exception:
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
            finally:
                self._semaphore.release()

    def _apply_migrations(self) -> None:
        with self._get_conn() as conn:
            conn.autocommit = False
            cur = conn.cursor()
            try:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version "
                    "(version INTEGER NOT NULL DEFAULT 0)"
                )
                conn.commit()

                # Advisory lock prevents concurrent migration from multiple instances
                cur.execute("SELECT pg_advisory_lock(8675309)")
                try:
                    cur.execute("SELECT version FROM schema_version")
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("INSERT INTO schema_version (version) VALUES (0)")
                        conn.commit()
                        current = 0
                    else:
                        current = row[0]

                    max_version = _MIGRATIONS[-1][0] if _MIGRATIONS else 0
                    if current > max_version:
                        # The async layer (AsyncAnalysisDB) is the sole migration
                        # OWNER in production and is ahead of this sync consumer's
                        # migration list. Do NOT raise — the sync path is a
                        # read-only consumer (tests/legacy) and must coexist with a
                        # DB already migrated past its own _MIGRATIONS tail.
                        logger.warning(
                            "sync persistence: DB schema v%s newer than sync max v%s; "
                            "skipping sync migrations (async layer owns schema)",
                            current, max_version,
                        )
                        return

                    if current >= max_version:
                        return

                    for version, sql in _MIGRATIONS:
                        if version <= current:
                            continue
                        try:
                            if callable(sql):
                                sql(cur)
                            else:
                                for stmt in sql.split(";"):
                                    stmt = stmt.strip()
                                    if stmt:
                                        cur.execute(stmt)
                            cur.execute(
                                "UPDATE schema_version SET version = %s", (version,)
                            )
                            conn.commit()
                        except Exception:
                            conn.rollback()
                            raise
                finally:
                    try:
                        cur.execute("SELECT pg_advisory_unlock(8675309)")
                        conn.commit()
                    except Exception:
                        pass
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def insert_run(self, run: Dict[str, Any]) -> None:
        """Insert a new analysis run; raises ValueError if the run_id already exists."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO analysis_runs "
                    "(run_id, ticker, analysis_date, status, config, started_at, instance_id, asset_type) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        run["run_id"],
                        run["ticker"],
                        run["analysis_date"],
                        run["status"],
                        run.get("config", "{}"),
                        run["started_at"],
                        self._instance_id,
                        run.get("asset_type", "stock"),
                    ),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise ValueError(f"Run {run['run_id']} already exists") from None
            except Exception:
                conn.rollback()
                raise

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        completed_at: Optional[str],
    ) -> bool:
        """Update a run's status/error/completed_at only if still 'running'.

        Returns True if a row was updated (i.e. it was running), False otherwise.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE analysis_runs SET status=%s, error=%s, completed_at=%s "
                    "WHERE run_id=%s AND status='running'",
                    (status, error, completed_at, run_id),
                )
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def save_report_section(self, run_id: str, section: str, content: str) -> None:
        """Upsert a report section for a run (idempotent on run_id+section)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO report_sections (run_id, section, content) VALUES (%s, %s, %s) "
                    "ON CONFLICT (run_id, section) DO UPDATE SET content = EXCLUDED.content",
                    (run_id, section, content),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a single analysis run row, or None if not found."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM analysis_runs WHERE run_id=%s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            except Exception:
                conn.rollback()
                raise

    def list_runs(
        self,
        page: int = 1,
        limit: int = 20,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a paginated, filtered list of analysis runs (newest first).

        Supports ticker/status/asset_type and analysis_date from/to filters.
        Returns {"items", "total", "page", "limit"}.
        """
        limit = min(max(limit, 1), 500)
        conditions: list[str] = []
        params: list[Any] = []

        if ticker:
            conditions.append("ticker = %s")
            params.append(ticker)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if from_date:
            conditions.append("analysis_date >= %s")
            params.append(from_date)
        if to_date:
            conditions.append("analysis_date <= %s")
            params.append(to_date)
        if asset_type:
            conditions.append("asset_type = %s")
            params.append(asset_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * limit

        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"SELECT COUNT(*) as cnt FROM analysis_runs {where}", params
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"SELECT run_id, ticker, analysis_date, status, started_at, "
                    f"completed_at, asset_type, config FROM analysis_runs {where} "
                    f"ORDER BY started_at DESC LIMIT %s OFFSET %s",
                    params + [limit, offset],
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def get_report_sections(self, run_id: str) -> List[Dict[str, Any]]:
        """Return all report sections for a run, ordered by insertion id."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM report_sections WHERE run_id=%s ORDER BY id",
                    (run_id,),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def recover_orphans(self) -> int:
        """Mark all still-'running' runs as failed (startup crash recovery); return the count."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE analysis_runs SET status='failed', "
                    "error='Server restarted — orphaned run' "
                    "WHERE status='running'"
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def get_checkpoint_exists(self, ticker: str, date: str) -> bool:
        """Return True if any analysis run exists for the given ticker and date."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT 1 FROM analysis_runs WHERE ticker=%s AND analysis_date=%s LIMIT 1",
                    (ticker, date),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row is not None

    def delete_run(self, run_id: str) -> bool:
        """Delete a single analysis run; return True if a row was removed."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM analysis_runs WHERE run_id=%s", (run_id,))
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def delete_all_runs(self) -> int:
        """Delete every analysis run; return the number deleted."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM analysis_runs")
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def delete_all_checkpoints(self) -> int:
        """Delete all completed/failed/cancelled runs; return the number deleted."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM analysis_runs "
                    "WHERE status IN ('completed', 'failed', 'cancelled')"
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def delete_ticker_checkpoints(self, ticker: str) -> int:
        """Delete completed/failed/cancelled runs for one ticker; return the count."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM analysis_runs "
                    "WHERE ticker=%s AND status IN ('completed', 'failed', 'cancelled')",
                    (ticker,),
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def checkpoint(self) -> None:
        """No-op checkpoint hook (kept for interface compatibility)."""

    def health_check(self) -> str:
        """Return "ok" if a trivial query succeeds, else "degraded"."""
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                conn.rollback()
            return "ok"
        except Exception:
            return "degraded"

    # ── Scanner persistence ──────────────────────────────────────────

    def insert_scan(self, scan: Dict[str, Any]) -> None:
        """Insert a new market-scan row."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scans "
                    "(scan_id, status, config, total, completed, failed, started_at, schedule_id, triggered_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        scan["scan_id"],
                        scan.get("status", "running"),
                        scan.get("config", "{}"),
                        scan.get("total", 0),
                        scan.get("completed", 0),
                        scan.get("failed", 0),
                        scan["started_at"],
                        scan.get("schedule_id"),
                        scan.get("triggered_by", "manual"),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        """Update allowed scan columns; ignores unknown fields and no-ops if none."""
        allowed = {"status", "total", "completed", "failed", "completed_at", "auto_trade_results", "auto_trade_summaries", "config"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scans SET {set_clause} WHERE scan_id=%s",
                    list(updates.values()) + [scan_id],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def insert_scan_result(self, scan_id: str, result: Dict[str, Any]) -> None:
        """Upsert a per-ticker scan result (idempotent on scan_id+ticker).

        Defensively validates/clamps direction, confidence, score (-10..10), and
        status before persisting.
        """
        direction = result.get("direction", "hold")
        if direction not in ("buy", "sell", "hold"):
            logger.error(
                "insert_scan_result: invalid direction %r — forcing hold", direction
            )
            direction = "hold"
        confidence = result.get("confidence", "none")
        if confidence not in ("high", "moderate", "low", "none"):
            logger.error(
                "insert_scan_result: invalid confidence %r — forcing none", confidence
            )
            confidence = "none"
        score = int(result.get("score", 0))
        score = max(-10, min(10, score))
        status = result.get("status", "failed")
        if status not in ("completed", "failed", "cancelled", "unknown"):
            logger.warning("insert_scan_result: invalid status %r — forcing unknown", status)
            status = "unknown"

        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scan_results "
                    "(scan_id, ticker, run_id, status, direction, confidence, "
                    "score, decision_summary, signal_source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (scan_id, ticker) DO UPDATE SET "
                    "run_id = EXCLUDED.run_id, status = EXCLUDED.status, "
                    "direction = EXCLUDED.direction, confidence = EXCLUDED.confidence, "
                    "score = EXCLUDED.score, decision_summary = EXCLUDED.decision_summary, "
                    "signal_source = EXCLUDED.signal_source",
                    (
                        scan_id,
                        result["ticker"],
                        result.get("run_id"),
                        status,
                        direction,
                        confidence,
                        score,
                        result.get("decision_summary", ""),
                        result.get("signal_source", "unknown"),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Return a scan with its results (ordered by |score|), or None if not found.

        Adds a skipped_count of results that came from the TA prefilter.
        """
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scans WHERE scan_id=%s", (scan_id,))
                row = cur.fetchone()
                if not row:
                    return None
                scan = dict(row)
                cur.execute(
                    "SELECT ticker, run_id, status, direction, confidence, score, "
                    "decision_summary, signal_source "
                    "FROM scan_results WHERE scan_id=%s ORDER BY ABS(score) DESC",
                    (scan_id,),
                )
                results = cur.fetchall()
                scan["results"] = [dict(r) for r in results]
                scan["skipped_count"] = sum(
                    1 for r in scan["results"] if r.get("signal_source") == "ta_prefilter"
                )
            except Exception:
                conn.rollback()
                raise
        return scan

    def list_scans(self) -> List[Dict[str, Any]]:
        """Return the 50 most recent scans with per-direction and skipped counts.

        Results lists are left empty; each scan carries direction_counts and
        skipped_count aggregates instead.
        """
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT scan_id, status, config, total, completed, failed, "
                    "started_at, completed_at, schedule_id, triggered_by "
                    "FROM scans ORDER BY started_at DESC LIMIT 50"
                )
                rows = cur.fetchall()
                scans = [dict(r) for r in rows]
                if not scans:
                    return []
                scan_ids = [s["scan_id"] for s in scans]
                cur.execute(
                    "SELECT scan_id, direction, COUNT(*) as cnt "
                    "FROM scan_results WHERE scan_id = ANY(%s) "
                    "GROUP BY scan_id, direction",
                    (scan_ids,),
                )
                counts = cur.fetchall()
                counts_by_scan: Dict[str, Dict[str, int]] = {s["scan_id"]: {} for s in scans}
                for row in counts:
                    counts_by_scan[row["scan_id"]][row["direction"]] = row["cnt"]
                cur.execute(
                    "SELECT scan_id, COUNT(*) as cnt "
                    "FROM scan_results "
                    "WHERE scan_id = ANY(%s) AND signal_source = 'ta_prefilter' "
                    "GROUP BY scan_id",
                    (scan_ids,),
                )
                skipped_rows = cur.fetchall()
                skipped_by_scan: Dict[str, int] = {row["scan_id"]: row["cnt"] for row in skipped_rows}
                for scan in scans:
                    scan["results"] = []
                    scan["direction_counts"] = counts_by_scan.get(scan["scan_id"], {})
                    scan["skipped_count"] = skipped_by_scan.get(scan["scan_id"], 0)
            except Exception:
                conn.rollback()
                raise
        return scans

    def get_scan_completed_tickers(self, scan_id: str) -> set[str]:
        """Return the set of tickers that already have a result row for a scan."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT ticker FROM scan_results WHERE scan_id=%s", (scan_id,)
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {r[0] for r in rows}

    def increment_scan_counter(self, scan_id: str, field: str) -> None:
        """Increment a scan's 'completed' or 'failed' counter by one (ignores others)."""
        if field not in ("completed", "failed"):
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scans SET {field} = {field} + 1 WHERE scan_id=%s",
                    (scan_id,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_running_scans(self) -> List[Dict[str, Any]]:
        """Return all scans currently in 'running' status."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scans WHERE status='running'")
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def delete_scan(self, scan_id: str) -> Dict[str, Any]:
        """Delete a scan and cascade-delete its associated analysis runs.

        Returns dict with counts: {deleted_results, deleted_analyses, deleted_sections}.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT run_id FROM scan_results WHERE scan_id=%s AND run_id IS NOT NULL",
                    (scan_id,),
                )
                run_ids = [r[0] for r in cur.fetchall()]

                deleted_sections = 0
                deleted_analyses = 0
                if run_ids:
                    cur.execute(
                        "DELETE FROM report_sections WHERE run_id = ANY(%s)",
                        (run_ids,),
                    )
                    deleted_sections = cur.rowcount
                    cur.execute(
                        "DELETE FROM analysis_runs WHERE run_id = ANY(%s)",
                        (run_ids,),
                    )
                    deleted_analyses = cur.rowcount

                cur.execute("DELETE FROM scan_results WHERE scan_id=%s", (scan_id,))
                deleted_results = cur.rowcount

                cur.execute("DELETE FROM scans WHERE scan_id=%s", (scan_id,))
                scan_deleted = cur.rowcount

                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if scan_deleted == 0:
            return {}
        return {
            "deleted_results": deleted_results,
            "deleted_analyses": deleted_analyses,
            "deleted_sections": deleted_sections,
        }

    def get_scan_analysis_count(self, scan_id: str) -> int:
        """Return the number of scan results that have a linked analysis run_id."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM scan_results WHERE scan_id=%s AND run_id IS NOT NULL",
                    (scan_id,),
                )
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        """Mark the DB closed and close all pooled connections."""
        self._closed = True
        self._pool.closeall()

    # ── Trading Accounts persistence ────────────────────────────────────

    def insert_account(self, account: Dict[str, Any]) -> None:
        """Insert a new trading account row (encrypted credentials included)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO trading_accounts "
                    "(id, label, account_type, api_key_masked, api_key_encrypted, "
                    "api_secret_encrypted, key_version, is_active, bybit_uid, "
                    "last_connected_at, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
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
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Return all non-deleted trading accounts (no secrets), newest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, label, account_type, api_key_masked, is_active, "
                    "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
                    "include_in_analytics "
                    "FROM trading_accounts WHERE deleted_at IS NULL "
                    "ORDER BY created_at DESC"
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Return a single non-deleted account (no secrets), or None if absent."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, label, account_type, api_key_masked, is_active, "
                    "bybit_uid, last_connected_at, last_error, created_at, updated_at, "
                    "include_in_analytics "
                    "FROM trading_accounts WHERE id=%s AND deleted_at IS NULL",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def get_account_credentials(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Return an account's encrypted API key/secret, or None if absent."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, account_type, api_key_encrypted, api_secret_encrypted "
                    "FROM trading_accounts WHERE id=%s AND deleted_at IS NULL",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def update_account(self, account_id: str, **fields: Any) -> bool:
        """Update allowed account fields; return True if a row was updated.

        Filters to a column allowlist (only last_error may be set NULL), stamps
        updated_at, and no-ops (returns False) when nothing updatable is given.
        """
        allowed = {"label", "is_active", "bybit_uid", "last_connected_at", "last_error", "include_in_analytics"}
        nullable = {"last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed and (v is not None or k in nullable)}
        if not updates:
            return False
        updates["updated_at"] = fields.get("updated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE trading_accounts SET {set_clause} WHERE id=%s AND deleted_at IS NULL",
                    list(updates.values()) + [account_id],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    def rotate_account_credentials(
        self, account_id: str, api_key_masked: str,
        api_key_encrypted: bytes, api_secret_encrypted: bytes, updated_at: str,
    ) -> bool:
        """Replace an account's encrypted API key/secret and clear last_error.

        Returns True if a non-deleted account row was updated.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE trading_accounts SET api_key_masked=%s, api_key_encrypted=%s, "
                    "api_secret_encrypted=%s, last_error=NULL, updated_at=%s "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (api_key_masked, api_key_encrypted, api_secret_encrypted, updated_at, account_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    def soft_delete_account(self, account_id: str, deleted_at: str) -> bool:
        """Soft-delete an account (set deleted_at, deactivate); return True if updated."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE trading_accounts SET deleted_at=%s, is_active=0, updated_at=%s "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (deleted_at, deleted_at, account_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return cur.rowcount > 0

    # ── Closed PnL persistence ──────────────────────────────────────────

    def insert_closed_pnl_records(self, account_id: str, records: List[Dict[str, Any]]) -> int:
        """Insert closed-PnL records for an account; return how many were inserted.

        Idempotent per (account_id, bybit_order_id) — duplicates are skipped, and
        individual malformed records are logged and skipped without aborting.
        """
        if not records:
            return 0
        inserted = 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                for rec in records:
                    try:
                        cur.execute(
                            "INSERT INTO closed_pnl_records "
                            "(account_id, symbol, side, qty, avg_entry_price, avg_exit_price, "
                            "closed_pnl, leverage, created_time, bybit_order_id) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                            "ON CONFLICT (account_id, bybit_order_id) DO NOTHING",
                            (
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
                            ),
                        )
                        inserted += cur.rowcount
                    except (KeyError, TypeError, ValueError) as e:
                        logger.warning("Skipping closed PnL record: %s — %s", type(e).__name__, e)
                    except Exception:
                        logger.debug("Duplicate or DB error inserting PnL record", exc_info=True)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted

    def get_closed_pnl(
        self, account_id: str, start_time: int, end_time: int,
        page: int = 1, limit: int = 100,
    ) -> Dict[str, Any]:
        """Return paginated closed-PnL records in a time window (newest first).

        Returns {"items", "total", "page", "limit"}.
        """
        offset = (page - 1) * limit
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s",
                    (account_id, start_time, end_time),
                )
                total = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT * FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s "
                    "ORDER BY created_time DESC LIMIT %s OFFSET %s",
                    (account_id, start_time, end_time, limit, offset),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    def get_closed_pnl_summary(
        self, account_id: str, start_time: int, end_time: int,
    ) -> Dict[str, Any]:
        """Aggregate one account's closed PnL in a window into win/loss summary stats.

        Returns total/average win-loss figures and win rate; zeros when no records.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT closed_pnl FROM closed_pnl_records "
                    "WHERE account_id=%s AND created_time>=%s AND created_time<=%s",
                    (account_id, start_time, end_time),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }

        wins = [r[0] for r in rows if r[0] > 0]
        losses = [r[0] for r in rows if r[0] < 0]
        total_pnl = sum(r[0] for r in rows)
        total_count = len(rows)
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

    def get_portfolio_pnl_summary(
        self, start_time: int, end_time: int,
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate closed PnL across all analytics-eligible accounts in a window.

        Restricts to active, non-deleted, analytics-included accounts (optionally
        one account_type). Returns the same win/loss summary shape as the
        per-account summary.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                sql = (
                    "SELECT cpr.closed_pnl FROM closed_pnl_records cpr "
                    "JOIN trading_accounts ta ON ta.id = cpr.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND cpr.created_time>=%s AND cpr.created_time<=%s"
                )
                params: list = [start_time, end_time]
                if account_type:
                    sql += " AND ta.account_type = %s"
                    params.append(account_type)
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise

        if not rows:
            return {
                "total_pnl": "0", "win_count": 0, "loss_count": 0,
                "win_rate": 0.0, "avg_win": "0", "avg_loss": "0",
            }

        wins = [r[0] for r in rows if r[0] > 0]
        losses = [r[0] for r in rows if r[0] < 0]
        total_pnl = sum(r[0] for r in rows)
        total_count = len(rows)
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

    def get_latest_closed_pnl_time(self, account_id: str) -> Optional[int]:
        """Return the max created_time of an account's closed PnL records, or None."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT MAX(created_time) FROM closed_pnl_records WHERE account_id=%s",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row[0] if row and row[0] else None

    # ── Daily Snapshots ────────────────────────────────────────────────

    def upsert_daily_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Insert or update a daily equity snapshot (keyed on account + date)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO daily_snapshots "
                    "(account_id, snapshot_date, equity, wallet_balance, available_balance, "
                    "unrealised_pnl, realised_pnl, positions_count, margin_used, "
                    "cumulative_pnl, daily_return_pct, peak_equity, drawdown_pct) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
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
                    (
                        snapshot["account_id"],
                        snapshot["snapshot_date"],
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
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_daily_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        """Return one account's daily snapshots in a date range, oldest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s AND snapshot_date>=%s AND snapshot_date<=%s "
                    "ORDER BY snapshot_date ASC",
                    (account_id, start_date, end_date),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_all_account_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return daily snapshots for all analytics-eligible accounts in a date range.

        Restricts to active, non-deleted, analytics-included accounts (optionally
        one account_type); ordered oldest first.
        """
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                sql = (
                    "SELECT ds.* FROM daily_snapshots ds "
                    "JOIN trading_accounts ta ON ta.id = ds.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND ds.snapshot_date>=%s AND ds.snapshot_date<=%s "
                )
                params: list = [start_date, end_date]
                if account_type:
                    sql += "AND ta.account_type = %s "
                    params.append(account_type)
                sql += "ORDER BY ds.snapshot_date ASC"
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_latest_snapshot(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Return an account's most recent daily snapshot, or None if none exist."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s ORDER BY snapshot_date DESC LIMIT 1",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    def get_previous_snapshot(self, account_id: str, before_date: str) -> Optional[Dict[str, Any]]:
        """Return an account's latest daily snapshot strictly before a date, or None."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM daily_snapshots "
                    "WHERE account_id=%s AND snapshot_date < %s "
                    "ORDER BY snapshot_date DESC LIMIT 1",
                    (account_id, before_date),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return dict(row) if row else None

    # ── High-Frequency Snapshots ──────────────────────────────────────

    def get_hf_snapshots(
        self, account_id: str, since_ts: datetime,
    ) -> List[Dict[str, Any]]:
        """Return one account's high-frequency snapshots since a timestamp, oldest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM high_freq_snapshots "
                    "WHERE account_id=%s AND ts >= %s "
                    "ORDER BY ts ASC",
                    (account_id, since_ts),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def get_all_hf_snapshots(
        self, since_ts: datetime, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return high-frequency snapshots for all analytics-eligible accounts since a timestamp.

        Restricts to active, non-deleted, analytics-included accounts (optionally
        one account_type); ordered oldest first.
        """
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                sql = (
                    "SELECT hf.* FROM high_freq_snapshots hf "
                    "JOIN trading_accounts ta ON ta.id = hf.account_id "
                    "WHERE ta.deleted_at IS NULL AND ta.is_active = 1 "
                    "AND ta.include_in_analytics = TRUE "
                    "AND hf.ts >= %s "
                )
                params: list = [since_ts]
                if account_type:
                    sql += "AND ta.account_type = %s "
                    params.append(account_type)
                sql += "ORDER BY hf.ts ASC"
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [dict(r) for r in rows]

    def insert_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        """Batch-insert high-frequency snapshots with a shared timestamp; return the count."""
        if not snapshots:
            return 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                batch_ts = datetime.now(timezone.utc)
                args = [
                    (s["account_id"], batch_ts, s["equity"], s["unrealised_pnl"],
                     s["realised_pnl"], s["balance"], s.get("position_count", 0))
                    for s in snapshots
                ]
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO high_freq_snapshots "
                    "(account_id, ts, equity, unrealised_pnl, realised_pnl, balance, position_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    args,
                )
                conn.commit()
                return len(args)
            except Exception:
                conn.rollback()
                raise

    _VALID_SNAPSHOT_TABLES = {"daily_snapshots", "high_freq_snapshots"}

    def cleanup_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        """Delete snapshot rows matching optional account/time bounds; return the count.

        Validates table against the snapshot-table allowlist (ValueError otherwise)
        and applies the correct date/timestamp column per table.
        """
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        if before_ts:
            if is_hf:
                conditions.append("ts < (%s::date + INTERVAL '1 day')")
            else:
                conditions.append("snapshot_date <= %s")
            params.append(before_ts)
        if after_ts:
            if is_hf:
                conditions.append("ts >= %s::date")
            else:
                conditions.append("snapshot_date >= %s")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"DELETE FROM {table} WHERE {where}", params)
                count = cur.rowcount
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    def cleanup_old_hf_snapshots(self, max_age_days: int = 1095) -> int:
        """Delete high-frequency snapshots older than max_age_days; return the count."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM high_freq_snapshots WHERE ts < NOW() - %s * INTERVAL '1 day'",
                    (max_age_days,),
                )
                count = cur.rowcount
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise

    def count_snapshots(
        self,
        account_id: Optional[str],
        before_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        table: str = "daily_snapshots",
    ) -> int:
        """Count snapshot rows matching optional account/time bounds.

        Validates table against the snapshot-table allowlist (ValueError otherwise)
        and applies the correct date/timestamp column per table.
        """
        if table not in self._VALID_SNAPSHOT_TABLES:
            raise ValueError(f"Invalid table: {table}")
        is_hf = table == "high_freq_snapshots"
        conditions: list[str] = []
        params: list = []
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        if before_ts:
            if is_hf:
                conditions.append("ts < (%s::date + INTERVAL '1 day')")
            else:
                conditions.append("snapshot_date <= %s")
            params.append(before_ts)
        if after_ts:
            if is_hf:
                conditions.append("ts >= %s::date")
            else:
                conditions.append("snapshot_date >= %s")
            params.append(after_ts)
        if not conditions:
            conditions.append("TRUE")
        where = " AND ".join(conditions)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params)
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    # ── Strategies ──────────────────────────────────────────────────

    @staticmethod
    def _deserialize_strategy(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("config"), str):
            d["config"] = json.loads(d["config"])
        return d

    def insert_strategy(self, strategy: Dict[str, Any]) -> None:
        """Insert a new strategy row (config JSON-serialized)."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO strategies (id, name, description, category, status, config, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        strategy["id"], strategy["name"], strategy.get("description", ""),
                        strategy.get("category", "swing"), strategy.get("status", "draft"),
                        json.dumps(strategy.get("config", {})),
                        strategy["created_at"], strategy["updated_at"],
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_strategies(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return strategies (config deserialized) filtered by optional status/category, newest first."""
        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if category:
            conditions.append("category = %s")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "TRUE"
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(f"SELECT id, name, description, category, status, config, created_at, updated_at FROM strategies WHERE {where} ORDER BY updated_at DESC", params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [self._deserialize_strategy(r) for r in rows]

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return one strategy (config deserialized), or None if not found."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT id, name, description, category, status, config, created_at, updated_at FROM strategies WHERE id = %s", (strategy_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._deserialize_strategy(row)

    def update_strategy(self, strategy_id: str, **fields: Any) -> bool:
        """Update allowed strategy fields; return True if a row changed.

        Serializes config to JSON, stamps updated_at, and no-ops (returns False)
        when no updatable field is given.
        """
        allowed = {"name", "description", "category", "status", "config"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and not isinstance(updates["config"], str):
            updates["config"] = json.dumps(updates["config"])
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE strategies SET {set_clause} WHERE id = %s",
                    list(updates.values()) + [strategy_id],
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def delete_strategy(self, strategy_id: str) -> bool:
        """Delete a strategy by id; return True if a row was removed."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    # ── Scheduled Scans ──────────────────────────────────────────────

    def insert_scheduled_scan(self, data: Dict[str, Any]) -> None:
        """Insert a scheduled scan; raises ValueError if its id already exists."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO scheduled_scans "
                    "(id, name, schedule_type, schedule_config, scan_config, status, "
                    "timezone, next_run_at, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
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
                    ),
                )
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise ValueError(f"Scheduled scan {data['id']} already exists") from None
            except Exception:
                conn.rollback()
                raise

    def update_scheduled_scan(self, schedule_id: str, fields: Dict[str, Any]) -> None:
        """Update allowed scheduled-scan columns; JSON-encodes config dicts and no-ops if none."""
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
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE scheduled_scans SET {set_clause} WHERE id=%s",
                    (*updates.values(), schedule_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_scheduled_scan(self, schedule_id: str) -> bool:
        """Delete a scheduled scan by id; return True if a row was removed."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM scheduled_scans WHERE id=%s", (schedule_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def list_scheduled_scans(self) -> List[Dict[str, Any]]:
        """Return all scheduled scans (configs deserialized), newest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM scheduled_scans ORDER BY created_at DESC"
                )
                return [self._deserialize_schedule(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _deserialize_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        for k in ("schedule_config", "scan_config"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        return d

    def get_scheduled_scan(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Return one scheduled scan (configs deserialized), or None if not found."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM scheduled_scans WHERE id=%s", (schedule_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return self._deserialize_schedule(row) if row else None

    def get_due_scheduled_scans(self) -> List[Dict[str, Any]]:
        """Return up to 5 active scheduled scans whose next_run_at is now due."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM scheduled_scans "
                    "WHERE status='active' AND next_run_at <= %s "
                    "ORDER BY next_run_at ASC LIMIT 5",
                    (now,),
                )
                return [self._deserialize_schedule(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    def claim_scheduled_scan(
        self, schedule_id: str, old_next: str, new_next: Optional[str]
    ) -> bool:
        """Atomically claim a due scheduled scan via compare-and-swap on next_run_at.

        Advances next_run_at to new_next and stamps last_run_at only if the row is
        still active and its next_run_at equals old_next. Returns True if claimed
        (guarantees a single runner across instances), False if another claimed it.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE scheduled_scans "
                    "SET next_run_at=%s, last_run_at=%s, updated_at=%s "
                    "WHERE id=%s AND next_run_at=%s AND status='active'",
                    (new_next, now, now, schedule_id, old_next),
                )
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def insert_schedule_execution(self, data: Dict[str, Any]) -> int:
        """Insert a schedule-execution record; return its new id."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO schedule_executions "
                    "(schedule_id, scan_id, status, started_at, completed_at, error_message) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        data["schedule_id"],
                        data.get("scan_id"),
                        data["status"],
                        data["started_at"],
                        data.get("completed_at"),
                        data.get("error_message"),
                    ),
                )
                exec_id = cur.fetchone()[0]
                conn.commit()
                return exec_id
            except Exception:
                conn.rollback()
                raise

    def update_schedule_execution(self, exec_id: int, fields: Dict[str, Any]) -> None:
        """Update allowed columns on a schedule-execution row; no-ops if none given."""
        allowed = {"scan_id", "status", "completed_at", "error_message"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE schedule_executions SET {set_clause} WHERE id=%s",
                    (*updates.values(), exec_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_schedule_executions(
        self, schedule_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return a schedule's recent execution records, newest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM schedule_executions "
                    "WHERE schedule_id=%s ORDER BY started_at DESC LIMIT %s",
                    (schedule_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                raise

    def cleanup_old_executions(self, days: int = 90, min_keep: int = 100) -> int:
        """Delete execution records older than `days`, keeping the latest min_keep per schedule.

        Returns the number of rows deleted.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM schedule_executions "
                    "WHERE started_at < %s "
                    "AND id NOT IN ("
                    "  SELECT id FROM ("
                    "    SELECT id, ROW_NUMBER() OVER (PARTITION BY schedule_id ORDER BY started_at DESC) AS rn "
                    "    FROM schedule_executions"
                    "  ) ranked WHERE rn <= %s"
                    ")",
                    (cutoff, min_keep),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    def update_scan_schedule_link(
        self, scan_id: str, schedule_id: str, triggered_by: str
    ) -> None:
        """Link a scan back to the schedule that triggered it."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE scans SET schedule_id=%s, triggered_by=%s WHERE scan_id=%s",
                    (schedule_id, triggered_by, scan_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def count_scheduled_scans(self) -> int:
        """Return the total number of scheduled scans."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM scheduled_scans")
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise

    def mark_orphaned_executions(self) -> int:
        """Fail executions stuck in 'started' for >10 minutes (crash recovery); return the count."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE schedule_executions SET status='failed', "
                    "completed_at=%s, error_message='Server restarted during execution' "
                    "WHERE status='started' AND started_at < %s",
                    (now, threshold),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    # ── Close Rules ──────────────────────────────────────────────

    def insert_close_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a close rule (defaulting status to 'active'); return the stored row.

        Serializes a datetime reference_value to ISO text before persisting.
        """
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
        placeholders = ", ".join(["%s"] * len(vals))
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"INSERT INTO close_rules ({col_names}) VALUES ({placeholders}) RETURNING *",
                    list(vals.values()),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._serialize_row(row)

    def list_close_rules(self, account_id: str) -> list:
        """Return all close rules for an account (JSON-safe), newest first."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT * FROM close_rules WHERE account_id = %s ORDER BY created_at DESC",
                    (account_id,),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [self._serialize_row(r) for r in rows]

    def get_close_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Return one close rule (JSON-safe), or None if not found."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute("SELECT * FROM close_rules WHERE id = %s", (rule_id,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._serialize_row(row)

    def update_close_rule(self, rule_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Update allowed close-rule columns; return the updated row or None.

        Normalizes reference_value to text, stamps updated_at, and returns None
        when nothing updatable is given or the rule does not exist.
        """
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
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"UPDATE close_rules SET {set_clause} WHERE id = %s RETURNING *",
                    list(updates.values()) + [rule_id],
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if not row:
            return None
        return self._serialize_row(row)

    def atomic_trigger_rule(self, rule_id: str) -> bool:
        """Atomically set rule status to 'triggered' only if currently 'active'. Returns True if transitioned."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE close_rules SET status = 'triggered', triggered_at = now(), updated_at = now() "
                    "WHERE id = %s AND status = 'active' RETURNING id",
                    (rule_id,),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return row is not None

    def deactivate_rules_for_account(self, account_id: str, exclude_rule_id: str | None = None) -> int:
        """Deactivate all active/paused rules for an account (e.g. after a rule triggers a close-all).
        Returns the number of rules deactivated."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                if exclude_rule_id:
                    cur.execute(
                        "UPDATE close_rules SET status = 'expired', updated_at = now() "
                        "WHERE account_id = %s AND id != %s AND status IN ('active', 'paused', 'triggered')",
                        (account_id, exclude_rule_id),
                    )
                else:
                    cur.execute(
                        "UPDATE close_rules SET status = 'expired', updated_at = now() "
                        "WHERE account_id = %s AND status IN ('active', 'paused', 'triggered')",
                        (account_id,),
                    )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    def delete_close_rule(self, rule_id: str) -> bool:
        """Delete a close rule and its executions in one transaction; return True if removed."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM close_executions WHERE rule_id = %s", (rule_id,))
                cur.execute("DELETE FROM close_rules WHERE id = %s", (rule_id,))
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected > 0

    def list_active_rules(self) -> list:
        """Fetch all active rules for non-deleted, active accounts."""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT cr.* FROM close_rules cr "
                    "JOIN trading_accounts ta ON cr.account_id = ta.id "
                    "WHERE cr.status = 'active' AND ta.deleted_at IS NULL "
                    "AND ta.is_active = 1 "
                    "AND (cr.expires_at IS NULL OR cr.expires_at > now()) "
                    "ORDER BY cr.account_id, cr.created_at",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return [self._serialize_row(r) for r in rows]

    def recover_stuck_triggered_rules(self, max_age_seconds: int = 120) -> int:
        """Revert rules stuck in 'triggered' state for longer than max_age_seconds."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE close_rules SET status = 'active', triggered_at = NULL "
                    "WHERE status = 'triggered' "
                    "AND triggered_at < now() - interval '1 second' * %s",
                    (max_age_seconds,),
                )
                affected = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return affected

    def count_active_rules_by_account(self) -> Dict[str, int]:
        """Return {account_id: count} for all accounts with active rules."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT account_id::text, COUNT(*) FROM close_rules "
                    "WHERE status = 'active' GROUP BY account_id",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {r[0]: r[1] for r in rows}

    def get_active_targets_by_account(self) -> Dict[str, list]:
        """Return {account_id: [{trigger_type, threshold_value, reference_value}]} for active rules."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT account_id::text, trigger_type, threshold_value, reference_value "
                    "FROM close_rules WHERE status = 'active' ORDER BY account_id, created_at",
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        result: Dict[str, list] = {}
        for r in rows:
            result.setdefault(r[0], []).append({
                "trigger_type": r[1],
                "threshold_value": str(r[2]) if r[2] is not None else None,
                "reference_value": str(r[3]) if r[3] is not None else None,
            })
        return result

    def count_rules_for_account(self, account_id: str) -> int:
        """Return the number of active or paused close rules for an account."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM close_rules WHERE account_id = %s AND status IN ('active', 'paused')",
                    (account_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                raise
        return row[0] if row else 0

    # ── Close Executions ─────────────────────────────────────────

    def insert_close_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a close-execution record; return the stored row (JSON-safe).

        Serializes the results payload to JSON when not already a string.
        """
        cols = ["account_id", "rule_id", "trigger_source", "total_positions",
                "closed_count", "failed_count", "results"]
        vals = {c: execution.get(c) for c in cols}
        if vals.get("results") and not isinstance(vals["results"], str):
            vals["results"] = json.dumps(vals["results"])
        col_names = ", ".join(vals.keys())
        placeholders = ", ".join(["%s"] * len(vals))
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    f"INSERT INTO close_executions ({col_names}) VALUES ({placeholders}) RETURNING *",
                    list(vals.values()),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._serialize_row(row)

    def list_close_executions(self, account_id: str, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """Return paginated close executions for an account (newest first).

        Returns {"items", "total", "page", "limit"}.
        """
        offset = (page - 1) * limit
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM close_executions WHERE account_id = %s",
                    (account_id,),
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    "SELECT * FROM close_executions WHERE account_id = %s "
                    "ORDER BY executed_at DESC LIMIT %s OFFSET %s",
                    (account_id, limit, offset),
                )
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                raise
        return {
            "items": [self._serialize_row(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    def _serialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DB row to JSON-safe dict."""
        result = {}
        for k, v in dict(row).items():
            if isinstance(v, (datetime, date)):
                result[k] = v.isoformat()
            elif isinstance(v, (uuid.UUID, Decimal)):
                result[k] = str(v)
            else:
                result[k] = v
        return result
