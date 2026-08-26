from collections import deque
import logging

from app.services.broker.base import Quote
from app.services.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class SMACrossoverStrategy(BaseStrategy):
    """
    A simple moving average crossover strategy.
    Maintains a fast and slow moving average of incoming ticks for a specific symbol.
    Emits a BUY signal when fast crosses above slow.
    Emits a SELL signal when fast crosses below slow.
    """
    def __init__(self, strategy_id: str, name: str, config: dict):
        super().__init__(strategy_id, name, config)
        self.symbol = config.get("symbol", "RELIANCE")
        self.fast_window = int(config.get("fast_window", 10))
        self.slow_window = int(config.get("slow_window", 50))
        self.trade_qty = int(config.get("quantity", 1))
        
        self.prices = deque(maxlen=self.slow_window)
        self.current_position = 0  # 1 for Long, -1 for Short, 0 for Flat

    def on_start(self) -> None:
        # Clear prices on start so it requires a fresh buildup of data
        self.prices.clear()
        self.current_position = 0
        logger.info("%s started. Fast window: %d, Slow window: %d, Target: %s", 
                    self.name, self.fast_window, self.slow_window, self.symbol)

    async def on_price_update(self, quote: Quote) -> None:
        if quote.symbol != self.symbol:
            return

        self.prices.append(quote.last_price)

        if len(self.prices) < self.slow_window:
            # Not enough data to calculate slow moving average
            return

        # Calculate SMAs
        fast_sma = sum(list(self.prices)[-self.fast_window:]) / self.fast_window
        slow_sma = sum(self.prices) / self.slow_window

        # Check for crossovers
        if fast_sma > slow_sma and self.current_position <= 0:
            logger.info("Fast SMA (%.2f) > Slow SMA (%.2f). Emitting BUY.", fast_sma, slow_sma)
            self.emit_signal(self.symbol, "BUY", self.trade_qty)
            self.current_position = 1

        elif fast_sma < slow_sma and self.current_position >= 0:
            logger.info("Fast SMA (%.2f) < Slow SMA (%.2f). Emitting SELL.", fast_sma, slow_sma)
            self.emit_signal(self.symbol, "SELL", self.trade_qty)
            self.current_position = -1
