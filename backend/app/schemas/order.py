import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(..., pattern="^(MARKET|LIMIT|SL|SL-M)$")
    quantity: int = Field(..., gt=0)
    price: float | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=128)
    strategy_id: uuid.UUID | None = None
    # SEBI/Zerodha compliance tag for algorithmic orders.
    # Max 20 chars (Kite Connect limit). Verify required format against
    # current broker API docs before going live.
    algo_tag: str | None = Field(default=None, max_length=20)


class OrderRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    strategy_id: uuid.UUID | None
    idempotency_key: str
    broker_order_id: str | None
    symbol: str
    side: str
    order_type: str
    quantity: int
    filled_quantity: int
    price: float | None
    status: str
    rejection_reason: str | None
    correlation_id: str | None
    algo_tag: str | None
    placed_at: datetime
    filled_at: datetime | None

    model_config = {"from_attributes": True}


class KillSwitchRequest(BaseModel):
    reason: str = Field(default="Manual kill switch triggered via API")
