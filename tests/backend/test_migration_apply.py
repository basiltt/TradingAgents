"""Tests for Regime Multi-Strategy migrations 43-48 (TASK-0.5, async-only per PD2).

These are static/structural assertions (no live DB needed): migration shape,
no-inner-semicolon (the runner splits on ';'), and CHECK-enum == Pydantic Literal
parity (R5-G6) so the DB constraint can never reject a value Pydantic accepts.
"""

import re

from backend.async_persistence import _MIGRATIONS
from backend.schemas import AutoTradeConfig


def _new_migrations():
    return {v: sql for v, sql in _MIGRATIONS if isinstance(v, int) and v >= 43}


def test_migration_versions_sequential_no_dupes():
    versions = [v for v, _ in _MIGRATIONS]
    assert versions == sorted(versions), "migration versions not sorted"
    assert len(versions) == len(set(versions)), "duplicate migration versions"
    assert versions[-1] == 50, "latest migration should be 50 (49-50 = regime perf indexes)"


def test_new_migrations_present():
    m = _new_migrations()
    for v in (43, 44, 45, 46, 47, 48):
        assert v in m, f"migration {v} missing"


def test_no_inner_semicolons():
    # The runner does sql.split(';'); an inner ';' would shatter a statement.
    for v, sql in _new_migrations().items():
        if isinstance(sql, str):
            assert sql.rstrip(";").count(";") == 0, f"migration {v} has an inner semicolon"


def test_migration_44_is_multiclause_single_statement():
    sql = _new_migrations()[44]
    assert sql.count("ADD COLUMN IF NOT EXISTS") == 3  # strategy_kind, strategy_cohort, f1_active
    assert "strategy_kind" in sql and "strategy_cohort" in sql and "f1_active" in sql


def test_idempotent_guards_present():
    for v, sql in _new_migrations().items():
        if isinstance(sql, str):
            assert "IF NOT EXISTS" in sql, f"migration {v} not idempotent (missing IF NOT EXISTS)"


def _check_enum_values(sql: str, column: str) -> set[str]:
    # extract the CHECK(... col IN ('a','b')) literal set for `column`
    m = re.search(rf"{column} IN \(([^)]*)\)", sql)
    if not m:
        return set()
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_check_enum_matches_pydantic_literal_cohort():
    # R5-G6: trading_accounts.strategy_cohort CHECK == AutoTradeConfig Literal.
    # The Pydantic field is Optional[Literal[...]] (None = "inherit" tri-state), so
    # unwrap the NoneType — the DB column is NOT NULL with a concrete default, so the
    # CHECK legitimately covers only the two concrete cohort values.
    m = _new_migrations()
    db_vals = _check_enum_values(m[43], "strategy_cohort")
    fields = AutoTradeConfig.model_fields
    literal_vals = {
        a for a in getattr(fields["strategy_cohort"].annotation, "__args__", ())
        if a is not type(None)  # drop NoneType from the Optional
    }
    # each remaining arg is itself the Literal; collect its values
    concrete = set()
    for a in literal_vals:
        concrete |= set(getattr(a, "__args__", (a,)))
    assert db_vals == {"trend", "mean_reversion"}
    assert db_vals == concrete, f"DB {db_vals} != Pydantic {concrete}"


def test_check_enum_matches_strategy_kind():
    # trades.strategy_kind CHECK has NO 'both' (a trade has one origin)
    db_vals = _check_enum_values(_new_migrations()[44], "strategy_kind")
    assert db_vals == {"trend", "mean_reversion"}


def test_kill_switch_table_uses_killed_column():
    # R2-F2: self-documenting `killed BOOLEAN DEFAULT false` (safe default)
    sql = _new_migrations()[48]
    assert "killed BOOLEAN NOT NULL DEFAULT false" in sql
    assert "enabled" not in sql


def test_pending_intents_keyed_by_account_symbol_side():
    # PD5: keyed by (account,symbol,side), NOT order_link_id (never sent to exchange)
    sql = _new_migrations()[47]
    assert "PRIMARY KEY (account_id, symbol, side)" in sql
    assert "order_link_id" not in sql
