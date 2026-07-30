# Sentinel: Distributed Multi-Agent Geopolitical Intelligence Platform

Sentinel is an enterprise-grade, autonomous multi-agent research pipeline designed to synthesize formal, academic-grade geopolitical and strategic research reports from raw web intelligence and high-dimensional knowledge graphs. Built on top of **LangGraph**, **Upstash Redis**, **Pinecone**, and **Supabase**, Sentinel coordinates parallel-agent execution, hybrid RAG retrieval, cross-model bias auditing, timeline compilation, and real-time SSE stream reporting.

---

## 1. System Architecture

Sentinel uses a stateful Graph orchestrator to manage parallel subagent web collection, hybrid vector/sparse search retrieval, source reliability rating, event timeline alignment, and report compilation.

```mermaid
flowchart TD
    User([User Prompt / Query]) --> Lead[LeadResearcher Orchestrator]
    
    Lead -->|Conditional Fan-out| SubTasks{Subagent Tasks Available?}
    
    SubTasks -- "Yes: Parallel Workers" --> Sub1[Subagent 1]
    SubTasks -- "Yes: Parallel Workers" --> Sub2[Subagent 2]
    SubTasks -- "Yes: Parallel Workers" --> SubN[Subagent N]
    
    subgraph Multi_Source_Retrieval ["Multi-Source & Hybrid RAG Retrieval"]
        Sub1 & Sub2 & SubN --> SmartSearch[Smart Search Engine]
        SmartSearch --> HybridRAG[Hybrid RAG Engine]
        
        HybridRAG --> Pinecone[(Pinecone Vector DB: BGE 768-dim)]
        HybridRAG --> BM25[(Local BM25 TF-IDF Sparse)]
        HybridRAG --> Postgres[(Supabase Postgres GIN FTS)]
        
        Pinecone & BM25 & Postgres --> RRF[Reciprocal Rank Fusion - RRF]
        RRF --> Flashrank[Flashrank Cross-Encoder Reranker]
    end
    
    Flashrank --> Cross[Cross-Model Bias Examiner]
    Flashrank --> Timeline[Timeline Compiler]
    
    subgraph Cross_Model_Audit ["Cross-Model Reliability & Bias"]
        Cross --> Gem[Gemini 1.5/2.0]
        Cross --> Groq[Groq / Llama-3]
        Gem & Groq --> Disagree{Model Contradiction?}
        Disagree -- Yes --> Mark[Flag model_disagreement=True]
    end
    
    GDELT[(GDELT Global Events)] -->|Grounding Chronology| Timeline
    
    SubTasks -- No --> Eval[Sufficiency Evaluator]
    Disagree -- No --> Eval
    Mark --> Eval
    Timeline --> Eval
    
    Eval -->|Status: 'continue'| Lead
    Eval -->|Status: 'synthesize'| Synth[Synthesis Engine]
    
    Synth --> Cit[Citation & Verification Agent]
    Cit --> Stream[SSE Real-time Stream & Report Brief]
    Stream --> End([END])
    
    style User fill:#0070f3,color:#fff,stroke:#0051a8,stroke-width:1px
    style End fill:#10b981,color:#fff,stroke:#059669,stroke-width:1px
```

### Pipeline Components

* **LeadResearcher (Orchestrator):** Analyzes incoming research topics, decomposes goals into atomic sub-claims, plans execution parameters, and dispatches parallel worker tasks.
* **Subagents (Parallel Collectors):** Perform targeted search loops across Tavily/DuckDuckGo, extract structured text snippets, and assemble isolated local memory fact sheets.
* **Hybrid RAG Engine:** Fuses **Pinecone** (BGE-M3 768-dim dense embeddings via ONNX CPU), **Local BM25** (in-process sparse keyword scoring), and **Supabase Postgres GIN FTS** (Full-Text Search) using **Reciprocal Rank Fusion (RRF)**, re-ranked by **Flashrank**.
* **Cross-Examiner:** Evaluates domain reliability against `data/bias_ratings.json`. Compares domain lean classifications across Gemini and Groq models, flagging analytical contradictions.
* **Timeline Compiler:** Synthesizes chronological data, deduplicates concurrent events, and cross-references GDELT event IDs for temporal grounding.
* **Sufficiency Evaluator:** Inspects gathered evidence against target depth. Triggers additional research passes if coverage gaps exist, or routes to final synthesis.
* **Synthesis Engine:** Compiles section drafts with academic structuring (Title, Abstract, Key Findings, Comparative Analysis, and Strategic Implications).
* **Citation Agent:** Verifies assertions against source URLs, enforces standard reference formats, and explicitly flags unverified claims as `[UNCITED]`.

