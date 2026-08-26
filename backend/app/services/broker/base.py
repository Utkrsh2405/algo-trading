"""
Broker-agnostic interface (Phase 2 — 🟡 vibe the shape, verify against the
real sandbox). Deliberately excludes order placement: that's Phase 5
(🔴 slow mode) and gets its own interface once a broker is chosen, with the
fail-closed / idempotency / rate-limiting properties documented in
docs/vibe-coding-plan.md.

Concrete brokers (Zerodha Kite Connect, Angel One SmartAPI, etc.) implement
this ABC in their own module under app/services/broker/, so the rest of the
app never imports a broker-specific class directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Balance:
    available_cash: float
    used_margin: float
    total_balance: float


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: int
    avg_price: float
    last_price: float


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: int
    avg_price: float
    unrealized_pnl: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    last_price: float
    timestamp: datetime

    def is_stale(self, max_age_seconds: float, now: datetime) -> bool:
        return (now - self.timestamp).total_seconds() > max_age_seconds


PriceCallback = Callable[[Quote], Awaitable[None]]


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


@dataclass
class PlacedOrder:
    """Returned by BrokerInterface.place_order() on success."""
    broker_order_id: str
    # The broker's status at the moment of placement (e.g. 'OPEN', 'COMPLETE')
    broker_status: str


class BrokerInterface(ABC):
    """
    All methods raise BrokerAuthError / BrokerConnectionError / BrokerRateLimitError
    (see exceptions.py) on failure — callers must not assume a bare exception
    means "safe to retry silently."
    """

    @abstractmethod
    async def authenticate(self) -> None:
        """Perform initial OAuth login / token exchange."""

    @abstractmethod
    async def refresh_token(self) -> None:
        """Refresh an expiring access token before it lapses."""

    @abstractmethod
    async def get_balance(self) -> Balance:
        ...

    @abstractmethod
    async def get_holdings(self) -> list[Holding]:
        ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        ...

    @abstractmethod
    async def subscribe_prices(self, symbols: list[str], on_quote: PriceCallback) -> None:
        """
        Open the broker's live-price WebSocket for the given symbols and
        invoke on_quote for every tick. Implementations must reconnect on
        drop with backoff — a silently dead feed is a correctness bug, not
        just a UX one, once anything downstream trades on these quotes.
        """

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        algo_tag: str | None = None,
    ) -> PlacedOrder:
        """
        Submit an order to the broker. Raises BrokerConnectionError or
        BrokerRateLimitError on failure. Never returns a partially-constructed
        result — either a full PlacedOrder or an exception.

        algo_tag: SEBI/broker compliance identifier for algorithmic orders.
          For Zerodha Kite this maps to the `tag` parameter (max 20 chars).
          VERIFY the required format against the broker's current live API
          docs — regulatory requirements and accepted formats change over time.
          Pass None for manual/non-algo orders.
        """

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> None:
        """
        Request cancellation of a pending order. Called by kill_switch().
        May raise BrokerConnectionError if the broker is unreachable — the
        kill switch must catch this and continue cancelling other orders rather
        than aborting the whole sweep.
        """

    @abstractmethod
    async def close(self) -> None:
        """Tear down the WebSocket connection and any background tasks."""
