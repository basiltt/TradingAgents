"""Tests for the Opus sampling-param predicate (future-proof self-heal).

This is money-critical: a false-positive wrongly strips temperature (changing
trade behavior); a false-negative sends temperature to a model that 400s it
(freezing the AI Manager to no-action). The predicate must cover FUTURE Opus
releases so a new model can't silently break the LLM call.
"""
import pytest

from tradingagents.llm_clients.model_families import model_rejects_sampling_params


@pytest.mark.parametrize("model", [
    # Opus 4.7+ — reject sampling params (adaptive thinking only).
    "claude-opus-4-7",
    "claude-opus-4-8",
    "anthropic/claude-opus-4-8",
    "claude-opus-4-7-20260101",
    # FUTURE Opus — must self-cover (the whole point of the predicate vs a list).
    "claude-opus-4-9",
    "claude-opus-4-10",
    "claude-opus-4-12-20270101",
    "claude-opus-5",
    "claude-opus-5-2",
    "anthropic/claude-opus-5-0-20280101",
])
def test_opus_4_7_plus_rejects_sampling(model):
    assert model_rejects_sampling_params(model) is True


@pytest.mark.parametrize("model", [
    # Opus 4.0–4.6 still ACCEPT sampling params.
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-opus-4",
    # Legacy Claude 3 Opus accepts sampling params — must NOT false-match on
    # the date digits (regression guard: an earlier regex matched the date).
    "claude-3-opus-20240229",
    "claude-3-opus-latest",
    # Non-Opus Anthropic + other providers all keep sampling params.
    "claude-sonnet-4-6",
    "claude-sonnet-4-8",
    "claude-haiku-4-5",
    "gpt-5.4",
    "gpt-4o",
    "deepseek-chat",
    "gemini-2.5-flash",
    "",
    "opus",
])
def test_others_keep_sampling(model):
    assert model_rejects_sampling_params(model) is False
