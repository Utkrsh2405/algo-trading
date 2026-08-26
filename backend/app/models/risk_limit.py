import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiskLimit(Base):
    """
    strategy_id is nullable: a NULL strategy_id row is the account-wide limit,
    aggregated across all strategies for a user. Enforcement must check the
    account-wide row in addition to any per-strategy row — never one alone.
    """

    __tablename__ = "risk_limits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True, index=True
    )
    max_daily_loss: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    max_position_size: Mapped[int] = mapped_column(nullable=False)
    max_orders_per_minute: Mapped[int] = mapped_column(nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
