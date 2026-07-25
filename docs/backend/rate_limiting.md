# Sliding-Window Rate Limiting

Sentinel implements a sliding-window rate limiter powered by Redis Sorted Sets (ZSETs) in `src/core/rate_limiter.py`.

---

## Key Libraries Used

* **`redis.asyncio.client.Pipeline`**: Executes atomic Redis transactional commands in a single network round-trip.
* **`fastapi.HTTPException`**: Raises `429 Too Many Requests` when limits are exceeded.

---

## Rate Limiting Algorithm

Unlike simple fixed window counters (which allow traffic spikes at window boundaries), Sentinel uses a **Sliding Window Log** algorithm with timestamp scores:

```
[Window Start: now - 86,400s] [Current Time: now]
 │ │
 ▼ ▼
───────┬────────────┬────────────┬────────────┬────────────┬───────┤
 │ Timestamp1 │ Timestamp2 │ Timestamp3 │ Timestamp4 │ │
───────┴────────────┴────────────┴────────────┴────────────┴───────┘
 (Pruned by ZREMRANGEBYSCORE) (Counted by ZCARD)
```

---

## Implementation (`src/core/rate_limiter.py`)

```python
async def enforce_rate_limit(user_id: str, action: str, limit: int, window_seconds: int = 86400) -> None:
 r = get_redis_client()
 now = time.time()
 key = f"rate:{user_id}:{action}"

 async with r.pipeline(transaction=True) as pipe:
 # 1. Remove elements older than (now - window_seconds)
 pipe.zremrangebyscore(key, 0, now - window_seconds)
 # 2. Count remaining elements in window
 pipe.zcard(key)
 # 3. Add current timestamp score
 pipe.zadd(key, {f"{now}": now})
 # 4. Set key expiration to auto-clean idle users
 pipe.expire(key, window_seconds)
 results = await pipe.execute()

 count_in_window = results[1]
 if count_in_window >= limit:
 raise HTTPException(
 status_code=429,
 detail=f"Rate limit exceeded for {action}. Maximum allowed: {limit} per {window_seconds // 3600} hours."
 )
```

---

## Active Limits Set in Sentinel

| Action Endpoint | Redis Key Action | Limit | Window |
|---|---|---|---|
| `POST /api/research` | `research_run` | **10 runs** | 24 Hours |
| `POST /api/chat` | `chat_message` | **30 messages** | 24 Hours |
| `POST /api/chat/stream` | `chat_message` | **30 messages** | 24 Hours |