---

## 2. Distributed State & Infrastructure (Upstash Redis)

Sentinel utilizes Upstash Redis to deliver atomic concurrency, real-time logging, and sliding-window rate limiting.

| Redis Primitive | Target Scope | Description |
| :--- | :--- | :--- |
| **`HSET`** | `run:{run_id}` | Stores live state, agent status, collected sources, and intermediate execution artifacts. |
| **`Pub/Sub`** | `sse:{run_id}` | Broadcasts real-time thinking logs and section streams to client Server-Sent Events (SSE) endpoints. |
| **`SADD`** | `cancellations` | Maintains an active set of cancelled `run_id` flags for instant execution teardown across threads. |
| **`ZSET`** | `rate:{user_id}:{action}` | Implements a **true sliding-window rate limiter** using Unix timestamps as scores, executing 4 operations (`ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`, `EXPIRE`) atomically via Redis pipelines. |

---

## 3. Technology Stack

* **Core Runtime:** Python 3.11+ / FastAPI / Uvicorn
* **Orchestration:** LangGraph (StateGraph) with parallel execution nodes
* **Retrieval & RAG:** FastEmbed (BGE-base-en-v1.5 ONNX), Pinecone Vector DB, BM25 (in-process), Supabase Postgres (GIN `tsvector`), Flashrank Reranker
* **LLM & Failover:** Google Gemini 1.5/2.0 with automatic rotation, Groq / Llama-3 failover pool
* **State & Caching:** Upstash Redis (Hashes, Pub/Sub, ZSET Sliding Window)
* **Frontend UI:** Modern Vercel-inspired Slate/Gunmetal dashboard, Chart.js visualizations, `html2pdf.js` export engine, Supabase Google OAuth authentication

---

## 4. Configuration Settings (`.env`)

Sentinel is configured using environment variables. Create a `.env` file in the root directory:

```bash
# LLM Providers & Key Rotation
GOOGLE_API_KEY="AIzaSy..."
GOOGLE_API_KEY_1="AIzaSy..."
GOOGLE_API_KEY_2="AIzaSy..."
GROQ_API_KEY="gsk_..."

# Search & Retrieval
TAVILY_API_KEY="tvly-..."
PINECONE_API_KEY="pcsk_..."
PINECONE_INDEX_NAME="sentinel-index"

# Supabase Auth & Postgres
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_ANON_KEY="eyJhbG..."
SUPABASE_SERVICE_ROLE_KEY="eyJhbG..."

# Upstash Redis State Manager
REDIS_URL="rediss://default:your-password@your-redis.upstash.io:6379"

# Execution Budgets
MAX_RESEARCH_ITERATIONS=2
MAX_SUBAGENTS=3
MAX_SEARCH_CALLS_PER_SUBAGENT=3
```

---

## 5. Setup and Installation

### Prerequisites
* Python 3.11+
* Upstash Redis Instance
* Supabase Account & Database
* Pinecone API Key

### Installation Steps

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/compileandgo/sentinel.git
   cd sentinel
   ```

2. **Set up Virtual Environment:**
   Using `uv` (Recommended):
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip sync
   ```
   Or standard `pip`:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   ```bash
   cp .env.example .env
   # Update .env with your credentials
   ```

4. **Initialize Database Tables:**
   Execute the migration SQL scripts located in `supabase-auth/` in your Supabase SQL Editor to set up user authentication and chat history tables.

---

## 6. Running the Application

Start the Sentinel API and Web Server:

```bash
python src/web/app.py
# or using uvicorn directly
uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser and navigate to:
* **Dashboard:** `http://localhost:8000/app`
* **Landing Page:** `http://localhost:8000/landing`
* **API Documentation:** `http://localhost:8000/docs`

---

## 7. Key Features & PDF Export

* **Interactive Charting:** Section analytical datasets are rendered dynamically with Chart.js.
* **High-Contrast PDF Export:** Uses `html2pdf.js` with live canvas snapshotting and dark-text overrides for clean print-ready reports.
* **Google OAuth Integration:** 1-click authentication powered by Supabase Auth (`google` provider).
* **Stateful Chat Cards:** Report Brief cards remain accessible inside chat streams for instant full-screen viewer toggling.
