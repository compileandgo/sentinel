# Architecture Overview

This document describes the high-level architecture of Sentinel, including how components communicate, how requests move through the system, and which third-party libraries power each layer.


## High-Level System Architecture

```
 ┌─────────────────────────────────────────┐ 
 │ Browser / Web Frontend │ 
 │ (HTML5, CSS3, ES6, WebSpeech, Voice) │ 
 └────────────────────┬────────────────────┘ 
 │ HTTP REST / SSE Stream 
 ▼ 
 ┌─────────────────────────────────────────┐ 
 │ Nginx Reverse Proxy │ 
 │ (Port 80 / SSL, unbuffered SSE) │ 
 └────────────────────┬────────────────────┘ 
 │ Proxy Pass (Port 8000) 
 ▼ 
 ┌─────────────────────────────────────────┐ 
 │ FastAPI Web Application │ 
 │ (Async Request Handlers) │ 
 └───────┬─────────────────────────┬───────┘ 
 │ │ 
 ┌───────────────┴──────────┐ ┌──────────┴───────────────┐ 
 ▼ ▼ ▼ ▼ 
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐ 
│ Upstash Redis Cloud │ │ LangGraph Engine │ │ Supabase Postgres │ 
│ - Shared Run Hashes │ │ - Lead Researcher │ │ - User Auth & Chats │ 
│ - SSE Pub/Sub Broker │ │ - Subagents Pool │ │ - Research Chunks │ 
│ - Rate Limit ZSETs │ │ - Cross-Examiner │ │ - Q&A Vector Cache │ 
└──────────────────────┘ └──────────┬───────────┘ └──────────────────────┘ 
 │ 
 ▼ 
 ┌──────────────────────────────┐ 
 │ Hybrid RAG & Search Tools │ 
 │ - Pinecone Vector DB (Cosine)│ 
 │ - Local BM25 Encoder (Sparse)│ 
 │ - Supabase Full-Text Search │ 
 │ - Tavily & GDELT Search │ 
 └──────────────────────────────┘
```


## Libraries Used & Why

| Library | Role in Sentinel | Why Chosen |
| - | - | - |
| **FastAPI** (`fastapi`) | Web Server framework | Async handling for concurrent API calls and native support for `StreamingResponse` (Server-Sent Events). |
| **Uvicorn** (`uvicorn`) | ASGI Web Server | Lightweight, high-performance async server for running FastAPI applications. |
| **LangGraph** (`langgraph`) | Multi-Agent Orchestration | Provides cyclic graph state machines, allowing agents to loop, pause for human approval, and resume deterministically. |
| **LangChain Core** (`langchain-core`) | Abstraction Layer | Provides unified message schemas (`SystemMessage`, `HumanMessage`), prompt templates, and LLM call wrappers. |
| **redis-py** (`redis`) | Redis Client | Async driver (`redis.asyncio`) connecting to Upstash Redis for distributed state, Pub/Sub, and sliding-window rate limiting. |
| **supabase-py** (`supabase`) | Database Client | Python SDK for Supabase Postgres, handling authentication JWT verification, user chat persistence, and vector queries. |
| **pinecone-client** (`pinecone`) | Vector Database | Hosted cloud vector database for storing and querying 768-dimensional dense vector embeddings of ingested intelligence chunks. |
| **pinecone-text** (`pinecone-text`) | BM25 Sparse Encoder | Computes sparse term frequency metrics (`BM25Encoder`) locally for hybrid keyword/vector search. |
| **fastembed** (`fastembed`) | Vector Embeddings | Runs ONNX-quantized BGE bi-encoders (`BAAI/bge-base-en-v1.5`) locally on CPU to compute 768-dim embeddings without external API costs. |



## End-to-End Request Lifecycle

### 1. Research Request Lifecycle

1. User submits a topic via `POST /api/research`.

2. `rate\_limiter.py` checks Redis to ensure the user hasn't exceeded the daily limit (10 runs / 24h).

3. FastAPI creates a new `chat\_id` in Supabase and spawns a background execution thread (`ThreadPoolExecutor`).

4. The background thread initializes `build\_graph()` in LangGraph.

5. The `lead\_researcher` node drafts a breakdown of subagent tasks and publishes a `plan\_ready` event to Redis Pub/Sub (`sse:\{run\_id\}`).

6. The thread pauses (`threading.Event().wait()`) waiting for human approval.

7. User approves via frontend $\\rightarrow$ graph resumes $\\rightarrow$ subagents run in parallel $\\rightarrow$ `cross\_examiner` verifies facts $\\rightarrow$ `synthesizer` builds final report.

8. Logs and events stream continuously to the browser via Nginx $\\rightarrow$ FastAPI $\\rightarrow$ Redis Pub/Sub.

### 2. Q&A Chat Request Lifecycle

1. User asks a question via `POST /api/chat`.

2. `rate\_limiter.py` verifies user limits (30 messages / 24h).

3. `qa\_cache.py` checks Supabase `public.qa\_cache` for a semantically similar previous question ($\\ge 0.90$ similarity using BGE vector embeddings).

 - **Cache HIT**: Returns cached answer immediately (\< 50ms, 0 LLM cost).

 - **Cache MISS**: Runs 3-channel Hybrid Search (Pinecone + BM25 + FTS), retrieves top 25 chunks, fuses with Reciprocal Rank Fusion (RRF), calls LLM (Gemini/Groq), saves result to `qa\_cache`, and returns answer.

