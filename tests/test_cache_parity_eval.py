"""Smoke tests for the cache behavioral-parity eval harness.

These test the NON-LLM logic of ``scripts/cache_parity_eval.py`` — parser, stats,
fixtures, prompt-decomposition invariants, and the dry-run safety property. They
make NO network calls: the live path is exercised with a fake in-memory model
caller, and the dry-run path is asserted to never invoke a caller at all.

Run: python -m pytest tests/test_cache_parity_eval.py -v
"""

from __future__ import annotations

import importlib

import pytest

cpe = importlib.import_module("scripts.cache_parity_eval")


# ---------------------------------------------------------------------------
# Import + fixtures
# ---------------------------------------------------------------------------


def test_module_imports_cleanly():
    # Re-import to prove it has no import-time side effects / errors.
    importlib.reload(cpe)
    assert cpe is not None


def test_fixtures_count_and_keys():
    assert len(cpe.FIXTURES) >= 30, "harness requires N>=30 fixtures"
    for fx in cpe.FIXTURES:
        assert set(("symbol", "trade_date", "market_state")).issubset(fx.keys())
        assert isinstance(fx["symbol"], str) and fx["symbol"]
        assert isinstance(fx["trade_date"], str) and fx["trade_date"]
        assert isinstance(fx["market_state"], str) and fx["market_state"]


def test_fixtures_span_regimes_and_symbols():
    blob = " ".join(fx["market_state"].lower() for fx in cpe.FIXTURES)
    for regime in ("bull", "bear", "chop"):
        assert regime in blob, f"no {regime} fixture present"
    symbols = {fx["symbol"] for fx in cpe.FIXTURES}
    # A spread of crypto + stock inputs.
    assert {"BTCUSDT", "ETHUSDT"}.issubset(symbols)
    assert symbols & {"AAPL", "NVDA"}


# ---------------------------------------------------------------------------
# Decision-label parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("Lots of analysis...\nFINAL TRANSACTION PROPOSAL: **BUY**", "BUY"),
    ("FINAL TRANSACTION PROPOSAL: **SELL**", "SELL"),
    ("blah\nFINAL TRANSACTION PROPOSAL: **HOLD**\n", "HOLD"),
    ("final transaction proposal: buy", "BUY"),                  # lowercase
    ("FINAL TRANSACTION PROPOSAL:   SELL", "SELL"),              # no emphasis
    ("FINAL TRANSACTION PROPOSAL:**hold**", "HOLD"),            # tight spacing
    ("I think we should hold for now.", "HOLD"),                 # fallback token
    ("First buy, then later sell the rest", "SELL"),            # fallback = last
])
def test_parse_decision_extracts_label(text, expected):
    assert cpe.parse_decision(text) == expected


@pytest.mark.parametrize("text", [None, "", "no decision token here at all"])
def test_parse_decision_returns_none_when_absent(text):
    assert cpe.parse_decision(text) is None


def test_parser_prefers_final_proposal_over_stray_tokens():
    # A stray "sell" earlier must not override the explicit final proposal.
    text = "We could sell, but momentum is strong.\nFINAL TRANSACTION PROPOSAL: **BUY**"
    assert cpe.parse_decision(text) == "BUY"


# ---------------------------------------------------------------------------
# Prompt-decomposition invariants (OLD vs NEW)
# ---------------------------------------------------------------------------


def test_old_equals_stable_plus_volatile():
    assert cpe._OLD_SYSTEM_TEMPLATE == cpe._STABLE_SYSTEM + cpe._VOLATILE_CONTEXT


def test_content_parity_old_vs_new_per_fixture():
    # The two prompt forms must carry byte-identical CONTENT (differ only in role
    # boundaries). assert_content_parity raises if not.
    for fx in cpe.FIXTURES:
        cpe.assert_content_parity(fx)


