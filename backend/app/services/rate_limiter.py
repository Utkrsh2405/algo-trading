"""
Token-bucket rate limiter implemented in Redis using an atomic Lua script.

Why Lua? Because Redis executes Lua scripts atomically — there is no race
window between the "check" and the "decrement" steps. A plain GET-then-SET
in Python would allow two concurrent callers to both see tokens=1, both
decide to proceed, and both decrement, ending up at -1.

The bucket allows `capacity` tokens per `window_seconds`. Tokens refill
continuously (not in discrete minute-windows) so a user who places 15 orders
in the first 30 s of a minute, waits 30 s, and then places 15 more is
treated correctly — they're within the per-minute limit even though both
bursts touch the same Redis key.
"""

import logging

from app.core.redis import redis_client
from app.services.broker.exceptions import OrderRateLimitError

logger = logging.getLogger(__name__)

# Atomic Lua script: check remaining tokens, decrement if available.
# Returns 1 if the request is allowed, 0 if the bucket is exhausted.
#
# KEYS[1] = bucket key (e.g. "rate_limit:user:<uuid>")
# ARGV[1] = capacity  (max tokens, == max_orders_per_minute from RiskLimit)
# ARGV[2] = window    (seconds for a full refill, e.g. 60)
# ARGV[3] = now_ms    (current time as integer milliseconds, for refill calc)
_LUA_TOKEN_BUCKET = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])   -- seconds
local now_ms   = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
local tokens        = tonumber(data[1]) or capacity
local last_refill   = tonumber(data[2]) or now_ms

-- Refill: tokens_per_ms = capacity / (window * 1000)
local elapsed_ms = now_ms - last_refill
local refill = math.floor(elapsed_ms * capacity / (window * 1000))
tokens = math.min(capacity, tokens + refill)

if tokens < 1 then
    -- Bucket empty — update last_refill so the timer keeps running
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill_ms', now_ms)
    redis.call('EXPIRE', key, window * 2)
    return 0
end

-- Consume one token
tokens = tokens - 1
redis.call('HMSET', key, 'tokens', tokens, 'last_refill_ms', now_ms)
redis.call('EXPIRE', key, window * 2)
return 1
"""


async def check_rate_limit(user_id: str, capacity: int, window_seconds: int = 60) -> None:
    """
    Consume one token from the user's rate-limit bucket.

    Raises OrderRateLimitError if the bucket is exhausted.
    Does NOT raise on Redis errors — a Redis failure here should not
    silently allow unlimited orders, so we re-raise any Redis exception
    as OrderRateLimitError (fail-closed behaviour).

    Args:
        user_id:        The user's UUID string (used as part of the Redis key).
        capacity:       Total tokens per window (== RiskLimit.max_orders_per_minute).
        window_seconds: How many seconds until the bucket fully refills (default 60).
    """
    import time
    key = f"rate_limit:user:{user_id}"
    now_ms = int(time.time() * 1000)

    try:
        allowed = await redis_client.eval(
            _LUA_TOKEN_BUCKET,
            1,           # number of KEYS
            key,         # KEYS[1]
            capacity,    # ARGV[1]
            window_seconds,  # ARGV[2]
            now_ms,      # ARGV[3]
        )
    except Exception as exc:
        # Redis is unreachable — fail closed: block the order
        logger.error("Rate limiter Redis error for user %s: %s", user_id, exc)
        raise OrderRateLimitError(
            f"Rate limiter unavailable (fail-closed): {exc}"
        ) from exc

    if not allowed:
        logger.warning(
            "Rate limit exhausted for user %s (capacity=%d per %ds)",
            user_id, capacity, window_seconds,
        )
        raise OrderRateLimitError(
            f"Order rate limit of {capacity} orders/{window_seconds}s exceeded. "
            "Back off before retrying."
        )
