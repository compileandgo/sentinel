from typing import Dict, List, Optional, TypedDict, Annotated
import operator

class RawIntel(TypedDict):
    """One retrieved source record. Produced by search, consumed by CrossExaminer."""
    source_url: str
    title: str
    snippet: str
    published_date: str   # ISO date string or "" if unknown
    query: str   # the search query that produced this result
    subagent_id: str   # "lead" in MVP; subagent ID in parallel arch

class BiasEntry(TypedDict):
    """One source bias classification. Produced by CrossExaminer."""
    domain: str
    lean: str   # e.g. "centrist", "state-pro-X", "centre-left"
    reliability: str   # "high" | "medium" | "low"
    method: str   # "static-table" | "llm" | "llm-dual-model"
    model_disagreement: bool  # True if Gemini and Groq disagreed
    notes: str

class ChronEntry(TypedDict):
    """One dated event. Produced by TimelineCompiler."""
    date: str   # ISO date or approximate e.g. "2025-Q3"
    event: str   # one-sentence description
    source_url: str
    confidence: str   # "high" | "medium" | "low"
    conflict_flag: bool  # True if another source gives a different date

class EvalResult(TypedDict):
    """Structured output from SufficiencyEvaluator."""
    status: str    # "continue" | "synthesize"
    confidence: float  # 0.0–1.0 how well-covered the topic is
    unresolved_questions: List[str]
    reasoning: str

class SubagentTask(TypedDict):
    """Task assigned to a single subagent."""
    subagent_id: str
    topic: str
    task: str
    output_path: str

class AgentState(TypedDict):
    # Core
    topic: str
    run_id: str
    plan_path: str             # path to plan.md written at start of run

    # Research tracking
    research_backlog: List[str]              # open questions still needing evidence
    subagent_artifacts: Annotated[List[str], operator.add]  # paths to written markdown artifacts
    subagent_tasks: List[SubagentTask]       # specs delegated to parallel workers

    # Accumulated typed records
    raw_intel: Annotated[List[RawIntel], operator.add]
    bias_matrix: Annotated[List[BiasEntry], operator.add]
    chronology: Annotated[List[ChronEntry], operator.add]

    # Loop control
    iterations: int
    eval_result: Optional[EvalResult]

    # Output
    synthesis: str
    final_report: str
