"""Tests for the canonical acct_ordinal derivation on get_summaries (PR2-7)."""
from unittest.mock import MagicMock

from backend.services.auto_trade_service import AutoTradeExecutor


def _exec_with_accounts(account_ids):
    ex = AutoTradeExecutor(MagicMock())
    configs = [{"account_id": aid, "execution_mode": "batch"} for aid in account_ids]
    ex.init_configs(configs)
    return ex


def test_acct_ordinal_is_sorted_distinct_index():
    ex = _exec_with_accounts(["zzz", "aaa", "mmm"])
    m = ex._acct_ordinal_map()
    # Sorted distinct, 1-based.
    assert m == {"aaa": 1, "mmm": 2, "zzz": 3}


def test_acct_ordinal_stable_for_multiple_configs_same_account():
    ex = _exec_with_accounts(["aaa", "aaa", "bbb"])  # aaa has 2 configs
    m = ex._acct_ordinal_map()
    assert m == {"aaa": 1, "bbb": 2}  # one ordinal per distinct account


def test_get_summaries_stamps_acct_ordinal():
    ex = _exec_with_accounts(["bbb", "aaa"])
    summaries = ex.get_summaries()
    by_acct = {s["account_id"]: s["acct_ordinal"] for s in summaries}
    assert by_acct == {"aaa": 1, "bbb": 2}


def test_acct_ordinal_ignores_blank_account_id():
    ex = _exec_with_accounts(["aaa", ""])
    m = ex._acct_ordinal_map()
    assert m == {"aaa": 1}
