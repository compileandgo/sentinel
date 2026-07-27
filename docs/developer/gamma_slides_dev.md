# Sentinel: Distributed Multi-Agent Geopolitical Intelligence Platform

---

## Slide 1 — Title

**Title:** Sentinel
**Subtitle:** Distributed Multi-Agent Research System — Architecture Deep Dive

**Presenter note:** This is a technical walkthrough of a production AI research platform. We will cover the agent graph design, distributed state management, hybrid retrieval pipeline, and the engineering trade-offs at every layer.

---

## Slide 2 — The Engineering Problem

**Title:** Why Not Just Call an LLM?

**Two-column layout:**

**Column 1 — What a naive RAG chain gives you:**
- Single LLM call, no iteration
- No source cross-validation
- Static prompt — cannot adapt based on partial results
- Synchronous blocking — one user request blocks the server thread
- No real-time feedback to the client during execution

**Column 2 — What Sentinel needs:**
- Cyclic, stateful multi-node execution graph
- Parallel retrieval workers with independent search strategies
- Cross-model consensus check before synthesis
- Non-blocking background execution with SSE log streaming
- Distributed state that survives server restarts and scales horizontally

**Code callout:**
```python
# What we replaced
response = llm.invoke(f"Research {topic}")

# What we built instead
for event in graph.stream(state, stream_mode="updates"):
    publish_to_redis(run_id, event)
```

---

## Slide 3 — System Architecture (3 Layers)

**Title:** Three-Layer Architecture

**Layer 1 — Request & Streaming Layer:**
- Nginx (port 80): reverse proxy, `proxy_buffering off`, `proxy_read_timeout 86400s`
- FastAPI + Uvicorn: async request handlers, `ThreadPoolExecutor` for background agent runs
- SSE via `StreamingResponse` — no WebSocket overhead, compatible with standard HTTP

**Layer 2 — Distributed State Layer (Upstash Redis TLS):**
- `run:{run_id}` → HSET hash (status, topic, chat_id, TTL 24h)
- `sse:{run_id}` → Pub/Sub channel (live log forwarding to browser)
- `cancellations` → SADD set (cross-thread cancellation signal)
- `rate:{user_id}:{action}` → ZSET sliding window rate limiter

**Layer 3 — Data & Search Layer:**
- Supabase Postgres: users, chats, messages, research_briefs, research_chunks (GIN FTS index), qa_cache (pgvector)
- Pinecone: 768-dim cosine similarity dense vector index
- Local BM25Encoder (pinecone-text): sparse keyword scoring, runs in-process, 2ms, zero network cost

---

## Slide 4 — The Agent Graph (LangGraph State Machine)

**Title:** LangGraph Cyclic State Machine

**Flow diagram description:**
```
lead_researcher → [Human Gate] → spawn_subagents (parallel fan-out)
     ↑                               ↓
     └── [eval_result.continue] ← subagent (N workers)
                                     ↓
                              cross_examiner ←─── timeline_compiler
                                     ↓
                           sufficiency_evaluator
                            ↓ (sufficient)    ↓ (continue)
                          synthesis       lead_researcher
                              ↓
                         citation_agent
                              ↓
                             END
```

**Key design decisions:**
- `AgentState` is a `TypedDict` — single shared mutable state passed between all nodes
- LangGraph `.stream(state, stream_mode="updates")` yields node-level diffs, not full state — efficient for large state objects
- `Send("subagent", task)` — LangGraph primitive for parallel fan-out to the same node with different inputs
- Human gate implemented as `threading.Event.wait()` — blocks the background thread without blocking the async event loop

---

## Slide 5 — Parallel Execution & Thread Safety

**Title:** Concurrent Subagent Architecture

**The problem:**
- FastAPI runs on asyncio event loop (single thread)
- LangGraph agent graph runs in a background OS thread (`ThreadPoolExecutor`)
- Subagents within the graph run in a nested `ThreadPoolExecutor`
- Redis publishing is an async coroutine — cannot be called directly from a sync thread

**The solution:**
```python
# Bridge from sync background thread → async event loop
asyncio.run_coroutine_threadsafe(
    publish_run_event(run_id, evt),
    loop   # reference to main asyncio loop passed at thread spawn
)
```

**StdoutRedirector pattern:**
```python
class StdoutRedirector:
    def write(self, text):
        for line in text.splitlines():
            if line.strip():
                self.callback(line)   # fires run_coroutine_threadsafe

sys.stdout = StdoutRedirector(callback=on_log_line)
# Now every print() inside any agent node streams to Redis → browser
```

**Why this matters:** Zero changes to agent node code. All `print()` calls inside any node are intercepted automatically.

