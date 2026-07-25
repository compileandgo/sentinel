# Blueprint for 10,000 Concurrent Users

This document defines the architectural scaling roadmap required to scale Sentinel from a single EC2 server to a high-availability distributed cluster supporting **10,000 active concurrent users**.

---

## Target Distributed Architecture

```
 ┌──────────────────────────┐
 │ AWS Route 53 (DNS) │
 └────────────┬─────────────┘
 │
 ┌────────────▼─────────────┐
 │ AWS ALB (Load Balancer) │
 └────────────┬─────────────┘
 │
 ┌───────────────────────────────┼───────────────────────────────┐
 ▼ ▼ ▼
 ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
 │ EC2 App Server 1 │ │ EC2 App Server 2 │ │ EC2 App Server N │
 │ (FastAPI / Nginx)│ │ (FastAPI / Nginx)│ │ (FastAPI / Nginx)│
 └─────────┬────────┘ └─────────┬────────┘ └─────────┬────────┘
 │ │ │
 └───────────────────────────────┼───────────────────────────────┘
 │
 ┌───────────────────────────────────┼───────────────────────────────────┐
 ▼ ▼ ▼
 ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
 │ Upstash Redis │ │ Celery Worker Pool│ │ Supabase DB │
 │ (Pub/Sub & State) │ │(ECS / EC2 Workers)│ │(Pooled Postgres) │
 └───────────────────┘ └───────────────────┘ └───────────────────┘
```

---

## Key Infrastructure Upgrades

### 1. AWS Application Load Balancer (ALB)
* Distributes incoming HTTP and SSE connections evenly across multiple EC2 application instances.
* Performs SSL termination (`https://`) using AWS Certificate Manager (ACM).

### 2. AWS Auto Scaling Group (ASG)
* Automatically provisions between **3 to 6 x `t3.medium` EC2 instances** based on CPU utilization ($>70\%$) or active connection counts.

### 3. Dedicated Celery Background Worker Pool
* Offloads long-running multi-agent LangGraph loops from the API web processes to a dedicated pool of Celery background workers (`celery -A src.worker worker`).
* Web servers instantly return `run_id` and publish events via Upstash Redis Pub/Sub, preventing web server worker starvation.

### 4. Supabase Database Connection Pooling (pgBouncer)
* Enables Supabase Transaction Pooler on port `6543`.
* Prevents Postgres connection exhaustion when thousands of app instances query database tables simultaneously.

### 5. Multi-Key API Rotation
* Expands `GOOGLE_API_KEYS` and `GROQ_API_KEYS` key pools in `.env` across 5+ API keys to distribute LLM request load and prevent rate limit errors (`429 Too Many Requests`).

---

## Cost Breakdown for 10k Concurrent Architecture

| Component | Quantity / Tier | Monthly Cost |
|---|---|---|
| **AWS ALB (Load Balancer)** | 1 Load Balancer | ~$20 / mo |
| **AWS EC2 App Instances** | 4x `t3.medium` (Auto-scaling) | ~$110 / mo |
| **Celery Worker Nodes** | 2x `t3.medium` | ~$55 / mo |
| **Upstash Redis** | Pay-As-You-Go Plan | ~$30 / mo |
| **Supabase Database** | Pro Tier (Connection Pooling) | $25 / mo |
| **Pinecone Vector DB** | Standard Serverless | ~$15 / mo |
| **Total Cost** | **Handles 10,000 simultaneous users** | **~$255 / month** |
