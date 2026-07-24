import os
import json
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator
import redis.asyncio as aioredis
from src.config import Config

_redis_client: Optional[aioredis.Redis] = None

def get_redis_client() -> aioredis.Redis:
    """Returns an async Redis client instance connecting to REDIS_URL."""
    global _redis_client
    if _redis_client is None:
        redis_url = Config.REDIS_URL or os.environ.get("REDIS_URL", "")
        if not redis_url:
            raise ValueError("REDIS_URL is not configured in .env")
        
        # Ensure rediss:// scheme for Upstash TLS
        if redis_url.startswith("redis://") and "upstash.io" in redis_url:
            redis_url = redis_url.replace("redis://", "rediss://", 1)

        _redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10
        )
    return _redis_client


async def set_run_state(run_id: str, data: Dict[str, Any], expire_seconds: int = 86400) -> None:
    """Stores run state in Redis hash `run:{run_id}`."""
    r = get_redis_client()
    key = f"run:{run_id}"
    serialized = {k: (json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v)) for k, v in data.items()}
    await r.hset(key, mapping=serialized)
    await r.expire(key, expire_seconds)


async def get_run_state(run_id: str) -> Dict[str, Any]:
    """Retrieves run state from Redis hash `run:{run_id}`."""
    r = get_redis_client()
    key = f"run:{run_id}"
    data = await r.hgetall(key)
    if not data:
        return {}
    
    parsed = {}
    for k, v in data.items():
        try:
            parsed[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            parsed[k] = v
    return parsed


async def publish_run_event(run_id: str, event: Dict[str, Any]) -> None:
    """Publishes a JSON event to channel `sse:{run_id}` for SSE clients."""
    r = get_redis_client()
    channel = f"sse:{run_id}"
    await r.publish(channel, json.dumps(event))


async def subscribe_run_events(run_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Async generator subscribing to Redis channel `sse:{run_id}`."""
    r = get_redis_client()
    pubsub = r.pubsub()
    channel = f"sse:{run_id}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message and message.get("type") == "message":
                try:
                    payload = json.loads(message["data"])
                    yield payload
                except json.JSONDecodeError:
                    continue
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


async def mark_run_cancelled(run_id: str, expire_seconds: int = 86400) -> None:
    """Adds run_id to the cancelled set in Redis."""
    r = get_redis_client()
    await r.sadd("cancellations", run_id)
    await r.expire("cancellations", expire_seconds)


async def is_run_cancelled(run_id: str) -> bool:
    """Checks if a run_id is in the cancelled set."""
    r = get_redis_client()
    return await r.sismember("cancellations", run_id)


async def set_run_approval(run_id: str, approved: bool = True) -> None:
    """Sets human-in-the-loop approval status for a run_id."""
    r = get_redis_client()
    key = f"run:{run_id}:approved"
    await r.set(key, "1" if approved else "0", ex=3600)


async def is_run_approved(run_id: str) -> bool:
    """Checks if human approval has been granted for a run_id."""
    r = get_redis_client()
    key = f"run:{run_id}:approved"
    val = await r.get(key)
    return val == "1"
