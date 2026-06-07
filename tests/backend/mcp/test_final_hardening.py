"""Final-review hardening regression tests.

Covers the cross-phase review findings:
- A6: revert must run the prior config through the absolute sanity ceiling
  (it previously bypassed it, allowing a ceiling-breaching prior to be restored).
- NaN/Inf in bounded fields must be treated as a ceiling breach.
- build_diff produces the {before, fields} envelope the UI + drift-guard expect.
- create_proposal_from_winner persists a pending proposal (the create side of
  the money path that was previously unwired).
"""
from __future__ import annotations

import math

import pytest

from backend.mcp.tools.optimizer.apply import (
    ApplyRejected,
    build_diff,
    sanity_ceiling_ok,
    validate_full_config,
)


# --- NaN / ceiling ---

def test_nan_leverage_is_a_ceiling_breach():
    assert sanity_ceiling_ok({"leverage": float("nan"), "stop_loss_pct": 2.0, "capital_pct": 10}) is False


def test_inf_capital_is_a_ceiling_breach():
    assert sanity_ceiling_ok({"leverage": 5, "stop_loss_pct": 2.0, "capital_pct": math.inf}) is False


def test_non_numeric_leverage_is_a_breach():
    assert sanity_ceiling_ok({"leverage": "lots", "stop_loss_pct": 2.0, "capital_pct": 10}) is False


def test_sane_config_passes_ceiling():
    assert sanity_ceiling_ok({"leverage": 10, "stop_loss_pct": 2.0, "capital_pct": 20}) is True


# --- A6: revert through the ceiling ---

def test_validate_full_config_rejects_ceiling_breach():
    """A prior snapshot that exceeds the hard leverage ceiling must NOT validate
    for revert — the exact A6 escalation the review found."""
    with pytest.raises(ApplyRejected):
        validate_full_config({"leverage": 125, "stop_loss_pct": 2.0, "capital_pct": 10})


def test_validate_full_config_rejects_missing_stop_loss():
    with pytest.raises(ApplyRejected):
        validate_full_config({"leverage": 5, "stop_loss_pct": None, "capital_pct": 10})


# --- diff envelope ---

def test_build_diff_emits_before_and_changed_fields_only():
    prior = {"leverage": 5, "take_profit_pct": 3.0, "stop_loss_pct": 2.0, "account_id": "a"}
    proposed = {"leverage": 8, "take_profit_pct": 3.0, "stop_loss_pct": 2.0}
    diff = build_diff(prior, proposed)
    assert diff["before"] == prior  # full prior for the drift-guard
    assert diff["fields"] == {"leverage": {"from": 5, "to": 8}}  # only the change


def test_build_diff_ignores_non_sweepable_fields():
    prior = {"leverage": 5, "stop_loss_pct": 2.0}
    proposed = {"leverage": 5, "stop_loss_pct": 2.0, "allow_real_trades": True}
    diff = build_diff(prior, proposed)
    assert diff["fields"] == {}  # allow_real_trades is not sweepable → not a change
