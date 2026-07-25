# Redis State Manager & Pub/Sub Broker

Sentinel uses **Upstash Redis** (via `redis.asyncio`) for distributed state management, SSE event streaming, cancellation flags, and rate limiting.

---

## Key Libraries Used

* **`redis.asyncio.from_url`**: Creates an async Redis connection pool.
* **`redis.asyncio.client.PubSub`**: Handles async pub/sub subscriptions for SSE events.

---

## Redis Key Structure

| Key Pattern | Type | Purpose | TTL |
|---|---|---|---|
| `run:{run_id}` | Hash (`HSET`) | Stores current run metadata (`status`, `topic`, `chat_id`, `final_report`). | 24 Hours (86,400s) |
| `sse:{run_id}` | Pub/Sub Channel | Broadcasts execution logs and node completion status to listening web clients. | Real-time Stream |
| `cancellations` | Set (`SADD`) | Contains `run_id`s that have been cancelled by users. | 24 Hours |
| `run:{run_id}:approved` | String (`SET`) | `"1"` if human approved the research plan, else missing/`"0"`. | 1 Hour |
| `rate:{user_id}:{action}` | Sorted Set (`ZSET`) | Timestamps of requests for sliding window rate limiting. | 24 Hours |

---

## Core Functions (`src/core/redis_state.py`)

### 1. Connecting with TLS (`get_redis_client`)
Upstash Redis requires TLS (`rediss://` protocol). The client auto-converts `redis://` schemes to `rediss://`:

```python
def get_redis_client() -> aioredis.Redis:
 redis_url = Config.REDIS_URL
 if redis_url.startswith("redis://") and "upstash.io" in redis_url:
 redis_url = redis_url.replace("redis://", "rediss://", 1)
 return aioredis.from_url(redis_url, decode_responses=True)
```

### 2. Distributed SSE Event Publisher (`publish_run_event`)
Publishes a JSON payload to channel `sse:{run_id}`:
```python
async def publish_run_event(run_id: str, event: Dict[str, Any]) -> None:
 r = get_redis_client()
 await r.publish(f"sse:{run_id}", json.dumps(event))
```

### 3. Distributed SSE Subscriber (`subscribe_run_events`)
Async generator that subscribes to `sse:{run_id}` and yields JSON objects to FastAPI's `StreamingResponse`:
```python
async def subscribe_run_events(run_id: str) -> AsyncGenerator[Dict[str, Any], None]:
 r = get_redis_client()
 pubsub = r.pubsub()
 await pubsub.subscribe(f"sse:{run_id}")
 async for message in pubsub.listen():
 if message and message.get("type") == "message":
 yield json.loads(message["data"])
```

### 4. Shared Cancellation Check (`is_run_cancelled`)
Checked before and during agent node execution:
```python
async def is_run_cancelled(run_id: str) -> bool:
 r = get_redis_client()
 return await r.sismember("cancellations", run_id)
```
