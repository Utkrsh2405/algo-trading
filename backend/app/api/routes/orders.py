"""
Order placement API routes — Phase 5 🔴 Slow Mode.

These routes sit between the HTTP layer and the order/risk services.
They are intentionally thin — all business logic lives in services/order.py.

The kill-switch endpoint is deliberately separated from normal order routes
so it can be easily found, audited, and eventually locked down to specific
IP ranges or given a higher auth requirement.
"""

import uuid
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.order import Order
from app.models.risk_limit import RiskLimit
from app.models.user import User
from app.schemas.order import KillSwitchRequest, OrderCreate, OrderRead
from app.services.broker.exceptions import (
    BrokerConnectionError,
    DuplicateOrderError,
    KillSwitchActiveError,
    OrderRateLimitError,
    RiskCheckError,
)
from app.services.order import clear_kill_switch, kill_switch, place_order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _get_broker(request: Request):
    """Extract the broker from app state, injected during lifespan."""
    return request.app.state.price_feed._broker


def _new_correlation_id() -> str:
    return uuid.uuid4().hex


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Place a new order through the full safety stack:
    kill-switch → idempotency → risk check → rate limit → broker.
    """
    broker = _get_broker(request)
    correlation_id = _new_correlation_id()

    # Fetch rate limit for this user (use account-wide row)
    risk_limit = (
        db.query(RiskLimit)
        .filter(RiskLimit.user_id == current_user.id, RiskLimit.strategy_id.is_(None))
        .first()
    )
    max_orders_per_minute = risk_limit.max_orders_per_minute if risk_limit else 30

    try:
        # Resolve algo_tag: payload takes precedence, then env-level default.
        # For SEBI compliance every algo order must carry the registered tag.
        # If neither is set and this is an algo order, log a warning.
        resolved_algo_tag = payload.algo_tag or settings.KITE_ALGO_TAG
        if resolved_algo_tag is None:
            logger.warning(
                "No algo_tag on order from user %s. "
                "Set KITE_ALGO_TAG in .env or pass algo_tag in the request for SEBI compliance.",
                current_user.id,
            )

        order = await place_order(
            db,
            broker,
            user_id=current_user.id,
            strategy_id=payload.strategy_id,
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            order_type=payload.order_type,
            price=payload.price,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            max_orders_per_minute=max_orders_per_minute,
            algo_tag=resolved_algo_tag,
        )
    except KillSwitchActiveError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DuplicateOrderError as exc:
        # 200 OK (not 409) — the client gets the idempotent result
        existing = (
            db.query(Order)
            .filter(Order.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing:
            return existing
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (RiskCheckError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except OrderRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except BrokerConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return order


@router.get("", response_model=list[OrderRead])
def list_orders(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List orders for the current user, newest first."""
    return (
        db.query(Order)
        .filter(Order.user_id == current_user.id)
        .order_by(Order.placed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single order by ID. Only returns orders owned by the current user."""
    order = db.get(Order, order_id)
    if order is None or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.post(
    "/kill-switch",
    status_code=status.HTTP_200_OK,
    summary="Engage kill switch — cancels all pending orders and halts trading",
)
async def engage_kill_switch(
    payload: KillSwitchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    🔴 Immediately blocks all order placement for this account,
    deactivates all strategies, and attempts to cancel every pending order.

    This endpoint is idempotent — calling it when the switch is already
    active is safe and returns the same response.
    """
    broker = _get_broker(request)
    correlation_id = _new_correlation_id()

    summary = await kill_switch(
        db,
        broker,
        user_id=current_user.id,
        correlation_id=correlation_id,
        reason=payload.reason,
    )
    return summary


@router.delete(
    "/kill-switch",
    status_code=status.HTTP_200_OK,
    summary="Clear kill switch — allows trading to resume",
)
async def disengage_kill_switch(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    ⚠️ Clears the kill switch so orders can be placed again.
    This action is logged to audit_log.
    """
    correlation_id = _new_correlation_id()
    await clear_kill_switch(current_user.id, correlation_id, db)
    return {"kill_switch": "cleared", "message": "Trading is now re-enabled for your account."}
