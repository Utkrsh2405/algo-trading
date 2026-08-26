import logging
from abc import ABC, abstractmethod
from typing import Type

from app.services.broker.base import Quote
from app.services.price_feed import PriceFeedService

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Base class for all trading strategies. 
    Concrete implementations will hold the actual trading logic.
    """
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def on_price_update(self, quote: Quote) -> None:
        """
        Called every time a new, non-stale price tick arrives.
        Order placement and risk checks will be called from here.
        """
        pass


class StrategyEngine:
    """
    Manages active strategies and routes live quotes to them.
    Enforces safety properties like feed-down halting.
    """
    def __init__(self, price_feed: PriceFeedService):
        self.price_feed = price_feed
        self.active_strategies: list[BaseStrategy] = []
        # Register to receive live quotes from the feed
        self.price_feed.on_quote_callbacks.append(self._handle_quote)

    def load_strategy(self, strategy: BaseStrategy):
        self.active_strategies.append(strategy)

    async def _handle_quote(self, quote: Quote) -> None:
        """
        Routes the quote to all active strategies if the feed is healthy.
        """
        if self.price_feed.is_feed_down:
            logger.warning("StrategyEngine ignoring quote: Price feed is marked DOWN.")
            return

        for strategy in self.active_strategies:
            try:
                await strategy.on_price_update(quote)
            except Exception:
                # We must not let one strategy crash the engine or other strategies
                logger.exception("Strategy %s raised an exception during on_price_update", strategy.__class__.__name__)


class BacktestResult:
    def __init__(self, pnl: float, sharpe: float, max_drawdown: float, win_rate: float):
        self.pnl = pnl
        self.sharpe = sharpe
        self.max_drawdown = max_drawdown
        self.win_rate = win_rate


def run_backtest(strategy_cls: Type[BaseStrategy], config: dict, historical_data: list[Quote]) -> BacktestResult:
    """
    Stub for running a backtest on historical data.
    Will simulate execution of on_price_update over historical ticks.
    """
    logger.info("Running backtest for %s over %d ticks", strategy_cls.__name__, len(historical_data))
    
    # TODO: Implement actual simulation loop and metrics calculation
    # For now, return a zeroed result as a scaffold
    return BacktestResult(
        pnl=0.0,
        sharpe=0.0,
        max_drawdown=0.0,
        win_rate=0.0
    )
