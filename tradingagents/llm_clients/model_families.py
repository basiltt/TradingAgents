"""Shared model-family constants for LLM provider routing.

Kept dependency-free so it can be imported from both the engine
(`tradingagents.llm_clients`) and the API layer (`backend.services`) without
pulling in langchain/litellm.
"""

# Substrings identifying Opus models that require adaptive thinking and reject
# the legacy sampling params. Opus 4.7/4.8 removed temperature/top_p/top_k and
# the budget_tokens extended-thinking shape; both 400 on these models. This list
# is explicit (not a "4.7+" prefix match) — extend it when a new Opus ships.
OPUS_ADAPTIVE_SUBSTRINGS = ("opus-4-7", "opus-4-8")
