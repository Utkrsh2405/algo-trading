class BrokerError(Exception):
    """Base class for all broker-adapter errors."""


class BrokerAuthError(BrokerError):
    """Login, token refresh, or credential validation failed."""


class BrokerConnectionError(BrokerError):
    """The broker API or its WebSocket feed is unreachable."""


class BrokerRateLimitError(BrokerError):
    """The broker rejected a request for exceeding its rate limit."""


# ── Phase 5 ─────────────────────────────────────────────────────────────────

class RiskCheckError(Exception):
    """
    The risk-check function itself failed (DB error, timeout, etc.).
    Callers MUST treat this as 'order blocked' — never let the order through
    when the gate cannot be evaluated. This is the fail-closed guarantee.
    """


class KillSwitchActiveError(Exception):
    """
    The account-level kill switch is engaged. All order placement must halt
    until the switch is explicitly cleared by the user.
    """


class OrderRateLimitError(Exception):
    """
    The per-user order rate limit (token bucket) is exhausted.
    The caller should back off rather than retry immediately.
    """


class DuplicateOrderError(Exception):
    """
    An order with this idempotency_key already exists in a non-FAILED state.
    The caller should treat the existing order as the authoritative result
    rather than placing a new one.
    """