---

## Slide 6 — 3-Channel Hybrid RAG Search

**Title:** Hybrid Retrieval: Dense + Sparse + FTS

**Retrieval pipeline per subagent query:**

```
Query string
    │
    ├─► BGE Embed (FastEmbed, ONNX, CPU)     → 768-dim float32 vector
    │       ↓
    │   Pinecone Dense Query (top_k=25)       → cosine similarity results
    │
    ├─► BM25Encoder.encode_queries()          → sparse {token_id: score} dict
    │       ↓
    │   Ranked by TF-IDF score (top 25)
    │
    └─► Supabase FTS: tsquery GIN index       → Postgres full-text results
            ↓
        (SELECT WHERE fts_vector @@ websearch_to_tsquery(...))

All three result sets → Reciprocal Rank Fusion (k=60) → Top 10 merged
         ↓
Parent chunk expansion (child chunk ID → fetch parent text from Supabase)
```

**Why parent-child chunking:**
```
Document ingested as:
  Parent chunk (1000 tokens) → stored in Supabase only
       └── Child chunk A (200 tokens) → embedded in Pinecone + BM25
       └── Child chunk B (200 tokens) → embedded in Pinecone + BM25

At retrieval: child chunk scores highest → resolve parent_id → return full 1000-token context
```
Smaller chunks = precise vector matching. Larger parent = enough context for LLM synthesis.

---

## Slide 7 — Reciprocal Rank Fusion

**Title:** Why RRF Instead of Score Normalization?

**The problem with score normalization:**
- Pinecone returns cosine similarity: range [0.0, 1.0]
- BM25 returns TF-IDF scores: range [0, ~50]
- Postgres FTS returns `ts_rank`: range [0.0, 1.0] but different distribution

Normalizing across these three incompatible scales requires domain knowledge of each distribution. Any normalization constant chosen is arbitrary.

**RRF ignores scores entirely — uses only rank position:**

$$\text{RRF}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

```python
def rrf_fuse(results_per_channel: list[list[str]], k=60) -> list[str]:
    scores = {}
    for results in results_per_channel:
        for rank, doc_id in enumerate(results, 1):
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)
```

- `k=60` smoothing prevents rank-1 from dominating: rank 1 scores `1/61 = 0.0164`, rank 2 scores `1/62 = 0.0161`
- Documents appearing in top positions across multiple channels naturally accumulate the highest fused scores
- Zero tuning required when adding a 4th retrieval channel

---

## Slide 8 — Cross-Model Verification (Cross-Examiner Node)

**Title:** Dual-LLM Consensus Engine

**Why two models:**
- Single model bias: Gemini may have different training data cutoffs, RLHF biases, and factual weighting than Llama-3.3
- Running the same raw intel through two models and comparing outputs detects factual contradictions and source lean

**Execution pattern:**
```python
# Parallel LLM calls — both models run simultaneously
with ThreadPoolExecutor(max_workers=2) as executor:
    gemini_future = executor.submit(safe_llm_invoke, msgs, model="gemini")
    groq_future   = executor.submit(safe_llm_invoke, msgs, model="groq")

gemini_result = gemini_future.result()
groq_result   = groq_future.result()

disagreement = (gemini_result.lean != groq_result.lean)
```

**Output per source domain:**
```
pmc.ncbi.nlm.nih.gov  → centrist  [llm-dual-model] (disagreement=False)
erringtowardsanswers.substack.com → right-center [llm-dual-model] (disagreement=True)
```

**Self-healing LLM failover:**
```python
# If Gemini returns 503 or 401, automatically fall through to Groq
def safe_llm_invoke(messages, retries=3):
    for key in gemini_key_pool:
        try:
            return gemini_llm.invoke(messages)
        except (ServiceUnavailable, Unauthenticated):
            continue
    return groq_llm.invoke(messages)   # fallback
```

---

## Slide 9 — Semantic Q&A Cache

**Title:** Vector Semantic Cache — 14.6x Latency Reduction

**Architecture:**
```
Incoming query → BGE embed → 768-dim vector
                                ↓
              cosine_similarity(query_vec, stored_vecs in qa_cache)
                                ↓
                sim >= 0.90 ?
                ├── YES → return cached answer directly   (~1.1s)
                └── NO  → run full pipeline + cache result (~16.5s)
```

**Supabase SQL for cache lookup:**
```sql
SELECT question, answer,
       1 - (embedding <=> query_embedding::vector) AS similarity
FROM qa_cache
ORDER BY similarity DESC
LIMIT 1;
-- If similarity >= 0.90, return cached answer
```