def test_new_messages_move_volatile_to_human_turn():
    fx = cpe.FIXTURES[0]
    new = cpe.build_new_messages(fx)
    old = cpe.build_old_messages(fx)
    # NEW: system content has NO volatile marker; a human turn does.
    assert new[0]["role"] == "system"
    assert "For your reference, the current date is" not in new[0]["content"]
    assert any(m["role"] == "user" and "For your reference, the current date is"
               in m["content"] for m in new)
    # OLD: the system message DOES carry the volatile marker.
    assert old[0]["role"] == "system"
    assert "For your reference, the current date is" in old[0]["content"]


# ---------------------------------------------------------------------------
# Statistics: noise floor, agreement, McNemar
# ---------------------------------------------------------------------------


def test_noise_floor_zero_when_self_consistent():
    runs = [["BUY"] * 5, ["SELL"] * 5, ["HOLD"] * 5]
    assert cpe.noise_floor(runs) == 0.0


def test_noise_floor_positive_with_disagreement():
    # One fixture: 4 BUY / 1 SELL -> 1/5 disagreement; others consistent.
    runs = [["BUY", "BUY", "BUY", "BUY", "SELL"], ["HOLD"] * 5]
    # mean of (0.2, 0.0) = 0.1
    assert cpe.noise_floor(runs) == pytest.approx(0.1)


def test_agreement_rate_perfect():
    old = ["BUY", "SELL", "HOLD"]
    new = ["BUY", "SELL", "HOLD"]
    assert cpe.agreement_rate(old, new) == 1.0


def test_agreement_rate_partial_and_skips_none():
    old = ["BUY", "SELL", "HOLD", None]
    new = ["BUY", "BUY", "HOLD", "SELL"]   # disagree on idx1; idx3 skipped (old None)
    assert cpe.agreement_rate(old, new) == pytest.approx(2 / 3)


def test_mcnemar_p_is_one_when_no_discordance():
    old = ["BUY", "SELL", "HOLD"]
    new = ["BUY", "SELL", "HOLD"]
    assert cpe.mcnemar_exact_p(old, new) == 1.0


def test_mcnemar_p_high_for_balanced_discordance():
    # Equal bullish/bearish moves -> no directional drift -> p == 1.0.
    old = ["HOLD", "HOLD", "HOLD", "HOLD"]
    new = ["BUY", "BUY", "SELL", "SELL"]   # b=2, c=2
    assert cpe.mcnemar_exact_p(old, new) == pytest.approx(1.0)


def test_mcnemar_p_low_for_systematic_drift():
    # All 8 discordant pairs move bullish -> strong drift -> tiny p.
    old = ["HOLD"] * 8
    new = ["BUY"] * 8                       # b=8, c=0
    p = cpe.mcnemar_exact_p(old, new)
    assert p < 0.05, f"expected significant drift, got p={p}"
    # Exact two-sided binomial for k=0,n=8,p=0.5 is 2*0.5**8 = 0.0078125.
    assert p == pytest.approx(2 * 0.5 ** 8)


def test_two_sided_binom_matches_known_value():
    # k=1, n=10: lower tail = C(10,0)+C(10,1) over 2^10 = 11/1024; doubled.
    assert cpe._two_sided_binom_p(1, 10) == pytest.approx(2 * 11 / 1024)


# ---------------------------------------------------------------------------
# Pass-rule end-to-end (no LLM — canned label arrays)
# ---------------------------------------------------------------------------


def test_evaluate_pass_true_when_parity_holds():
    # Old fully self-consistent (noise 0 -> threshold 1.0); new matches exactly.
    old_runs = [["BUY"] * 5, ["SELL"] * 5, ["HOLD"] * 5]
    new = ["BUY", "SELL", "HOLD"]
    res = cpe.evaluate_pass(old_runs, new)
    assert res.passed is True
    assert res.agreement == 1.0
    assert res.noise == 0.0
    assert res.mcnemar_p == 1.0


def test_evaluate_pass_false_on_systematic_drift():
    # Old self-consistent HOLD; new always BUY -> agreement 0, drift significant.
    old_runs = [["HOLD"] * 5 for _ in range(8)]
    new = ["BUY"] * 8
    res = cpe.evaluate_pass(old_runs, new)
    assert res.passed is False
    assert res.agreement == 0.0
    assert res.mcnemar_p < 0.05


