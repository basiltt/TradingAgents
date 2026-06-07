"""MCP domain errors + exception→MCP-error mapping — TASK-P0-06.

Domain exceptions raised by handlers/services are mapped by the dispatcher to a
structured, agent-readable `isError` tool result (NOT a JSON-RPC protocol error).
Each maps to a stable code + a retryable hint.
"""
from __future__ import annotations

from dataclasses import dataclass


class MCPError(Exception):
    """Base for mappable MCP domain errors."""

    code = "internal_error"
    retryable = False


class MCPValidationError(MCPError):
    code = "invalid_params"
    retryable = False


class MCPNotFoundError(MCPError):
    code = "not_found"
    retryable = False


class MCPConflictError(MCPError):
    code = "conflict"
    retryable = False


class MCPBusyError(MCPError):
    code = "busy"
    retryable = True


class MCPRateLimitError(MCPError):
    code = "rate_limited"
    retryable = True


class MCPServiceUnavailableError(MCPError):
    code = "service_unavailable"
    retryable = True


class MCPDeniedError(MCPError):
    code = "denied"
    retryable = False


class MCPTimeoutError(MCPError):
    code = "timeout"
    retryable = True


@dataclass(frozen=True)
class MappedError:
    code: str
    message: str
    retryable: bool
    status: str  # audit status: 'error' | 'rejected' | 'rate_limited' | 'timeout'


def map_exception(exc: BaseException) -> MappedError:
    """Map a domain exception to an agent-facing error.

    Unmapped exceptions become a generic internal error (no raw message leak).
    """
    if isinstance(exc, MCPDeniedError):
        return MappedError(exc.code, str(exc) or "denied", False, "rejected")
    if isinstance(exc, MCPValidationError):
        return MappedError(exc.code, str(exc) or "invalid parameters", False, "rejected")
    if isinstance(exc, MCPRateLimitError):
        return MappedError(exc.code, str(exc) or "rate limited", True, "rate_limited")
    if isinstance(exc, MCPTimeoutError):
        return MappedError(exc.code, str(exc) or "timed out", True, "timeout")
    if isinstance(exc, MCPError):
        return MappedError(exc.code, str(exc) or exc.code, exc.retryable, "error")
    # Unmapped: do not leak the raw exception text to the agent.
    return MappedError("internal_error", "internal error", False, "error")
