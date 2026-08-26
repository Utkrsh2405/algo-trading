import asyncio
import logging
import uuid

from app.db.session import SessionLocal
from app.services.broker.base import BrokerInterface, Quote
from app.services.order import place_order
from app.services.price_feed import PriceFeedService
from app.services.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    Manages active strategies and routes live quotes to them.
    Executes trades when strategies emit signals.
    """
    def __init__(self, price_feed: PriceFeedService, broker: BrokerInterface):
        self.price_feed = price_feed
        self.broker = broker
        self.strategies: dict[str, BaseStrategy] = {}
        # Register to receive live quotes from the feed
        self.price_feed.on_quote_callbacks.append(self._handle_quote)

    def load_strategy(self, strategy: BaseStrategy):
        if strategy.id in self.strategies:
            raise ValueError(f"Strategy {strategy.id} already loaded")
            
        strategy._signal_callback = self._on_strategy_signal
        self.strategies[strategy.id] = strategy
        logger.info("Loaded strategy %s (%s)", strategy.name, strategy.id)

    def get_strategy(self, strategy_id: str) -> BaseStrategy | None:
        return self.strategies.get(strategy_id)

    def start_strategy(self, strategy_id: str) -> None:
        strat = self.get_strategy(strategy_id)
        if strat:
            strat.start()

    def stop_strategy(self, strategy_id: str, reason: str = "Stopped manually") -> None:
        strat = self.get_strategy(strategy_id)
        if strat:
            strat.stop(reason)

    async def _handle_quote(self, quote: Quote) -> None:
        """
        Routes the quote to all RUNNING strategies if the feed is healthy.
        """
        if self.price_feed.is_feed_down:
            # If the feed is down, stop all running strategies for safety
            for strat in self.strategies.values():
                if strat.is_running:
                    strat.stop("Broker feed is down/stale. Trading halted.")
            return

        for strat in self.strategies.values():
            if strat.is_running:
                try:
                    await strat.on_price_update(quote)
                except Exception:
                    logger.exception("Strategy %s raised an exception during on_price_update. Stopping it.", strat.id)
                    strat.stop("Fatal error during execution")

    def _on_strategy_signal(self, strategy: BaseStrategy, symbol: str, side: str, quantity: int) -> None:
        """
        Callback fired by a strategy when it wants to trade.
        We spawn an async task to place the order so we don't block the price feed loop.
        """
        # For this skeleton, we assume all strategies belong to a system user or the first user.
        # In a multi-tenant system, the strategy would track which user it belongs to.
        # We will look up the first user in the DB to execute the trade.
        asyncio.create_task(self._execute_signal(strategy, symbol, side, quantity))

    async def _execute_signal(self, strategy: BaseStrategy, symbol: str, side: str, quantity: int) -> None:
        from app.models.user import User
        db = SessionLocal()
        try:
            user = db.query(User).first()
            if not user:
                logger.error("No user found in DB to execute strategy trade.")
                strategy.stop("No user configured")
                return

            # Note: A real system would have a robust strategy_id UUID. We just use a hash or a fixed UUID for now.
            # Using UUID namespace to generate a stable UUID from strategy ID string.
            strategy_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, strategy.id)
            
            await place_order(
                db=db,
                broker=self.broker,
                user_id=user.id,
                strategy_id=strategy_uuid,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type="MARKET",
                price=None,
                idempotency_key=f"strat-{strategy.id}-{uuid.uuid4()}",
                correlation_id=f"signal-{uuid.uuid4()}",
                algo_tag=strategy.name.upper().replace(" ", "")[:20]
            )
        except Exception as e:
            logger.error("Failed to execute signal for strategy %s: %s", strategy.id, e)
            # Stop the strategy if it starts generating failing orders (fail-safe)
            strategy.stop(f"Order placement failed: {e}")
        finally:
            db.close()
