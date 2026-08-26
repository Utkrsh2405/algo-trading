import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.services.broker.base import Quote

logger = logging.getLogger(__name__)


@dataclass
class StrategyState:
    id: str
    name: str
    is_running: bool
    config: dict[str, Any]
    status_message: str = "Stopped"


class BaseStrategy(ABC):
    """
    Base class for trading strategies.
    Strategies hold state, consume price ticks, and yield trade signals.
    """
    def __init__(self, strategy_id: str, name: str, config: dict[str, Any]):
        self.id = strategy_id
        self.name = name
        self.config = config
        self.is_running = False
        self.status_message = "Stopped"

    @abstractmethod
    async def on_price_update(self, quote: Quote) -> None:
        """
        Called every time a new, non-stale price tick arrives if the strategy is running.
        Inside this method, the strategy should call self.emit_signal(...) to trade.
        """
        pass

    def start(self) -> None:
        self.is_running = True
        self.status_message = "Running"
        self.on_start()
        logger.info("Strategy %s (%s) started", self.name, self.id)

    def stop(self, reason: str = "Stopped manually") -> None:
        self.is_running = False
        self.status_message = reason
        self.on_stop()
        logger.info("Strategy %s (%s) stopped: %s", self.name, self.id, reason)

    def on_start(self) -> None:
        """Hook for initialization when started."""
        pass

    def on_stop(self) -> None:
        """Hook for cleanup when stopped."""
        pass

    # A callback injected by the engine to place orders
    _signal_callback = None

    def emit_signal(self, symbol: str, side: str, quantity: int) -> None:
        """
        Emit a trade signal to the engine.
        side: "BUY" or "SELL"
        """
        if not self.is_running:
            logger.warning("Strategy %s emitted signal while stopped", self.id)
            return
            
        logger.info("Strategy %s emitted signal: %s %s %d", self.id, side, symbol, quantity)
        if self._signal_callback:
            self._signal_callback(self, symbol, side, quantity)

    def get_state(self) -> StrategyState:
        return StrategyState(
            id=self.id,
            name=self.name,
            is_running=self.is_running,
            config=self.config,
            status_message=self.status_message,
        )
