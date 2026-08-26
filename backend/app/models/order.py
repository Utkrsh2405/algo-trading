import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    """
    idempotency_key is unique so a duplicate place_order() call with the same
    key cannot create a second row — enforce this at the DB level, not just
    in application code.
    """

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY / SELL
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)  # MARKET / LIMIT / SL / SL-M
    quantity: Mapped[int] = mapped_column(nullable=False)
    filled_quantity: Mapped[int] = mapped_column(nullable=False, default=0)  # Updated on fills/partial-fills
    price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # correlation_id ties this row to its audit_log chain: signal→risk check→broker call→fill
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # algo_tag: SEBI/broker compliance tag identifying the algorithm.
    # Zerodha Kite: this maps to the `tag` parameter (max 20 chars).
    # IMPORTANT: Verify the required format against the current Kite Connect
    # API docs before going live — the format has changed in the past and
    # this document may lag behind regulatory updates.
    algo_tag: Mapped[str | None] = mapped_column(String(64), nullable=True, index=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
