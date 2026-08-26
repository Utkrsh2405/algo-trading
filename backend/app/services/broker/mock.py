"""
In-process paper broker for local development and demos before a real
broker is chosen/wired up. Never used for live trading — it exists purely
so Phase 3+ (price streaming, dashboard, strategy scaffolding) has
something to run against without a real broker connection.
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone

from app.services.broker.base import (
    Balance, BrokerInterface, BrokerPosition, Holding, OrderSide, OrderType,
    PlacedOrder, PriceCallback, Quote,
)
from app.services.broker.exceptions import BrokerConnectionError


class MockBroker(BrokerInterface):
    def __init__(self, starting_cash: float = 100_000.0) -> None:
        self._cash = starting_cash
        self._prices: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        # Track mock-placed orders so cancel_order can find them
        self._orders: dict[str, str] = {}  # broker_order_id → status
        # Track mock positions
        self._mock_positions: dict[str, int] = {}

    async def authenticate(self) -> None:
        return None

    async def refresh_token(self) -> None:
        return None

    async def get_balance(self) -> Balance:
        return Balance(available_cash=self._cash, used_margin=0.0, total_balance=self._cash)

    async def get_holdings(self) -> list[Holding]:
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        # Convert our mock positions dict to the expected output
        positions = []
        for symbol, qty in self._mock_positions.items():
            if qty != 0:
                avg_price = self._prices.get(symbol, 100.0)
                positions.append(BrokerPosition(
                    symbol=symbol,
                    quantity=qty,
                    average_price=avg_price,
                    pnl=0.0,
                    realized=0.0,
                    unrealized=0.0
                ))
        return positions

    async def subscribe_prices(self, symbols: list[str], on_quote: PriceCallback) -> None:
        for symbol in symbols:
            self._prices.setdefault(symbol, 100.0 + random.random() * 900)

        self._running = True

        async def _tick_loop() -> None:
            while self._running:
                for symbol in symbols:
                    drift = random.uniform(-0.5, 0.5)
                    self._prices[symbol] = max(0.05, self._prices[symbol] + drift)
                    await on_quote(
                        Quote(
                            symbol=symbol,
                            last_price=round(self._prices[symbol], 2),
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
                await asyncio.sleep(1)

        self._task = asyncio.create_task(_tick_loop())

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        algo_tag: str | None = None,  # accepted but ignored in paper trading
    ) -> PlacedOrder:
        """Simulates an immediate COMPLETE fill with a generated order ID."""
        broker_order_id = f"MOCK-{uuid.uuid4().hex[:10].upper()}"
        self._orders[broker_order_id] = "COMPLETE"
        
        # Update mock positions
        current_qty = self._mock_positions.get(symbol, 0)
        qty_change = quantity if side == OrderSide.BUY else -quantity
        self._mock_positions[symbol] = current_qty + qty_change
        
        return PlacedOrder(broker_order_id=broker_order_id, broker_status="COMPLETE")

    async def cancel_order(self, broker_order_id: str) -> None:
        """Marks a mock order as CANCELLED. Raises if the order does not exist."""
        if broker_order_id not in self._orders:
            raise BrokerConnectionError(f"Mock order {broker_order_id} not found")
        self._orders[broker_order_id] = "CANCELLED"

    async def close(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
