"""
Risk-check service — Phase 5 🔴 Slow Mode.

CRITICAL PROPERTIES (read before making any change here):

1. FAIL-CLOSED: If this function raises ANY exception (DB error, timeout,
   missing data), the caller MUST block the order. The exception must never
   be swallowed to let an order through. We raise RiskCheckError to make
   the intent explicit at the call site.

2. ATOMIC READS: We fetch risk_limits with SELECT … FOR UPDATE inside a
   single transaction. This means two concurrent order requests for the
   same user cannot both read the same risk state, both decide "OK", and
   both pass — the second request blocks at the DB level until the first
   transaction commits (which happens after the order row is written, in
   order.py). This is enforced per-row, so different users' requests do
   not block each other.

3. ACCOUNT-WIDE AGGREGATION: We always check BOTH:
   - The per-strategy risk limit (if one exists for this strategy_id), AND
   - The account-wide risk limit (strategy_id IS NULL for this user).
   Whichever is more restrictive wins. A strategy cannot bypass the
   account-wide limit by having a generous per-strategy limit.

4. CORRELATION-ID LOGGING: Every call — allowed or blocked — writes to
   audit_log so the full decision chain can be reconstructed later.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.position import Position
from app.models.risk_limit import RiskLimit
from app.services.broker.exceptions import RiskCheckError

logger = logging.getLogger(__name__)

# Status values for orders we count as "open / consuming position"
_ACTIVE_ORDER_STATUSES = {"PENDING", "PLACED", "OPEN"}


def _write_audit(
    db: Session,
    *,
    user_id: uuid.UUID,
    correlation_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    details: dict,
) -> None:
    """Append-only audit row. Rolls back with the caller's transaction if needed."""
    db.add(AuditLog(
        user_id=user_id,
        correlation_id=correlation_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    ))


def _today_realized_loss(db: Session, user_id: uuid.UUID) -> float:
    """
    Sum of (filled_quantity * price) for today's FILLED SELL orders minus
    equivalent BUY fills — a simplified P&L that counts realized loss.
    For Phase 5 we use a conservative proxy: total negative P&L from filled
    orders placed today. Replace with proper realized-P&L logic once position
    tracking is extended.

    Returns a non-negative float representing the loss amount (0 means no loss).
    """
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    rows = (
        db.execute(
            select(Order.side, Order.filled_quantity, Order.price)
            .where(
                Order.user_id == user_id,
                Order.status == "FILLED",
                Order.placed_at >= today_start,
                Order.price.isnot(None),
            )
        )
        .all()
    )

    realized = 0.0
    for side, qty, price in rows:
        if price is None:
            continue
        # Buys cost money; sells recoup. A loss occurs when cost > proceeds.
        sign = -1 if side == "BUY" else 1
        realized += sign * qty * price

    # Return the loss (positive means loss)
    return max(0.0, -realized)


def _current_position_size(
    db: Session, user_id: uuid.UUID, strategy_id: uuid.UUID | None, symbol: str
) -> int:
    """Absolute quantity held in this symbol under the given scope."""
    pos = db.execute(
        select(Position.quantity).where(
            Position.user_id == user_id,
            Position.strategy_id == strategy_id,
            Position.symbol == symbol,
        )
    ).scalar_one_or_none()
    return abs(pos or 0)


def check_risk_before_order(
    db: Session,
    *,
    user_id: uuid.UUID,
    strategy_id: uuid.UUID | None,
    symbol: str,
    quantity: int,
    side: str,
    correlation_id: str,
) -> None:
    """
    Evaluates risk limits before an order may be placed.

    Raises:
        RiskCheckError  — the risk check itself failed (DB error, etc.).
                          Callers MUST treat this as 'blocked'.
        ValueError      — a risk limit was breached (order must be blocked).

    Does NOT raise on "allowed" — returns None silently.

    This function is called inside a transaction in order.py (place_order).
    The SELECT FOR UPDATE on risk_limits ensures two concurrent calls for the
    same user cannot both read an "OK" state and both proceed past the limit.
    """
    try:
        # ── 1. Load risk limits with a row-level lock ────────────────────────
        # We lock BOTH the per-strategy row (if any) and the account-wide row.
        # The lock is held until the surrounding transaction in place_order
        # commits (after the Order row is written), preventing a second
        # concurrent request from reading stale risk state.

        limit_query = select(RiskLimit).where(
            RiskLimit.user_id == user_id,
            # Match either the per-strategy limit OR the account-wide limit (NULL)
            (RiskLimit.strategy_id == strategy_id) | (RiskLimit.strategy_id.is_(None)),
        ).with_for_update()

        limits = db.execute(limit_query).scalars().all()

        if not limits:
            # No risk limit configured for this user at all — block by default.
            # A missing limit is NOT a reason to allow unlimited orders.
            raise ValueError(
                f"No risk limit configured for user {user_id}. "
                "Order blocked until limits are set."
            )

        # ── 2. Evaluate each limit row (per-strategy + account-wide) ─────────
        today_loss = _today_realized_loss(db, user_id)
        current_qty = _current_position_size(db, user_id, strategy_id, symbol)

        for limit in limits:
            scope = "account-wide" if limit.strategy_id is None else f"strategy:{limit.strategy_id}"

            # Daily loss check
            if today_loss >= limit.max_daily_loss:
                msg = (
                    f"Daily loss limit breached [{scope}]: "
                    f"loss={today_loss:.2f} >= max={limit.max_daily_loss:.2f}"
                )
                logger.warning("RISK BLOCKED [%s]: %s", correlation_id, msg)
                _write_audit(
                    db,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    action="RISK_BLOCKED",
                    entity_type="risk_limit",
                    entity_id=str(limit.id),
                    details={"reason": msg, "scope": scope},
                )
                raise ValueError(msg)

            # Position size check (projected quantity after this order)
            projected_qty = current_qty + quantity if side == "BUY" else current_qty - quantity
            if abs(projected_qty) > limit.max_position_size:
                msg = (
                    f"Position size limit breached [{scope}]: "
                    f"projected={abs(projected_qty)} > max={limit.max_position_size}"
                )
                logger.warning("RISK BLOCKED [%s]: %s", correlation_id, msg)
                _write_audit(
                    db,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    action="RISK_BLOCKED",
                    entity_type="risk_limit",
                    entity_id=str(limit.id),
                    details={"reason": msg, "scope": scope},
                )
                raise ValueError(msg)

        # ── 3. All limits passed — log and return ────────────────────────────
        _write_audit(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            action="RISK_ALLOWED",
            entity_type="order",
            entity_id=None,
            details={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "today_loss": today_loss,
                "current_qty": current_qty,
            },
        )
        logger.info("RISK ALLOWED [%s]: %s %s x%d", correlation_id, side, symbol, quantity)

    except ValueError:
        # Re-raise limit-breach errors as-is — caller handles them
        raise
    except Exception as exc:
        # ANY other exception (DB failure, timeout, etc.) becomes a
        # RiskCheckError, which the caller MUST treat as "blocked".
        # This is the fail-closed guarantee.
        logger.error(
            "RISK CHECK FAILED [%s] — treating as BLOCKED: %s",
            correlation_id, exc, exc_info=True,
        )
        raise RiskCheckError(
            f"Risk check failed internally (fail-closed): {exc}"
        ) from exc
