import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from kiteconnect import KiteConnect, KiteTicker

from app.core.config import settings
from app.services.broker.base import (
    Balance, BrokerInterface, BrokerPosition, Holding, OrderSide, OrderType,
    PlacedOrder, PriceCallback, Quote,
)
from app.services.broker.exceptions import BrokerAuthError, BrokerConnectionError

logger = logging.getLogger(__name__)


class ZerodhaBroker(BrokerInterface):
    """
    Zerodha Kite Connect implementation of BrokerInterface.
    Wraps the synchronous kiteconnect library and its threaded KiteTicker.
    """

    def __init__(self, api_key: str, api_secret: str, access_token: str | None = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key)
        
        if access_token:
            self.kite.set_access_token(access_token)
            
        self.kws: KiteTicker | None = None
        self._price_callback: PriceCallback | None = None
        self._instrument_map: dict[int, str] = {}

    async def authenticate(self) -> None:
        """
        In a real scenario, the user performs OAuth login, gets a request_token,
        and exchanges it for an access_token. That exchange happens elsewhere
        (e.g. via a dedicated API endpoint). This method is a no-op if we already
        have the access_token.
        """
        if not self.kite.access_token:
            raise BrokerAuthError("Access token not available. Perform OAuth flow first.")

    async def refresh_token(self) -> None:
        """Kite Connect tokens are valid for the whole day. No refresh mechanism."""
        pass

    async def get_balance(self) -> Balance:
        if not self.kite.access_token:
            raise BrokerAuthError("Not authenticated")

        try:
            # kite.margins() is a sync call, run in thread to avoid blocking asyncio loop
            margins = await asyncio.to_thread(self.kite.margins)
            equity = margins.get("equity", {})
            return Balance(
                available_cash=equity.get("available", {}).get("cash", 0.0),
                used_margin=equity.get("utilised", {}).get("debits", 0.0),
                total_balance=equity.get("net", 0.0)
            )
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            raise BrokerConnectionError(f"Failed to fetch balance: {e}")

    async def get_holdings(self) -> list[Holding]:
        try:
            raw_holdings = await asyncio.to_thread(self.kite.holdings)
            return [
                Holding(
                    symbol=h["tradingsymbol"],
                    quantity=h["quantity"],
                    avg_price=h["average_price"],
                    last_price=h["last_price"]
                )
                for h in raw_holdings
            ]
        except Exception as e:
            logger.error(f"Failed to fetch holdings: {e}")
            raise BrokerConnectionError(f"Failed to fetch holdings: {e}")

    async def get_positions(self) -> list[BrokerPosition]:
        try:
            raw_positions = await asyncio.to_thread(self.kite.positions)
            net_positions = raw_positions.get("net", [])
            return [
                BrokerPosition(
                    symbol=p["tradingsymbol"],
                    quantity=p["quantity"],
                    avg_price=p["average_price"],
                    unrealized_pnl=p["pnl"]
                )
                for p in net_positions
            ]
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            raise BrokerConnectionError(f"Failed to fetch positions: {e}")

    def _fetch_instrument_map(self, symbols: list[str]) -> dict[str, int]:
        """Fetches instrument tokens for the requested symbols (sync call)."""
        instruments = self.kite.instruments(exchange="NSE")
        token_map = {}
        for inst in instruments:
            if inst['tradingsymbol'] in symbols:
                token_map[inst['tradingsymbol']] = inst['instrument_token']
        return token_map

    async def subscribe_prices(self, symbols: list[str], on_quote: PriceCallback) -> None:
        if not self.kite.access_token:
            raise BrokerAuthError("Access token not set")

        try:
            token_map = await asyncio.to_thread(self._fetch_instrument_map, symbols)
        except Exception as e:
            raise BrokerConnectionError(f"Failed to fetch instrument tokens: {e}")

        self._instrument_map = {v: k for k, v in token_map.items()}
        tokens = list(self._instrument_map.keys())

        if not tokens:
            logger.warning("No valid instrument tokens found for requested symbols.")
            return

        self._price_callback = on_quote
        self.kws = KiteTicker(self.api_key, self.kite.access_token)

        loop = asyncio.get_running_loop()

        def on_ticks(ws: KiteTicker, ticks: list[dict[str, Any]]) -> None:
            # Called from the KiteTicker twisted/threaded loop
            for tick in ticks:
                instrument_token = tick['instrument_token']
                if instrument_token in self._instrument_map:
                    symbol = self._instrument_map[instrument_token]
                    last_price = tick['last_price']
                    
                    # Ensure timestamp has timezone if it's missing
                    ts = tick.get('exchange_timestamp')
                    if ts is None:
                        ts = datetime.now(timezone.utc)
                    elif ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    quote = Quote(symbol=symbol, last_price=last_price, timestamp=ts)
                    
                    # Fire callback in the main asyncio event loop
                    if self._price_callback:
                        asyncio.run_coroutine_threadsafe(self._price_callback(quote), loop)

        def on_connect(ws: KiteTicker, response: Any) -> None:
            logger.info("KiteTicker connected. Subscribing to tokens: %s", tokens)
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_LTP, tokens)

        def on_close(ws: KiteTicker, code: int, reason: str) -> None:
            logger.warning("KiteTicker connection closed: %d - %s", code, reason)

        self.kws.on_ticks = on_ticks
        self.kws.on_connect = on_connect
        self.kws.on_close = on_close

        # Connect the WebSocket in a background thread
        logger.info("Starting KiteTicker thread...")
        self.kws.connect(threaded=True)

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
        Places an order via Kite Connect REST API.
        Runs the synchronous kite.place_order() on a worker thread.
        Raises BrokerConnectionError on any failure so the order service
        always sees a typed exception, never a raw kiteconnect error.

        algo_tag maps to Kite's `tag` parameter (max 20 chars per Kite docs).
        ⚠ VERIFY the exact required format against the current Kite Connect
        API docs and SEBI circular applicable at the time of going live.
        """
        if not self.kite.access_token:
            raise BrokerAuthError("Access token not set — authenticate first")

        # Kite Connect tag field: max 20 characters (alphanumeric, no spaces).
        # Truncate with a warning rather than hard-failing — a truncated tag is
        # still compliance-tagged; a failed order is not.
        kite_tag: str | None = None
        if algo_tag:
            if len(algo_tag) > 20:
                logger.warning(
                    "algo_tag %r is %d chars, truncating to 20 for Kite tag field. "
                    "VERIFY the required format in current Kite Connect docs.",
                    algo_tag, len(algo_tag),
                )
                kite_tag = algo_tag[:20]
            else:
                kite_tag = algo_tag

        # Map our canonical enums to Kite's string constants
        kite_transaction = "BUY" if side == OrderSide.BUY else "SELL"
        kite_order_type = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.SL: "SL",
            OrderType.SL_M: "SL-M",
        }[order_type]

        def _do_place() -> str:
            return self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=kite_transaction,
                quantity=quantity,
                order_type=kite_order_type,
                product=self.kite.PRODUCT_CNC,
                price=price,
                tag=kite_tag,  # SEBI algo compliance tag
            )

        try:
            broker_order_id = await asyncio.to_thread(_do_place)
            return PlacedOrder(
                broker_order_id=str(broker_order_id),
                broker_status="OPEN",
            )
        except Exception as e:
            logger.error("Kite place_order failed for %s: %s", symbol, e)
            raise BrokerConnectionError(f"Broker rejected order: {e}") from e

    async def cancel_order(self, broker_order_id: str) -> None:
        """
        Cancels a PENDING order via Kite Connect REST API.
        Called by kill_switch() — must NOT propagate kiteconnect-specific errors;
        wraps them in BrokerConnectionError so the kill switch can continue
        through its cancellation loop even if individual cancels fail.
        """
        if not self.kite.access_token:
            raise BrokerAuthError("Access token not set — authenticate first")

        def _do_cancel() -> None:
            self.kite.cancel_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=broker_order_id,
            )

        try:
            await asyncio.to_thread(_do_cancel)
        except Exception as e:
            logger.error("Kite cancel_order failed for %s: %s", broker_order_id, e)
            raise BrokerConnectionError(f"Broker cancel failed: {e}") from e

    async def close(self) -> None:
        if self.kws:
            self.kws.close()
            self.kws = None
