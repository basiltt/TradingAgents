"""Cool Off Time — CooloffSweep env-parse hardening (cross-phase deploy-safety fix).

Unit-tests _parse_interval: a malformed COOLOFF_SWEEP_INTERVAL_S must never crash the
constructor (which runs at app startup outside any try/except) — it falls back to the
default and floors at 1s.
"""

import pytest
from backend.services.cooloff_sweep import _parse_interval, _DEFAULT_INTERVAL_S


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, _DEFAULT_INTERVAL_S),       # unset → default
        ("", _DEFAULT_INTERVAL_S),         # empty → default
        ("abc", _DEFAULT_INTERVAL_S),      # non-numeric → default
        ("60s", _DEFAULT_INTERVAL_S),      # trailing unit → default (int() raises)
        ("0", _DEFAULT_INTERVAL_S),        # zero would busy-loop → default
        ("-5", _DEFAULT_INTERVAL_S),       # negative → default
        ("1", 1),                          # valid floor
        ("30", 30),                        # valid
        ("120", 120),                      # valid
    ],
)
def test_parse_interval(raw, expected):
    assert _parse_interval(raw) == expected
