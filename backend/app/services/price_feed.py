import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import SessionLocal
from app.models.price_history import PriceHistory
from app.services.broker.base import BrokerInterface, Quote
from app.services.connection_manager import price_connection_manager
from app.services.price_cache import set_latest_price

logger = logging.getLogger(__name__)


def _save_tick(quote: Quote) -> None:
    """Runs on a worker thread via asyncio.to_thread — SQLAlchemy's sync
    Session must not be driven directly from the event loop."""
    db = SessionLocal()
    try:
        stmt = (
            pg_insert(PriceHistory)
            .values(
                symbol=quote.symbol,
                timestamp=quote.timestamp,
                open=quote.last_price,
                high=quote.last_price,
                low=quote.last_price,
                close=quote.last_price,
                volume=0,
            )
            .on_conflict_do_nothing(constraint="uq_price_symbol_ts")
        )
        db.execute(stmt)
        db.commit()
    finally:
        db.close()


class PriceFeedService:
    """
    Wires a BrokerInterface's live quotes to: TimescaleDB persistence,
    the Redis latest-price cache, and the WebSocket broadcast to dashboard
    clients. One instance per running broker connection.
    """

    def __init__(self, broker: BrokerInterface, max_staleness_seconds: float = 5.0, watchdog_interval: float = 2.0) -> None:
        self._broker = broker
        self._max_staleness = max_staleness_seconds
        self._watchdog_interval = watchdog_interval
        self._last_quote_time: datetime | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._feed_down = True  # Assume down until first quote
        self.on_quote_callbacks: list = []

    async def start(self, symbols: list[str]) -> None:
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        await self._broker.subscribe_prices(symbols, self._on_quote)

    async def stop(self) -> None:
        if self._watchdog_task:
            self._watchdog_task.cancel()
        await self._broker.close()

    @property
    def is_feed_down(self) -> bool:
        return self._feed_down

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(self._watchdog_interval)
            if self._last_quote_time is None:
                continue
            
            now = datetime.now(timezone.utc)
            seconds_since_last = (now - self._last_quote_time).total_seconds()
            
            if seconds_since_last > self._max_staleness and not self._feed_down:
                logger.warning(f"Price feed is DOWN (no quotes for {seconds_since_last:.1f}s)")
                self._feed_down = True
                await price_connection_manager.broadcast({"type": "feed_status", "status": "down"})

    async def _on_quote(self, quote: Quote) -> None:
        now = datetime.now(timezone.utc)
        self._last_quote_time = now

        if self._feed_down:
            logger.info("Price feed is UP")
            self._feed_down = False
            await price_connection_manager.broadcast({"type": "feed_status", "status": "up"})

        if quote.is_stale(self._max_staleness, now):
            logger.warning(f"Stale quote received for {quote.symbol}: {quote.timestamp}")
            return  # Drop stale quotes to prevent acting on them

        try:
            await asyncio.to_thread(_save_tick, quote)
        except Exception:
            logger.exception("Failed to persist price tick for %s", quote.symbol)

        await set_latest_price(quote)
        
        # Broadcast to dashboard
        await price_connection_manager.broadcast(
            {
                "type": "quote",
                "symbol": quote.symbol,
                "last_price": quote.last_price,
                "timestamp": quote.timestamp.isoformat(),
            }
        )

        # Notify strategy engine components
        for callback in self.on_quote_callbacks:
            try:
                await callback(quote)
            except Exception:
                logger.exception("Strategy callback failed")