**The cosine similarity math:**
$$\cos(\theta) = \frac{\mathbf{a} \cdot \mathbf{b}}{\|\mathbf{a}\| \|\mathbf{b}\|}$$

Using `<=>` operator (pgvector cosine distance = 1 - similarity)

**Threshold rationale:**
- `0.95+` → too strict, misses paraphrased questions ("What is X?" vs "Explain X")
- `0.85` → too loose, returns cached answers for different questions with similar keywords
- `0.90` → empirically correct balance for domain-specific Q&A on research briefs

---

## Slide 10 — Distributed Rate Limiter

**Title:** Sliding Window Rate Limiter via Redis ZSET

**Implementation:**
```python
async def check_rate_limit(user_id: str, action: str, limit: int, window_s: int) -> bool:
    key = f"rate:{user_id}:{action}"
    now = time.time()
    window_start = now - window_s

    async with redis.pipeline() as pipe:
        pipe.zremrangebyscore(key, 0, window_start)  # evict old timestamps
        pipe.zadd(key, {str(now): now})               # add current request
        pipe.zcard(key)                               # count requests in window
        pipe.expire(key, window_s)                    # auto-cleanup
        results = await pipe.execute()

    count = results[2]
    return count <= limit
```

**Why ZSET over a simple counter:**
- `INCR` counter resets at fixed boundaries (midnight, top of hour)
- A user could send 10 requests at 23:59 and 10 more at 00:00 — 20 requests in 2 minutes
- ZSET stores actual Unix timestamps as scores → true sliding window, no boundary exploits
- All 4 Redis operations execute atomically in a single pipeline roundtrip

**Limits configured:**
- Research runs: 10 per 24h window
- Chat requests: 30 per 24h window

---

## Slide 11 — Real-Time SSE Log Streaming

**Title:** Agent Logs → Redis Pub/Sub → Browser

**The threading boundary problem:**

```
main asyncio event loop          background OS thread
(handles HTTP requests)          (runs LangGraph graph)
         │                                │
         │ ← cannot call async fns →      │
         │                                │
         └──── Redis Pub/Sub ─────────────┘
               (the bridge)
```

**Full flow:**
```
1. Agent node runs: print("[LeadResearcher] Classifying domain...")
2. sys.stdout.write() → StdoutRedirector.write() intercepts
3. asyncio.run_coroutine_threadsafe(redis.publish("sse:run_id", json), loop)
4. FastAPI SSE endpoint subscribed to "sse:run_id" receives message
5. FastAPI yields:  "data: {type: log, message: ...}\n\n"
6. Browser EventSource.onmessage fires → log line appended to UI
```

**Nginx config required for SSE:**
```nginx
location /api/stream/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_buffering    off;          # critical — without this, Nginx buffers SSE frames
    proxy_read_timeout 86400s;       # 24h — keeps long research runs connected
    proxy_cache        off;
}
```

---

## Slide 12 — Voice Engine

**Title:** STT + TTS Pipeline

**Speech-to-Text:**
```javascript
// MediaRecorder captures microphone at 16kHz
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

// VAD: 7-second silence detection before auto-submit
let silenceTimer = null;
analyser.addEventListener("volumechange", (e) => {
    if (e.volume < SILENCE_THRESHOLD) {
        silenceTimer = setTimeout(() => recorder.stop(), 7000);
    } else {
        clearTimeout(silenceTimer);
    }
});

// POST WebM payload to backend
recorder.ondataavailable = (e) => chunks.push(e.data);
recorder.onstop = async () => {
    const blob = new Blob(chunks, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "recording.webm");
    await fetch("/api/voice/stt", { method: "POST", body: formData });
};
```

**Backend Whisper transcription with vocabulary prompt:**
```python
transcription = groq_client.audio.transcriptions.create(
    file=("audio.webm", audio_bytes, "audio/webm"),
    model="whisper-large-v3",
    prompt="RAG, Pinecone, GDELT, BM25, Supabase, LangGraph, geopolitical",
    # Domain vocabulary prompt dramatically reduces transcription errors
    # for technical terms that Whisper otherwise mishears
)
```

---

## Slide 13 — AWS EC2 Deployment

**Title:** Production Deployment Configuration

