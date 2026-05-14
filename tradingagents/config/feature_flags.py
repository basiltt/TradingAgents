import types

_FEATURE_FLAGS = {
    "use_information_barriers": True,
    "use_risk_manager": True,
    "use_multi_timeframe": True,
    "use_structured_pm_output": True,
}
FEATURE_FLAGS = types.MappingProxyType(_FEATURE_FLAGS)


def is_enabled(flag_name: str) -> bool:
    import logging

    logger = logging.getLogger(__name__)
    if flag_name not in FEATURE_FLAGS:
        logger.warning("Unknown feature flag: %s", flag_name)
        return False
    enabled = FEATURE_FLAGS[flag_name]
    if not enabled and flag_name in ("use_information_barriers", "use_risk_manager"):
        logger.critical(
            "Security feature flag '%s' is DISABLED — this removes a safety layer",
            flag_name,
        )
    return enabled
