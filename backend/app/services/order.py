"""
Order orchestration service — Phase 5 🔴 Slow Mode.

CRITICAL FLOW for place_order():
  1. Kill-switch check (Redis)         → abort immediately if active
  2. Idempotency check (DB)            → return existing order if seen before
  3. Risk check (SELECT FOR UPDATE)    → fail-closed; any error = blocked
  4. Rate-limit check (Redis Lua)      → fail-closed; any error = blocked
  5. Write Order row (status=PENDING)  → DB record BEFORE broker call
  6. Broker call                       → update to PLACED or FAILED
  7. Audit log                         → every step, regardless of outcome

WHY step 5 before step 6?
  If the server crashes between placing with the broker and writing to DB,
  we'd have an orphaned broker order. Writing PENDING first means on restart
  we can find all PENDING orders and reconcile their broker status. The
  alternative (write after) would make orphaned live orders invisible.

KILL SWITCH:
  Sets Redis key immediately (all subsequent place_order calls see it).
  Then deactivates strategies in DB, then attempts cancel on each PENDING
  order. Cancellation errors are logged but do NOT stop the sweep — we
  want as many cancels as possible even if some fail.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.redis import redis_client
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.strategy import Strategy
from app.services.broker.base import BrokerInterface, OrderSide, OrderType
from app.services.broker.exceptions import (
    BrokerConnectionError,
    DuplicateOrderError,
    KillSwitchActiveError,
    OrderRateLimitError,
    RiskCheckError,
)
from app.services.rate_limiter import check_rate_limit
from app.services.risk import check_risk_before_order

logger = logging.getLogger(__name__)

# Redis key pattern for the kill switch. User-scoped so one user's switch
# doesn't affect other users' trading.
_KILL_SWITCH_KEY = "kill_switch:user:{user_id}"


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
    """Append-only audit row. Always commit separately if the main tx rolled back."""
    db.add(AuditLog(
        user_id=user_id,
        correlation_id=correlation_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    ))


async def place_order(
    db: Session,
    broker: BrokerInterface,
    *,
    user_id: uuid.UUID,
    strategy_id: uuid.UUID | None,
    symbol: str,
    side: str,               # "BUY" or "SELL"
    quantity: int,
    order_type: str,         # "MARKET", "LIMIT", "SL", "SL-M"
    price: float | None,
    idempotency_key: str,
    correlation_id: str,
    max_orders_per_minute: int = 30,
    algo_tag: str | None = None,
) -> Order:
    """
    Place an order through all safety layers.

    Raises:
        KillSwitchActiveError  — kill switch is engaged
        DuplicateOrderError    — idempotency key already exists (non-FAILED)
        RiskCheckError         — risk check failed internally (fail-closed)
        ValueError             — risk limit breached
        OrderRateLimitError    — rate limit exhausted (fail-closed on Redis error)
        BrokerConnectionError  — broker rejected or unreachable
    """
    # ── 1. Kill-switch check ─────────────────────────────────────────────────
    kill_key = _KILL_SWITCH_KEY.format(user_id=user_id)
    is_killed = await redis_client.exists(kill_key)
    if is_killed:
        logger.warning("KILL SWITCH active — blocking order [%s]", correlation_id)
        _write_audit(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            action="ORDER_BLOCKED_KILL_SWITCH",
            entity_type="order",
            entity_id=None,
            details={"symbol": symbol, "side": side, "quantity": quantity},
        )
        db.commit()
        raise KillSwitchActiveError("Kill switch is active. Order blocked.")

    # ── 2. Idempotency check ─────────────────────────────────────────────────
    existing = (
        db.query(Order)
        .filter(Order.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None and existing.status != "FAILED":
        logger.info(
            "Duplicate order key [%s] — returning existing order %s (status=%s)",
            correlation_id, existing.id, existing.status,
        )
        _write_audit(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            action="ORDER_DUPLICATE",
            entity_type="order",
            entity_id=str(existing.id),
            details={"idempotency_key": idempotency_key, "existing_status": existing.status},
        )
        db.commit()
        raise DuplicateOrderError(
            f"Order with idempotency_key={idempotency_key!r} already exists "
            f"with status={existing.status!r}."
        )

    # ── 3. Risk check (fail-closed, SELECT FOR UPDATE inside) ────────────────
    # check_risk_before_order raises ValueError (limit breached) or
    # RiskCheckError (check itself failed). Both must block the order.
    check_risk_before_order(
        db,
        user_id=user_id,
        strategy_id=strategy_id,
        symbol=symbol,
        quantity=quantity,
        side=side,
        correlation_id=correlation_id,
    )

    # ── 4. Rate-limit check (fail-closed on Redis error) ─────────────────────
    await check_rate_limit(
        str(user_id),
        capacity=max_orders_per_minute,
        window_seconds=60,
    )

    # ── 5. Write PENDING order row — DB record before broker call ────────────
    order = Order(
        user_id=user_id,
        strategy_id=strategy_id,
        idempotency_key=idempotency_key,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        filled_quantity=0,
        price=price,
        status="PENDING",
        correlation_id=correlation_id,
        algo_tag=algo_tag,
    )
    db.add(order)
    db.flush()   # get the order.id without committing yet

    _write_audit(
        db,
        user_id=user_id,
        correlation_id=correlation_id,
        action="ORDER_PENDING",
        entity_type="order",
        entity_id=str(order.id),
        details={"symbol": symbol, "side": side, "quantity": quantity, "order_type": order_type},
    )
    db.commit()

    # ── 6. Call broker ───────────────────────────────────────────────────────
    try:
        placed = await broker.place_order(
            symbol=symbol,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            quantity=quantity,
            price=price,
            algo_tag=algo_tag,
        )
        order.broker_order_id = placed.broker_order_id
        order.status = "PLACED"
        _write_audit(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            action="ORDER_PLACED",
            entity_type="order",
            entity_id=str(order.id),
            details={
                "broker_order_id": placed.broker_order_id,
                "broker_status": placed.broker_status,
                "algo_tag": algo_tag,
            },
        )
    except Exception as exc:
        order.status = "FAILED"
        order.rejection_reason = str(exc)[:512]
        _write_audit(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            action="ORDER_FAILED",
            entity_type="order",
            entity_id=str(order.id),
            details={"error": str(exc)},
        )
        db.commit()
        raise BrokerConnectionError(f"Broker call failed: {exc}") from exc

    db.commit()
    db.refresh(order)
    return order


async def kill_switch(
    db: Session,
    broker: BrokerInterface,
    *,
    user_id: uuid.UUID,
    correlation_id: str,
    reason: str = "Manual kill switch",
) -> dict:
    """
    Engage the kill switch for a user:
    1. Set Redis key (blocks all future place_order calls immediately).
    2. Deactivate all strategies in the DB.
    3. Attempt to cancel every PENDING/PLACED order via the broker.
       Cancellation failures are logged but do NOT abort the sweep.

    Returns a summary dict with counts of cancelled and failed cancellations.
    """
    kill_key = _KILL_SWITCH_KEY.format(user_id=user_id)

    # Step 1: Set Redis key first — this is the primary guard.
    # Any place_order call after this point will be blocked immediately.
    # TTL of 7 days; must be explicitly cleared via /api/orders/kill-switch DELETE.
    await redis_client.set(kill_key, "1", ex=60 * 60 * 24 * 7)

    logger.critical("KILL SWITCH ENGAGED for user %s [%s]: %s", user_id, correlation_id, reason)

    _write_audit(
        db,
        user_id=user_id,
        correlation_id=correlation_id,
        action="KILL_SWITCH_ENGAGED",
        entity_type="user",
        entity_id=str(user_id),
        details={"reason": reason},
    )

    # Step 2: Deactivate all strategies in DB
    strategies = db.query(Strategy).filter(
        Strategy.user_id == user_id,
        Strategy.is_active == True,
    ).all()
    for strategy in strategies:
        strategy.is_active = False
    db.commit()

    # Step 3: Cancel all pending/open orders
    pending_orders = db.query(Order).filter(
        Order.user_id == user_id,
        Order.status.in_(["PENDING", "PLACED", "OPEN"]),
        Order.broker_order_id.isnot(None),
    ).all()

    cancelled_count = 0
    failed_count = 0

    for order in pending_orders:
        try:
            await broker.cancel_order(order.broker_order_id)
            order.status = "CANCELLED"
            order.rejection_reason = f"Kill switch: {reason}"
            _write_audit(
                db,
                user_id=user_id,
                correlation_id=correlation_id,
                action="ORDER_CANCELLED_KILL_SWITCH",
                entity_type="order",
                entity_id=str(order.id),
                details={"broker_order_id": order.broker_order_id},
            )
            cancelled_count += 1
        except Exception as exc:
            # Do NOT stop the sweep — continue cancelling the remaining orders.
            # The kill switch Redis key is already set, so no new orders can be placed.
            logger.error(
                "Failed to cancel order %s (broker_order_id=%s) during kill switch: %s",
                order.id, order.broker_order_id, exc,
            )
            _write_audit(
                db,
                user_id=user_id,
                correlation_id=correlation_id,
                action="ORDER_CANCEL_FAILED_KILL_SWITCH",
                entity_type="order",
                entity_id=str(order.id),
                details={"broker_order_id": order.broker_order_id, "error": str(exc)},
            )
            failed_count += 1

    db.commit()

    summary = {
        "kill_switch": "engaged",
        "strategies_deactivated": len(strategies),
        "orders_cancelled": cancelled_count,
        "cancel_failures": failed_count,
        "note": (
            "All future order placement is blocked. "
            "Cancel failures were logged — manually verify those orders with your broker."
        ) if failed_count > 0 else "All pending orders cancelled.",
    }
    logger.critical("KILL SWITCH SUMMARY for user %s: %s", user_id, summary)
    return summary


async def clear_kill_switch(user_id: uuid.UUID, correlation_id: str, db: Session) -> None:
    """
    Clear the kill switch for a user, allowing order placement to resume.
    This is a deliberate, explicit action — it should never happen automatically.
    """
    kill_key = _KILL_SWITCH_KEY.format(user_id=user_id)
    await redis_client.delete(kill_key)

    _write_audit(
        db,
        user_id=user_id,
        correlation_id=correlation_id,
        action="KILL_SWITCH_CLEARED",
        entity_type="user",
        entity_id=str(user_id),
        details={"cleared_at": datetime.now(timezone.utc).isoformat()},
    )
    db.commit()
    logger.warning("Kill switch CLEARED for user %s [%s]", user_id, correlation_id)
