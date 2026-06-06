"""Shared model-family constants/predicates for LLM provider routing.

Kept dependency-free (stdlib only) so it can be imported from both the engine
(`tradingagents.llm_clients`) and the API layer (`backend.services`) without
pulling in langchain/litellm.
"""

import re

# Substrings identifying Opus models that require adaptive thinking and reject
# the legacy sampling params. Opus 4.7/4.8 removed temperature/top_p/top_k and
# the budget_tokens extended-thinking shape; both 400 on these models.
#
# Kept for backward-compat / explicit membership tests. Prefer the predicate
# ``model_rejects_sampling_params`` below for gating, which also covers FUTURE
# Opus releases (4.9, 4.10, 5.x …) that — per the 4.7/4.8 precedent — are
# expected to keep rejecting sampling params. A hardcoded list would silently
# 400 on a new Opus, freezing the AI Manager to no-action; the regex self-covers.
OPUS_ADAPTIVE_SUBSTRINGS = ("opus-4-7", "opus-4-8")

# Matches Anthropic Opus 4.7+ in any common form:
#   claude-opus-4-7, anthropic/claude-opus-4-8, claude-opus-4-7-20260101,
#   claude-opus-4-10-*, claude-opus-5-*, claude-opus-5-2-*  (case-insensitive).
# Opus 4.0–4.6 (which still ACCEPT sampling params) and legacy Claude 3 Opus
# (claude-3-opus-*, which also accepts them) are deliberately excluded. The
# minor-version is bounded to 1–2 digits so a date suffix (e.g. ...-20240229)
# is never misread as a version number.
_OPUS_ADAPTIVE_RE = re.compile(
    r"opus-(?:"
    r"4-(?:[7-9]|1\d)"      # 4.7, 4.8, 4.9, 4.10–4.19  (NOT 4.0–4.6)
    r"|[5-9](?:-\d{1,2})?"  # 5, 5.x … 9.x  (single-digit major >= 5)
    r")(?![0-9])",          # the matched version isn't followed by more digits
    re.IGNORECASE,
)


def model_rejects_sampling_params(model: str) -> bool:
    """True if `model` is an Anthropic Opus that rejects temperature/top_p/top_k
    (Opus 4.7 and later). Covers prefixed (`anthropic/…`), dated-snapshot, and
    future minor/major Opus IDs so a new release can't silently 400 the call.

    Conservative by construction: matches ONLY Opus 4.7+ / 5+ — every other
    model (incl. Opus 4.0–4.6, all Sonnet/Haiku, all non-Anthropic) returns
    False and keeps its sampling params.
    """
    return bool(_OPUS_ADAPTIVE_RE.search((model or "").lower()))
