import time
from fastapi import HTTPException
from src.core.redis_state import get_redis_client

async def enforce_rate_limit(user_id: str, action: str, limit: int, window_seconds: int = 86400) -> None:
    """
    Enforces sliding-window rate limiting via Redis Sorted Sets (zset).
    - action: e.g. "research_run", "chat_qa"
    - limit: max allowed requests in window
    - window_seconds: default 86400 (24 hours)
    """
    r = get_redis_client()
    now = time.time()
    key = f"rate:{user_id}:{action}"

    async with r.pipeline(transaction=True) as pipe:
        # Clear items older than (now - window_seconds)
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        # Count remaining items in window
        pipe.zcard(key)
        # Add current timestamp
        pipe.zadd(key, {f"{now}": now})
        # Set expire on key to auto-clean
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

    count_in_window = results[1]
    if count_in_window >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {action}. Maximum allowed: {limit} per {window_seconds // 3600} hours."
        )
