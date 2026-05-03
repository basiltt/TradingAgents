"""Model name validators for each provider."""

from .model_catalog import get_known_models


VALID_MODELS = {
    provider: models
    for provider, models in get_known_models().items()
    if provider not in ("ollama", "openrouter")
}


def _normalize_model_name(name: str) -> str:
    """Normalize model name so 'claude-sonnet-4.6' matches 'claude-sonnet-4-6'."""
    import re
    return re.sub(r"[\.\-]", "-", name)


def validate_model(provider: str, model: str) -> bool:
    """Check if model name is valid for the given provider.

    For ollama, openrouter - any model is accepted.
    Normalizes dots/hyphens so proxy and direct API model IDs both match.
    """
    provider_lower = provider.lower()

    if provider_lower in ("ollama", "openrouter"):
        return True

    if provider_lower not in VALID_MODELS:
        return True

    normalized = _normalize_model_name(model)
    return any(
        _normalize_model_name(m) == normalized
        for m in VALID_MODELS[provider_lower]
    )