def test_evaluate_pass_tolerates_noise_in_threshold():
    # Old has 0.1 noise on one fixture -> threshold 1 - (0.1/3) ~ 0.967.
    old_runs = [
        ["BUY", "BUY", "BUY", "BUY", "SELL"],  # modal BUY, 0.2 disagreement
        ["SELL"] * 5,
        ["HOLD"] * 5,
    ]
    new = ["BUY", "SELL", "HOLD"]              # matches all modals -> agreement 1.0
    res = cpe.evaluate_pass(old_runs, new)
    assert res.agreement == 1.0
    assert res.noise == pytest.approx(0.2 / 3)
    assert res.passed is True


# ---------------------------------------------------------------------------
# Dry-run SAFETY — the critical property: no caller invocation, no spend
# ---------------------------------------------------------------------------


class _SpyCaller:
    def __init__(self):
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        return "FINAL TRANSACTION PROPOSAL: **HOLD**"


def test_dry_run_when_run_false_does_not_call_model(capsys):
    spy = _SpyCaller()
    out = cpe.run_eval(run=False, have_key=True, model_caller=spy,
                       fixtures=cpe.FIXTURES[:3])
    assert out is None
    assert spy.calls == 0, "dry run must NOT invoke the model caller"
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed


def test_dry_run_when_no_key_does_not_call_model(capsys):
    spy = _SpyCaller()
    out = cpe.run_eval(run=True, have_key=False, model_caller=spy,
                       fixtures=cpe.FIXTURES[:3])
    assert out is None
    assert spy.calls == 0, "missing key must NOT invoke the model caller"
    printed = capsys.readouterr().out
    assert "refusing to spend" in printed


def test_main_dry_run_returns_zero_without_key(monkeypatch):
    # No key in env -> main() must dry-run and exit 0 even with --run.
    monkeypatch.delenv(cpe.API_KEY_ENV, raising=False)
    assert cpe.main(["--run"]) == 0
    assert cpe.main([]) == 0


def test_default_model_caller_not_invoked_on_import():
    # Sanity: importing the module must not have built a client or called out.
    # (If it had, the import at top of this file would have already failed/spent.)
    assert callable(cpe.default_model_caller)


# ---------------------------------------------------------------------------
# Live path with a FAKE caller (no network) — proves orchestration + write
# ---------------------------------------------------------------------------


def test_live_path_with_fake_caller_passes(tmp_path):
    # Fake caller always returns HOLD -> old self-consistent, new matches -> PASS.
    spy = _SpyCaller()
    results_file = tmp_path / "results.md"
    fixtures = cpe.FIXTURES[:4]
    res = cpe.run_eval(run=True, have_key=True, model_caller=spy,
                       fixtures=fixtures, k_noise=3,
                       results_path=str(results_file))
    assert res is not None
    assert res.passed is True
    # Budget: 4 fixtures * (3 noise + 1 new) = 16 calls.
    assert spy.calls == len(fixtures) * (3 + 1)
    # Results doc was written with a verdict.
    assert results_file.exists()
    body = results_file.read_text(encoding="utf-8")
    assert "RUN - PASS" in body
    assert f"N fixtures: {len(fixtures)}" in body


def test_live_path_with_drifting_caller_fails(tmp_path):
    # Caller returns SELL for the OLD (2-message) prompt and BUY for the NEW
    # (3-message) prompt -> systematic drift -> FAIL. Distinguishes by message
    # count, which is the only structural difference between the forms.
    def drift_caller(messages):
        is_new = len(messages) == 3
        return ("FINAL TRANSACTION PROPOSAL: **BUY**" if is_new
                else "FINAL TRANSACTION PROPOSAL: **SELL**")

    results_file = tmp_path / "results.md"
    res = cpe.run_eval(run=True, have_key=True, model_caller=drift_caller,
                       fixtures=cpe.FIXTURES[:6], k_noise=3,
                       results_path=str(results_file))
    assert res is not None
    assert res.passed is False
    assert res.agreement == 0.0
    body = results_file.read_text(encoding="utf-8")
    assert "RUN - FAIL" in body
