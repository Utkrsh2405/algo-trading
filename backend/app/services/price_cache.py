import json
from datetime import datetime, timezone

from app.core.redis import redis_client
from app.services.broker.base import Quote

LATEST_PRICE_KEY_PREFIX = "price:latest:"
# A quote sitting in the cache past this age is treated as stale by readers,
# independent of whatever staleness check the broker feed itself applies.
CACHE_TTL_SECONDS = 30


async def set_latest_price(quote: Quote) -> None:
    key = f"{LATEST_PRICE_KEY_PREFIX}{quote.symbol}"
    payload = json.dumps({"last_price": quote.last_price, "timestamp": quote.timestamp.isoformat()})
    await redis_client.set(key, payload, ex=CACHE_TTL_SECONDS)


async def get_latest_price(symbol: str) -> Quote | None:
    raw = await redis_client.get(f"{LATEST_PRICE_KEY_PREFIX}{symbol}")
    if raw is None:
        return None
    data = json.loads(raw)
    return Quote(
        symbol=symbol,
        last_price=data["last_price"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )


async def get_latest_prices(symbols: list[str]) -> dict[str, Quote | None]:
    return {symbol: await get_latest_price(symbol) for symbol in symbols}
