# LangGraph Multi-Agent Architecture

Sentinel uses **LangGraph** (`langgraph`) to manage multi-agent research workflows. Unlike linear chain pipelines, LangGraph implements cyclic, state-driven graphs capable of conditional routing, parallel execution, and human-in-the-loop pausing.

---

## Key Libraries Used

* **`langgraph.graph.StateGraph`**: Constructs the state transition graph.
* **`langgraph.graph.END`**: Special terminal node signifying workflow completion.
* **`typing.TypedDict`**: Defines the strict schema of the shared state passed between nodes.

---

## Agent Graph Structure

```
 ┌───────────────────────────┐
 │ START NODE │
 └─────────────┬─────────────┘
 │
 ▼
 ┌───────────────────────────┐
 │ lead_researcher │
 │ (Formulates Research Plan)│
 └─────────────┬─────────────┘
 │
 ┌─────────────▼─────────────┐
 │ PAUSE FOR APPROVAL │
 │ (Human-in-the-Loop) │
 └─────────────┬─────────────┘
 │ (User clicks 'Proceed')
 ▼
 ┌───────────────────────────┐
 │ spawn_subagents │
 │ (Parallel Retrieval) │
 └─────────────┬─────────────┘
 │
 ▼
 ┌───────────────────────────┐
 │ cross_examiner │
 │ (Bias & Fact Verification)│
 └─────────────┬─────────────┘
 │
 ▼
 ┌───────────────────────────┐
 │ timeline_compiler │
 │ (Chronological Alignment) │
 └─────────────┬─────────────┘
 │
 ┌─────────────▼─────────────┐
 │ eval_report │
 │(Quality & Citation Check) │
 └─────────────┬─────────────┘
 │
 ┌─────────────────┴─────────────────┐
 │ Should Loop / Re-search? │
 ├─────────────────┬─────────────────┤
 │ Yes (Needs info)│ No (Sufficient) │
 ▼ ▼ │
 ┌───────────────────┐ ┌────────────────────┐ │
 │ lead_researcher │ │ synthesizer │ │
 └───────────────────┘ └─────────┬──────────┘ │
 │ │
 ▼ ▼
 ┌───────────────────┐
 │ END NODE │
 └───────────────────┘
```

---

## State Schema (`ResearchState`)

Defined in `src/agent/state.py`, `ResearchState` is a `TypedDict` passed between all graph nodes:

```python
class ResearchState(TypedDict):
 topic: str # Research query
 run_id: str # Unique execution ID
 plan_path: str # Path to generated research plan file
 start_time: float # Execution start timestamp
 research_backlog: List[str] # Unresolved sub-questions
 subagent_tasks: List[Dict] # Task specifications for parallel workers
 raw_intel: List[Dict] # Collected intelligence fragments (RAG + Tavily)
 bias_matrix: List[Dict] # Fact-check & bias analysis results
 chronology: List[Dict] # Key chronological events
 iterations: int # Current research loop count
 eval_result: Optional[Dict] # Evaluation score (completeness, uncited ratio)
 synthesis: str # Intermediate draft
 final_report: str # Complete Markdown report output
```

---

## Node Roles & Implementation

### 1. Lead Researcher (`src/agent/nodes/lead_researcher.py`)
* **Role**: Supervisor / Orchestrator.
* **Function**: Analyzes topic complexity, determines topic domain (`GEOPOLITICAL`, `ECONOMIC`, `SCIENTIFIC`), and breaks down the topic into subagent tasks.
* **Human-in-the-Loop**: On iteration 1, generates `research_plan.md` and triggers a pause event waiting for user confirmation before executing external web calls.

### 2. Subagents Execution (`src/agent/nodes/subagents.py`)
* **Role**: Information Retrieval.
* **Function**: Executes subtasks concurrently using Python `concurrent.futures`. Each subagent invokes 3 retrieval sources:
 1. Internal Vector/Keyword Hybrid RAG (`rag_search.py`).
 2. Live Web Search (`Tavily`).
 3. Real-time News API (`GDELT Project`).

### 3. Cross-Examiner (`src/agent/nodes/cross_examiner.py`)
* **Role**: Verification & Bias Mitigation.
* **Function**: Evaluates raw intel gathered by subagents for contradictions, media bias, and unverified claims.

### 4. Timeline Compiler (`src/agent/nodes/timeline_compiler.py`)
* **Role**: Chronology Engine.
* **Function**: Extracts temporal indicators (dates, years, milestones) and orders them chronologically to build a structured event timeline.

### 5. Synthesizer (`src/agent/nodes/synthesizer.py`)
* **Role**: Final Report Writer.
* **Function**: Compiles all verified intel, chronology, and bias evaluations into an executive report with inline markdown citations (`[Source: title]`).
