# Sentinel - Autonomous Geopolitical Intelligence Agent

Sentinel is a multi-agent, bias-aware research and analysis system designed for political and geopolitical intelligence collation. Built on LangGraph, it implements an orchestrator-parallel-subagent pattern to plan, coordinate, execute, and synthesize deep-dive research runs.

The backend is written in FastAPI, integrated with Supabase for data persistence and authentication. The frontend is a dark-mode chat interface, featuring hardware-accelerated transitions and responsive layout toggles optimized for mobile and desktop screens.

---

## 1. System Architecture

Sentinel uses a decoupled orchestrator-parallel-subagent architecture to handle complex geopolitical topics.

```
                    ┌───────────────────────────────────┐
                    │        User Research Topic        │
                    └─────────────────┬─────────────────┘
                                      │
                                      ▼
                    ┌───────────────────────────────────┐
           ┌───────▶│       LeadResearcher Node         │◀──────────────────┐
           │        │  - Validates query & scope        │                   │
           │        │  - Generates parallel task specs  │                   │
           │        │  - Persists plan to disk          │                   │
           │        └──────┬──────┬──────┬──────────────┘                   │
           │               │      │      │ (Parallel fan-out)               │
           │               ▼      ▼      ▼                                  │
           │   ┌───────────┐ ┌───────────┐ ┌───────────┐                    │
           │   │ Subagent 1│ │ Subagent 2│ │ Subagent N│                    │
           │   │ - Search  │ │ - Search  │ │ - Search  │                    │
           │   │ - Eval    │ │ - Eval    │ │ - Eval    │                    │
           │   │ - Disk Art│ │ - Disk Art│ │ - Disk Art│                    │
           │   └─────┬─────┘ └─────┬─────┘ └─────┬─────┘                    │
           │         │             │             │                          │
           │         └─────────────┼─────────────┘                          │
           │                       │ (Lightweight file paths)               │
           │                       ▼                                        │
           │        ┌──────────────────────────────┐                        │
           │        │       Cross-Examiner         │                        │
           │        │  - Checks static bias rules  │                        │
           │        │  - Generates bias_matrix     │                        │
           │        └──────────────┬───────────────┘                        │
           │                       │                                        │
           │                       ▼                                        │
           │        ┌──────────────────────────────┐                        │
           │        │      Timeline Compiler       │                        │
           │        │  - Extracts event records    │                        │
           │        │  - Highlights chronological  │                        │
           │        │    conflict flags            │                        │
           │        └──────────────┬───────────────┘                        │
           │                       │                                        │
           │                       ▼                                        │
           │        ┌──────────────────────────────┐                        │
           │        │    Sufficiency Evaluator     │──── (Needs Refinement) ┘
           │        └──────────────┬───────────────┘
           │                       │ (Target Confidence Met)
           │                       ▼
           │        ┌──────────────────────────────┐
           │        │       Synthesis Engine       │
           │        │  - Weights source credibility│
           │        │  - Compiles balanced prose   │
           │        └──────────────┬───────────────┘
           │                       │
           │                       ▼
           │        ┌──────────────────────────────┐
           └────────│        Citation Agent        │
                    │  - Matches claims to URLs    │
                    │  - Injects attribution       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  Structured Markdown Brief   │
                    └──────────────────────────────┘
```

### Component Nodes

* **LeadResearcher (Orchestrator):** Manages the execution flow. Generates specific task sub-queries and limits execution to target scope budgets.
* **Subagents (Parallel Workers):** Executed in parallel using LangGraph's dynamic `Send` mapping. Each subagent runs an iterative search-evaluate-refine loop, writes findings to `output/subagents/{run_id}/`, and returns local file references.
* **Cross-Examiner:** Maps source domains against static credibility metadata (`data/bias_ratings.json`) and runs LLM-based bias classification, compiling a structured `bias_matrix`.
* **Timeline Compiler:** Extracts structured dates and deduplicates chronologies. Resolves historical and event sequence mismatches.
* **Sufficiency Evaluator:** Inspects gathered intelligence against a predefined evaluation rubric. Determines whether to loop back for further research or trigger final synthesis.
* **Synthesis Engine:** Aggregates findings and compiles the intelligence brief, neutral-prose assessments, and position summaries.
* **Citation Agent:** Injects inline anchors and sources, mapping sentences to original retrieval URLs, and tags uncorroborated assertions.

---

## 2. Configuration Settings (.env)

Sentinel is configured using environment variables. An example layout is located in `.env.example`.

### Core API Settings
* `GOOGLE_API_KEY`: Primary Google Gemini API credential.
* `GOOGLE_API_KEY_1`, `GOOGLE_API_KEY_2`, etc.: Fallback API credentials rotated automatically on rate-limit exhaustion.
* `TAVILY_API_KEY`: Primary Tavily search provider credential.

### Model Parameters
* `LLM_MODEL`: Active LLM for orchestration and synthesis (default: `gemini-2.5-flash`).
* `LLM_TEMPERATURE`: LLM generation temperature (default: `0.1`).
* `SUBAGENT_MODEL`: LLM utilized for parallel subagent executions (default: `gemini-2.5-flash`).

### Research Constraints
* `MAX_RESEARCH_ITERATIONS`: The maximum number of orchestrator loops (default: `1`).
* `MAX_SUBAGENTS`: Maximum parallel subagent instances per iteration (default: `2`).
* `MAX_SEARCH_CALLS_PER_SUBAGENT`: Maximum search requests per subagent instance (default: `3`).
* `SEARCH_PROVIDER`: Primary search runtime (`tavily` or `duckduckgo`).

### Database & Authentication
* `SUPABASE_URL`: Endpoint url of the Supabase project instance.
* `SUPABASE_ANON_KEY`: Client authorization key for client-side queries.
* `SUPABASE_SERVICE_ROLE_KEY`: Service account token for database reads and writes.
* `SUPABASE_JWT_SECRET`: Signature key verification secret for authentication tokens.

### Port
* `PORT`: Server port binding (default: `8000`).

---

## 3. Technology Stack

* **Orchestration:** LangGraph (StateGraph) with concurrent `Send` dispatch.
* **LLM Engine:** Gemini 2.5 Flash (via Google AI Studio).
* **Search Engine:** Tavily API (Primary) with automated fallback to `duckduckgo-search`.
* **API Framework:** FastAPI (ASGI Python Server).
* **Database & Auth:** Supabase (PostgreSQL tables, message logging, and JWT authentication).
* **Frontend:** Vanilla HTML, CSS, JavaScript (Mobile-responsive UI with sidebar drawer toggles and dynamic transitions).

---

## 4. Setup and Installation

### Prerequisites
* Python 3.11+
* Active Supabase project instance

### Setup
1. Clone the repository:
   ```bash
   git clone <repository_url> sentinel
   cd sentinel
   ```
2. Initialize virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Establish configuration:
   ```bash
   cp .env.example .env
   # Populate credentials inside .env
   ```
4. Run database migrations on your Supabase instance using the SQL structures provided in `supabase-auth/`.

---

## 5. Execution

### Local Development Server
Execute the server using:
```bash
python src/web/app.py
```
Open `http://127.0.0.1:8000` in a web browser.

---

## 6. Future Scale-Up Planning

For a high-concurrency production roadmap detailing transitions to Redis, Celery task runners, sliding-window rate limiters, pgvector semantic caching, and uvicorn clustering, refer to [scaling_plan.md](scaling_plan.md).