**systemd unit (`/etc/systemd/system/sentinel.service`):**
```ini
[Unit]
Description=Sentinel Geopolitical Intelligence Platform
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/sentinel
ExecStart=/home/ubuntu/.local/bin/uv run uvicorn src.web.app:app \
          --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**2GB swap file — why it is critical:**
- FastEmbed loads `BAAI/bge-base-en-v1.5` ONNX model into RAM on first query: ~400MB
- Uvicorn workers + Redis client + Supabase client: ~300MB
- t3.micro has 908MB RAM. Without swap, the OS kills the process (OOM) on first embedding call
- Swap file persisted in `/etc/fstab` → survives reboots

**Key numbers:**
- RAM: 908MB physical + 2GB swap
- Disk: 6.7GB total, ~4.6GB free after deployment
- Nginx: port 80 → 127.0.0.1:8000

---

## Slide 14 — Scaling Architecture (10k Users)

**Title:** Scaling Roadmap — From t3.micro to 10k Concurrent Users

**Current bottlenecks at scale:**
1. Single Uvicorn process: `ThreadPoolExecutor` limited to CPU cores × 2
2. Every research run spawns threads in the web server process → memory pressure
3. Single EC2 instance: no horizontal scaling

**Production architecture:**
```
Internet → AWS ALB (SSL termination, health checks)
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
  EC2-1     EC2-2     EC2-3     ← Auto Scaling Group (t3.medium)
  Uvicorn   Uvicorn   Uvicorn   ← stateless — state is in Redis
    │         │         │
    └────┬────┘         │
         ▼              ▼
   Upstash Redis    Celery Workers (ECS Fargate)
   (shared state)  (research runs offloaded here)
         │
         ▼
   Supabase Postgres (pgBouncer transaction pooler, port 6543)
   Pinecone (no change — already cloud-managed)
```

**Key change — Celery:**
- Research runs move from `ThreadPoolExecutor` in web server to Celery workers
- Web server only handles HTTP — never blocks on long-running tasks
- Celery workers scale independently from web servers
- Redis becomes both the rate-limiter AND the Celery broker

**Projected cost at production scale:**
| Component | Monthly Cost |
|---|---|
| 4x EC2 t3.medium | ~$120 |
| AWS ALB | ~$20 |
| Celery on ECS (4 workers) | ~$80 |
| Supabase Pro | ~$25 |
| Upstash Redis | ~$10 |
| **Total** | **~$255/month** |

---

## Slide 15 — Why Not AWS Lambda / Bedrock / S3?

**Title:** AWS Service Selection Rationale

| Service | Why Not Used |
|---|---|
| **Lambda** | 15-min hard timeout. A single research run with 4 subagents, cross-examiner, synthesis, and citation alignment runs 2–4 minutes and requires persistent shared memory across nodes. Lambda resets state between invocations. |
| **Bedrock** | We need Gemini 2.0 Flash (Google) and Groq LPU (500+ tok/s Llama-3.3). Bedrock hosts neither. It would add a layer of indirection with no performance benefit over direct API integration. |
| **S3** | Research reports are stored in Supabase `research_briefs` table (Postgres JSONB). Adding S3 as a third storage location for the same data increases operational complexity without solving a problem. At scale, S3 + CloudFront makes sense for CDN delivery of large report exports. |
| **RDS** | Supabase is managed Postgres with built-in pgvector, auth, and Row Level Security. Standing up RDS separately would require managing auth, connection pooling, and backups independently. |
| **ElastiCache** | Upstash Redis is serverless and requires zero infrastructure management. ElastiCache requires VPC configuration, subnet groups, and a dedicated instance running 24/7 even when idle. |

**The principle:**
> Use managed cloud services where they eliminate operational overhead, not where they add it.

---

## Slide 16 — Tech Stack Summary

**Title:** Full Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Web Framework | FastAPI + Uvicorn | Async HTTP, SSE streaming |
| Agent Orchestration | LangGraph | Cyclic stateful multi-node execution graph |
| Primary LLM | Google Gemini 2.0 Flash | Planning, synthesis, citation alignment |
| Fallback / Verification LLM | Groq + Llama-3.3-70B | Cross-examiner, STT (Whisper-large-v3) |
| Live Web Search | Tavily AI Search | Clean snippet extraction for subagents |
| News Intelligence | GDELT Project API | Real-time geopolitical event monitoring |
| Distributed State | Upstash Redis (TLS) | Run state, SSE Pub/Sub, rate limiter, cancellation |
| Relational DB + Auth | Supabase (Postgres) | Users, chats, messages, reports, FTS, vector cache |
| Dense Vector Index | Pinecone | 768-dim cosine similarity search |
| Local Embedding Model | FastEmbed BGE (ONNX) | CPU inference, zero API cost |
| Sparse Keyword Search | BM25Encoder (pinecone-text) | In-process, 2ms, TF-IDF scoring |
| Deployment | AWS EC2 + Nginx + systemd | Ubuntu 26.04, port 80, auto-restart |
| Package Management | uv (Astral) | Fast Python dependency resolution |
