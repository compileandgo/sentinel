# Developer Guide & Local Setup

This document provides step-by-step instructions for installing, configuring, fitting encoders, and running Sentinel locally.

---

## Prerequisites

* **Python**: 3.11 or higher (Python 3.14 tested).
* **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`.
* **Git**: Installed locally.
* **Services Required**:
 - Upstash Redis database (`REDIS_URL`).
 - Supabase Project (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`).
 - Pinecone Index (`PINECONE_API_KEY`, `PINECONE_INDEX_NAME`).

---

## Step 1: Clone Repository & Install Dependencies

```bash
git clone https://github.com/compileandgo/sentinel.git
cd sentinel

# Install all dependencies using uv
uv sync
```

---

## Step 2: Environment Configuration (`.env`)

Create a `.env` file in the project root with the following keys:

```env
# Server Port
PORT=8000

# Redis Connection (Upstash rediss://)
REDIS_URL=rediss://default:your_password@your-db.upstash.io:6379

# Supabase Credentials
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_JWT_SECRET=your_jwt_secret

# Pinecone Vector DB
PINECONE_API_KEY=your_pinecone_key
PINECONE_INDEX_NAME=sentinel-index

# LLM API Keys (Pools supported via _1, _2...)
GOOGLE_API_KEY=your_primary_gemini_key
GOOGLE_API_KEY_1=your_secondary_gemini_key
GROQ_API_KEY=your_groq_key

# Search Tools
TAVILY_API_KEY=your_tavily_key
```

---

## Step 3: Fitting the Local BM25 Encoder

Before running hybrid RAG search, fit the local BM25 encoder against existing Supabase chunks:

```bash
uv run python scripts/fit_bm25.py
```

This generates `.bm25_cache/bm25_encoder.json` used by `rag_search.py`.

---

## Step 4: Running the Local Server

Start the FastAPI application on `http://127.0.0.1:8000`:

```bash
uv run uvicorn src.web.app:app --host 127.0.0.1 --port 8000 --reload
```

---

## Step 5: Running Tests

### 1. Test Python Syntax Across All Files
```bash
uv run python -m py_compile src/web/app.py src/core/redis_state.py src/tools/qa_cache.py
```

### 2. Test Redis State & Pub/Sub
```bash
uv run python -c "
import asyncio
from src.core.redis_state import set_run_state, get_run_state
asyncio.run(set_run_state('test', {'status': 'ok'}))
print(asyncio.run(get_run_state('test')))
"
```

### 3. Test Vector Semantic Cache
```bash
uv run python -c "
import asyncio
from src.tools.qa_cache import check_semantic_cache
print(asyncio.run(check_semantic_cache('test_chat', 'What is Sentinel?')))
"
```
