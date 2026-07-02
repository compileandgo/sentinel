"""
intel_agent.py — Sentinel Foundation Script
============================================

PURPOSE FOR CODING AGENT
--------------------------
This is the starting point. It is a working LINEAR MVP of the target
architecture described in README.md. It runs end-to-end and produces a
real brief. The coding agent should treat every # TODO[AGENT] comment as
a concrete upgrade task and evolve this toward the full architecture.

CURRENT STATE (this file)
--------------------------
  LeadResearcher → CrossExaminer → TimelineCompiler
       ↑                                   |
       └─────── SufficiencyEvaluator ←─────┘
                        |
                   SynthesisEngine
                        |
                  CitationAgent (stub)
                        |
                  Markdown Output

All nodes are SEQUENTIAL. Subagents are NOT yet parallel (single search
per iteration). See TODO[AGENT]: PARALLEL-SUBAGENTS below for the upgrade path.

TARGET STATE (README.md)
--------------------------
LeadResearcher spawns N parallel Subagents via LangGraph Send() API.
Each subagent writes a markdown artifact to output/subagents/<run_id>/.
LeadResearcher reads lightweight file references, not full content blobs.
See README.md → Architecture and Target vs. Current MVP table.

COST CONTROLS
--------------------------
All token-heavy operations are bounded. For a free-tier run:
  MAX_RESEARCH_ITERATIONS = 2   (hard cap, SufficiencyEvaluator exits first)
  MAX_SEARCH_CALLS        = 2   (per node per iteration)
  LLM calls per iteration ≈ 4   (director + examiner + timeline + evaluator)

Keep these low during development. Raise them only after the parallel
subagent architecture is in place and you have confirmed quota headroom.

UPGRADE ORDER (matches README.md "Target vs. Current MVP" table)
--------------------------
1. Typed schemas                 ← DONE HERE (RawIntel, BiasEntry, ChronEntry)
2. Parallel subagents + Send()   ← TODO[AGENT]: PARALLEL-SUBAGENTS
3. Filesystem artifact pattern   ← TODO[AGENT]: ARTIFACTS
4. Sufficiency Evaluator (JSON)  ← DONE HERE (structured output, not iter count)
5. Citation Agent (real)         ← TODO[AGENT]: CITATION-AGENT
6. SearchProvider abstraction    ← DONE HERE (Tavily + DDG fallback)
7. Eval harness                  ← TODO[AGENT]: EVAL-HARNESS
"""

# ──────────────────────────────────────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────────────────────────────────────

import os
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Optional, TypedDict, Annotated
import operator

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG  — all tunables in one place, loaded from .env
# ──────────────────────────────────────────────────────────────────────────────

class Config:
    # LLM
    LLM_MODEL        = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    SUBAGENT_MODEL   = os.getenv("SUBAGENT_MODEL", "gemini-2.5-flash")
    LLM_TEMPERATURE  = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    # Search
    SEARCH_PROVIDER  = os.getenv("SEARCH_PROVIDER", "tavily")  # "tavily" | "duckduckgo"
    TAVILY_API_KEY   = os.getenv("TAVILY_API_KEY", "")

    # Cost controls — keep LOW during development
    MAX_RESEARCH_ITERATIONS       = int(os.getenv("MAX_RESEARCH_ITERATIONS", "2"))
    MAX_SEARCH_CALLS_PER_SUBAGENT = int(os.getenv("MAX_SEARCH_CALLS_PER_SUBAGENT", "2"))
    # TODO[AGENT]: PARALLEL-SUBAGENTS — add MAX_SUBAGENTS here when Send() is wired
    MAX_SUBAGENTS    = int(os.getenv("MAX_SUBAGENTS", "3"))  # used in target arch

    # Output
    OUTPUT_DIR       = Path(os.getenv("OUTPUT_DIR", "./output"))
    SUBAGENT_DIR     = OUTPUT_DIR / "subagents"

    # Optional feature flags — all False by default, safe to ignore during MVP
    ENABLE_GDELT               = os.getenv("ENABLE_GDELT", "false").lower() == "true"
    ENABLE_RSS_FEEDS           = os.getenv("ENABLE_RSS_FEEDS", "false").lower() == "true"
    ENABLE_LOCAL_CACHE         = os.getenv("ENABLE_LOCAL_CACHE", "false").lower() == "true"
    ENABLE_CROSS_MODEL_BIAS    = os.getenv("ENABLE_CROSS_MODEL_BIAS_CHECK", "false").lower() == "true"

    # Optional keys — if blank, the feature disables itself gracefully
    GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")

# Create output dirs on startup
Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.SUBAGENT_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# TYPED SCHEMAS
# Purpose: every node writes typed dicts, never free-text blobs.
# The coding agent MUST preserve these schemas when adding new nodes.
# ──────────────────────────────────────────────────────────────────────────────

class RawIntel(TypedDict):
    """One retrieved source record. Produced by search, consumed by CrossExaminer."""
    source_url:     str
    title:          str
    snippet:        str
    published_date: str   # ISO date string or "" if unknown
    query:          str   # the search query that produced this result
    subagent_id:    str   # "lead" in MVP; subagent ID in parallel arch

class BiasEntry(TypedDict):
    """One source bias classification. Produced by CrossExaminer."""
    domain:             str
    lean:               str   # e.g. "centrist", "state-pro-X", "centre-left"
    reliability:        str   # "high" | "medium" | "low"
    method:             str   # "static-table" | "llm" | "llm-dual-model"
    model_disagreement: bool  # True if Gemini and Groq disagreed (optional feature)
    notes:              str

class ChronEntry(TypedDict):
    """One dated event. Produced by TimelineCompiler."""
    date:          str   # ISO date or approximate e.g. "2025-Q3"
    event:         str   # one-sentence description
    source_url:    str
    confidence:    str   # "high" | "medium" | "low"
    conflict_flag: bool  # True if another source gives a different date

class EvalResult(TypedDict):
    """Structured output from SufficiencyEvaluator. NOT a free-text decision."""
    status:               str    # "continue" | "synthesize"
    confidence:           float  # 0.0–1.0 how well-covered the topic is
    unresolved_questions: List[str]
    reasoning:            str

# ──────────────────────────────────────────────────────────────────────────────
# AGENT STATE
# All nodes read from and write to this single object.
# Use Annotated[List, operator.add] for fields that accumulate across iterations.
# ──────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Core
    topic:        str
    run_id:       str
    plan_path:    str             # path to plan.md written at start of run

    # Research tracking
    research_backlog:    List[str]              # open questions still needing evidence
    subagent_artifacts:  List[str]              # file paths (target arch); empty in MVP

    # Accumulated typed records
    raw_intel:   Annotated[List[RawIntel],   operator.add]
    bias_matrix: Annotated[List[BiasEntry],  operator.add]
    chronology:  Annotated[List[ChronEntry], operator.add]

    # Loop control
    iterations:  int
    eval_result: Optional[EvalResult]

    # Output
    synthesis:    str
    final_report: str

# ──────────────────────────────────────────────────────────────────────────────
# SEARCH PROVIDER ABSTRACTION
# Tavily is primary. DuckDuckGo is the automatic fallback.
# TODO[AGENT]: implement full SearchProvider Protocol when adding new providers.
# All nodes call search() — never import a specific provider directly in nodes.
# ──────────────────────────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 3) -> List[RawIntel]:
    """Call Tavily Search API. Returns typed RawIntel records."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=Config.TAVILY_API_KEY)
        resp = client.search(
            query=query,
            search_depth="basic",  # "basic" uses fewer credits than "advanced"
            max_results=max_results,
            include_published_date=True,
        )
        results = []
        for r in resp.get("results", []):
            results.append(RawIntel(
                source_url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                published_date=r.get("published_date", ""),
                query=query,
                subagent_id="lead",
            ))
        return results
    except Exception as e:
        print(f"  [Tavily] failed: {e} — falling back to DuckDuckGo")
        return _duckduckgo_search(query, max_results)


def _duckduckgo_search(query: str, max_results: int = 3) -> List[RawIntel]:
    """DuckDuckGo fallback. No API key required."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(RawIntel(
                    source_url=r.get("href", ""),
                    title=r.get("title", ""),
                    snippet=r.get("body", ""),
                    published_date="",
                    query=query,
                    subagent_id="lead",
                ))
        return results
    except Exception as e:
        print(f"  [DuckDuckGo] also failed: {e}")
        return []


def search(query: str, max_results: int = 3) -> List[RawIntel]:
    """
    Primary search interface. All nodes call this — never a provider directly.
    Provider selection: SEARCH_PROVIDER env var. Auto-falls back on error.
    """
    if Config.SEARCH_PROVIDER == "tavily" and Config.TAVILY_API_KEY:
        return _tavily_search(query, max_results)
    return _duckduckgo_search(query, max_results)


# ──────────────────────────────────────────────────────────────────────────────
# BIAS RATINGS TABLE
# Loaded from data/bias_ratings.json if it exists.
# CrossExaminer checks this first — only calls LLM for unknown domains.
# The coding agent should expand data/bias_ratings.json, not this function.
# ──────────────────────────────────────────────────────────────────────────────

_BIAS_TABLE: Dict[str, dict] = {}

def _load_bias_table():
    global _BIAS_TABLE
    table_path = Path("data/bias_ratings.json")
    if table_path.exists():
        with open(table_path) as f:
            _BIAS_TABLE = json.load(f)
        print(f"[Config] Loaded {len(_BIAS_TABLE)} entries from bias_ratings.json")
    else:
        print("[Config] data/bias_ratings.json not found — LLM will classify all domains")

_load_bias_table()


def classify_domain(domain: str, llm: ChatGoogleGenerativeAI) -> dict:
    """
    Returns bias classification for a domain.
    Checks static table first. Falls back to LLM only for unknown domains.
    """
    # Strip www.
    key = domain.replace("www.", "")
    if key in _BIAS_TABLE:
        entry = _BIAS_TABLE[key]
        return {"lean": entry.get("lean", "unknown"),
                "reliability": entry.get("reliability", "unknown"),
                "method": "static-table"}

    # LLM fallback for unknown domains
    # TODO[AGENT]: DUAL-MODEL — when ENABLE_CROSS_MODEL_BIAS is True,
    # run this prompt through Groq too and compare results.
    prompt = (f"Classify the media bias of '{domain}'. "
              f"Reply ONLY with JSON: "
              f'{{ "lean": "...", "reliability": "high|medium|low", "notes": "..." }}')
    try:
        res = llm.invoke([HumanMessage(content=prompt)])
        raw = res.content.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(raw)
        return {"lean": parsed.get("lean", "unknown"),
                "reliability": parsed.get("reliability", "unknown"),
                "method": "llm",
                "notes": parsed.get("notes", "")}
    except Exception:
        return {"lean": "unknown", "reliability": "unknown",
                "method": "llm-failed", "notes": ""}


# ──────────────────────────────────────────────────────────────────────────────
# LLM INITIALISATION
# ──────────────────────────────────────────────────────────────────────────────

def make_llm(model: Optional[str] = None) -> ChatGoogleGenerativeAI:
    """
    Returns a ChatGoogleGenerativeAI instance.
    TODO[AGENT]: PARALLEL-SUBAGENTS — subagent nodes should call
    make_llm(Config.SUBAGENT_MODEL) so lead and subagents can be split later.
    """
    return ChatGoogleGenerativeAI(
        model=model or Config.LLM_MODEL,
        temperature=Config.LLM_TEMPERATURE,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )

# ──────────────────────────────────────────────────────────────────────────────
# HELPER: write plan to disk
# ──────────────────────────────────────────────────────────────────────────────

def write_plan(run_id: str, topic: str, backlog: List[str]) -> str:
    """
    Persists the LeadResearcher's plan to disk.
    Used for context-overflow recovery and as a reference for subagents.
    Returns the file path written.
    """
    plan_dir = Config.SUBAGENT_DIR / run_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = str(plan_dir / "plan.md")
    content = f"# Sentinel Research Plan\n\n**Topic:** {topic}\n\n## Research Backlog\n"
    for i, q in enumerate(backlog, 1):
        content += f"{i}. {q}\n"
    Path(plan_path).write_text(content, encoding="utf-8")
    return plan_path


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1 — LEAD RESEARCHER (Orchestrator)
#
# CURRENT: plans backlog + does one search per backlog item (sequential).
# TARGET:  plans backlog + spawns N parallel Subagent nodes via Send() API.
#
# TODO[AGENT]: PARALLEL-SUBAGENTS
#   1. Extract the search loop below into a separate subagent_node() function.
#   2. In lead_researcher_node(), build subagent_tasks (List[Dict]) and
#      return them for LangGraph's Send() to dispatch in parallel.
#   3. Each subagent writes its findings to output/subagents/<run_id>/<id>.md
#      and returns a file path, not the content.
#   4. LeadResearcher reads only the first 500 chars of each artifact (summary)
#      to decide if more research is needed — not the full content.
#   Reference: README.md → Node Responsibilities → LeadResearcher
# ══════════════════════════════════════════════════════════════════════════════

def lead_researcher_node(state: AgentState) -> Dict:
    llm = make_llm()
    topic = state["topic"]
    current_iter = state.get("iterations", 0) + 1
    print(f"\n🔭 [LeadResearcher] Iteration {current_iter}/{Config.MAX_RESEARCH_ITERATIONS}")

    # ── First iteration: build backlog and save plan ──────────────────────────
    if current_iter == 1:
        print(f"  Planning research angles for: {topic}")
        plan_prompt = (
            f"You are an intelligence director. Decompose this geopolitical topic "
            f"into exactly 3 focused, non-overlapping research questions. "
            f"Each question should cover a distinct angle (e.g. one on events/timeline, "
            f"one on key actor positions, one on broader context/implications). "
            f"Return ONLY a JSON array of 3 strings. No preamble.\n\n"
            f"Topic: {topic}"
        )
        res = llm.invoke([
            SystemMessage(content="Return only valid JSON. No markdown fences."),
            HumanMessage(content=plan_prompt),
        ])
        try:
            raw = res.content.strip().replace("```json", "").replace("```", "")
            backlog = json.loads(raw)
            if not isinstance(backlog, list):
                raise ValueError("Not a list")
            backlog = [q for q in backlog if isinstance(q, str)][:3]
        except Exception:
            # Fallback: parse line by line
            backlog = [l.strip("•-1234567890. ") for l in res.content.splitlines()
                       if len(l.strip()) > 10][:3]

        plan_path = write_plan(state["run_id"], topic, backlog)
        print(f"  Plan saved → {plan_path}")
        for i, q in enumerate(backlog, 1):
            print(f"    {i}. {q}")
    else:
        backlog = state.get("research_backlog", [])
        plan_path = state.get("plan_path", "")
        # Refine backlog: add any unresolved questions from last eval
        eval_result = state.get("eval_result")
        if eval_result and eval_result.get("unresolved_questions"):
            for uq in eval_result["unresolved_questions"]:
                if uq not in backlog:
                    backlog.append(uq)
            print(f"  Backlog updated with {len(eval_result['unresolved_questions'])} "
                  f"unresolved questions from evaluator")

    # ── Search: one query per backlog item (MVP — will become parallel subagents)
    # Limit to MAX_SEARCH_CALLS_PER_SUBAGENT to stay within free-tier quota.
    new_intel: List[RawIntel] = []
    queries_to_run = backlog[:Config.MAX_SEARCH_CALLS_PER_SUBAGENT]

    for query in queries_to_run:
        print(f"  🔍 Searching: {query[:70]}...")
        results = search(query, max_results=3)
        new_intel.extend(results)
        print(f"     → {len(results)} results")

    # TODO[AGENT]: ARTIFACTS
    # When parallel subagents are in place, remove the search loop above and
    # instead build subagent_tasks here. The coding agent should return:
    # { "subagent_tasks": [...], "subagent_artifacts": [] }
    # and let the subagent_node() populate subagent_artifacts.

    return {
        "iterations":       current_iter,
        "research_backlog": backlog,
        "plan_path":        plan_path if current_iter == 1 else state.get("plan_path", ""),
        "raw_intel":        new_intel,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2 — CROSS-EXAMINER (Bias Analyzer)
#
# Produces typed BiasEntry records — NOT free-text analysis.
# Checks data/bias_ratings.json first; only calls LLM for unknown domains.
#
# TODO[AGENT]: DUAL-MODEL
#   When ENABLE_CROSS_MODEL_BIAS is True:
#   1. Import ChatGroq from langchain_groq.
#   2. Run classify_domain() prompt through Groq as well.
#   3. If Gemini and Groq disagree on lean, set model_disagreement=True.
#   Reference: README.md → Optional Free Enhancements → #3
# ══════════════════════════════════════════════════════════════════════════════

def cross_examiner_node(state: AgentState) -> Dict:
    llm = make_llm()
    print(f"\n⚖️  [CrossExaminer] Tagging {len(state['raw_intel'])} intel records...")

    # Only process intel added in the latest iteration (avoid reprocessing)
    # In the sequential MVP, all intel is new. With parallel subagents,
    # filter by subagent_id of artifacts from this iteration.
    seen_domains = {e["domain"] for e in state.get("bias_matrix", [])}
    new_bias_entries: List[BiasEntry] = []

    for record in state["raw_intel"]:
        url = record.get("source_url", "")
        if not url:
            continue
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = url

        if domain in seen_domains:
            continue  # already classified this run
        seen_domains.add(domain)

        classification = classify_domain(domain, llm)
        entry = BiasEntry(
            domain=domain,
            lean=classification.get("lean", "unknown"),
            reliability=classification.get("reliability", "unknown"),
            method=classification.get("method", "unknown"),
            model_disagreement=False,   # TODO[AGENT]: set True when dual-model disagrees
            notes=classification.get("notes", ""),
        )
        new_bias_entries.append(entry)
        print(f"  {domain:35s} → {entry['lean']:25s} [{entry['method']}]")

    return {"bias_matrix": new_bias_entries}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3 — TIMELINE COMPILER
#
# Standalone node — NOT folded into CrossExaminer.
# Produces typed ChronEntry records with conflict detection.
#
# TODO[AGENT]: GDELT
#   When ENABLE_GDELT is True, after LLM extraction:
#   1. Call src/tools/gdelt.py with the topic keywords.
#   2. Merge GDELT event records into chronology (set confidence="high"
#      for events that appear in both LLM extraction and GDELT).
#   3. Flag any LLM-extracted date that GDELT contradicts as conflict_flag=True.
#   Reference: README.md → Optional Free Enhancements → #1
# ══════════════════════════════════════════════════════════════════════════════

def timeline_compiler_node(state: AgentState) -> Dict:
    llm = make_llm()
    print(f"\n📅 [TimelineCompiler] Extracting dated events...")

    # Compile all snippets from raw_intel for extraction
    # Keep this prompt SHORT — only pass snippets, not full documents
    snippets = []
    for record in state["raw_intel"]:
        if record.get("snippet"):
            snippets.append(f"[{record.get('published_date','?')}] "
                           f"{record['snippet'][:200]}")

    if not snippets:
        print("  No snippets to process.")
        return {"chronology": []}

    extract_prompt = (
        f"Extract all explicitly dated events from these news snippets about: "
        f"{state['topic']}\n\n"
        f"Snippets:\n" + "\n".join(snippets[:10]) +  # cap at 10 to save tokens
        f"\n\nReturn ONLY a JSON array. Each item: "
        f'{{ "date": "YYYY-MM or YYYY-MM-DD", "event": "one sentence", '
        f'"source_url": "url or empty string", "confidence": "high|medium|low" }}\n'
        f"If no clear dates found, return []."
    )

    try:
        res = llm.invoke([
            SystemMessage(content="Return only valid JSON array. No markdown fences."),
            HumanMessage(content=extract_prompt),
        ])
        raw = res.content.strip().replace("```json", "").replace("```", "")
        events = json.loads(raw)
        if not isinstance(events, list):
            events = []
    except Exception as e:
        print(f"  Timeline extraction failed: {e}")
        events = []

    # Build typed records and detect conflicts
    existing_dates = {e["date"]: e["event"] for e in state.get("chronology", [])}
    new_entries: List[ChronEntry] = []

    for ev in events:
        date = ev.get("date", "")
        event_text = ev.get("event", "")
        if not date or not event_text:
            continue

        # Simple conflict detection: same date, meaningfully different event desc
        conflict = (date in existing_dates and
                    existing_dates[date].lower()[:30] != event_text.lower()[:30])

        new_entries.append(ChronEntry(
            date=date,
            event=event_text,
            source_url=ev.get("source_url", ""),
            confidence=ev.get("confidence", "medium"),
            conflict_flag=conflict,
        ))

    # Sort by date
    new_entries.sort(key=lambda x: x["date"])
    print(f"  Extracted {len(new_entries)} dated events "
          f"({sum(1 for e in new_entries if e['conflict_flag'])} conflicts)")

    return {"chronology": new_entries}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4 — SUFFICIENCY EVALUATOR
#
# Returns a structured EvalResult dict — NOT a hardcoded iteration count.
# The router reads eval_result["status"] to decide: continue | synthesize.
#
# Design principle from Anthropic's post:
# "Judge whether agents achieved the right outcomes while following a
# reasonable process" — not whether they followed a fixed number of steps.
# ══════════════════════════════════════════════════════════════════════════════

def sufficiency_evaluator_node(state: AgentState) -> Dict:
    llm = make_llm()
    print(f"\n🔎 [SufficiencyEvaluator] Checking research coverage...")

    # Hard cap — safety valve regardless of LLM decision
    if state.get("iterations", 0) >= Config.MAX_RESEARCH_ITERATIONS:
        print(f"  Hard cap reached ({Config.MAX_RESEARCH_ITERATIONS} iterations) → synthesize")
        return {"eval_result": EvalResult(
            status="synthesize",
            confidence=0.7,
            unresolved_questions=[],
            reasoning="Hard iteration cap reached.",
        )}

    backlog_str = "\n".join(f"- {q}" for q in state.get("research_backlog", []))
    intel_count = len(state.get("raw_intel", []))
    chron_count = len(state.get("chronology", []))
    bias_count  = len(state.get("bias_matrix", []))

    eval_prompt = (
        f"You are evaluating whether enough research has been gathered to write "
        f"a high-quality intelligence brief.\n\n"
        f"Topic: {state['topic']}\n\n"
        f"Research backlog (questions we set out to answer):\n{backlog_str}\n\n"
        f"Evidence gathered so far:\n"
        f"- {intel_count} source records\n"
        f"- {chron_count} dated events in timeline\n"
        f"- {bias_count} sources bias-classified\n\n"
        f"Respond ONLY with JSON:\n"
        f'{{"status": "continue" or "synthesize", '
        f'"confidence": 0.0-1.0, '
        f'"unresolved_questions": ["...", ...], '
        f'"reasoning": "one sentence"}}\n\n'
        f'Use "synthesize" if confidence >= 0.65 or intel_count >= 6. '
        f'Use "continue" only if critical backlog questions have zero coverage. '
        f"Keep unresolved_questions to max 2 items."
    )

    try:
        res = llm.invoke([
            SystemMessage(content="Return only valid JSON. No markdown fences."),
            HumanMessage(content=eval_prompt),
        ])
        raw = res.content.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(raw)
        result = EvalResult(
            status=parsed.get("status", "synthesize"),
            confidence=float(parsed.get("confidence", 0.7)),
            unresolved_questions=parsed.get("unresolved_questions", []),
            reasoning=parsed.get("reasoning", ""),
        )
    except Exception as e:
        print(f"  Evaluator JSON parse failed: {e} — defaulting to synthesize")
        result = EvalResult(
            status="synthesize",
            confidence=0.65,
            unresolved_questions=[],
            reasoning="Evaluator parse error — proceeding to synthesis.",
        )

    print(f"  Status: {result['status'].upper()} | "
          f"Confidence: {result['confidence']:.0%} | "
          f"{result['reasoning']}")
    return {"eval_result": result}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 5 — SYNTHESIS ENGINE
#
# Reads TYPED structured data — not stringified blobs.
# Does NOT handle citations — that is the Citation Agent's responsibility.
# ══════════════════════════════════════════════════════════════════════════════

def synthesis_node(state: AgentState) -> Dict:
    llm = make_llm()
    print(f"\n📝 [SynthesisEngine] Compiling intelligence brief...")

    # Build structured context from typed records
    # Cap sizes to stay within token budget
    timeline_md = "\n".join(
        f"- **{e['date']}** — {e['event']}"
        f"{' ⚠️ CONFLICT' if e['conflict_flag'] else ''}"
        f" [{e['confidence']} confidence]"
        for e in sorted(state.get("chronology", []), key=lambda x: x["date"])
    ) or "No dated events extracted."

    bias_md = "\n".join(
        f"- `{e['domain']}` → {e['lean']} | reliability: {e['reliability']}"
        f"{' | ⚠️ MODEL DISAGREEMENT' if e['model_disagreement'] else ''}"
        for e in state.get("bias_matrix", [])
    ) or "No bias classifications available."

    # Pass source snippets — capped to avoid token overflow
    intel_items = state.get("raw_intel", [])[:12]
    intel_md = "\n\n".join(
        f"**[{r.get('published_date','?')}] {r.get('title','Untitled')}**\n"
        f"{r.get('snippet','')[:300]}\n"
        f"Source: {r.get('source_url','')}"
        for r in intel_items
    ) or "No intel records."

    synthesis_prompt = (
        f"Write a structured intelligence brief in markdown. "
        f"Tone: neutral, analytical, intelligence-report style. "
        f"Do NOT include citations inline — these will be added by the citation agent. "
        f"Separate confirmed facts from speculative claims. "
        f"Weight claims by how many independent sources corroborate them.\n\n"
        f"Topic: {state['topic']}\n\n"
        f"## Timeline of Events\n{timeline_md}\n\n"
        f"## Source Bias Context\n{bias_md}\n\n"
        f"## Raw Intelligence\n{intel_md}\n\n"
        f"Structure the brief with these exact headings:\n"
        f"- Executive Summary\n"
        f"- Chronological Context\n"
        f"- Confirmed Positions & Facts\n"
        f"- Conflicting Narrative Vectors\n"
        f"- Geopolitical Outlook\n"
    )

    res = llm.invoke([
        SystemMessage(content=(
            "You are writing a classified intelligence brief. "
            "Be concise, factual, and explicitly note when claims are contested or single-sourced."
        )),
        HumanMessage(content=synthesis_prompt),
    ])

    print(f"  Synthesis complete ({len(res.content)} chars)")
    return {"synthesis": res.content}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 6 — CITATION AGENT
#
# CURRENT: stub that appends a formatted source list.
# TARGET:  matches every factual claim in synthesis to a source URL,
#          inserts inline citation markers, flags [UNCITED] assertions.
#
# TODO[AGENT]: CITATION-AGENT
#   1. Parse synthesis into sentences.
#   2. For each sentence, use LLM or string matching to find the best
#      matching RawIntel record.
#   3. Insert [N] citation markers at the end of each attributed sentence.
#   4. Append a numbered Sources section.
#   5. Add an "Uncited Claims" section for sentences with no match.
#   Reference: README.md → Node Responsibilities → Citation Agent
# ══════════════════════════════════════════════════════════════════════════════

def citation_agent_node(state: AgentState) -> Dict:
    print(f"\n🔗 [CitationAgent] Appending source list...")

    synthesis = state.get("synthesis", "")

    # Build numbered source list from raw_intel
    seen_urls: List[str] = []
    sources_md = "\n## Sources\n"
    for record in state.get("raw_intel", []):
        url = record.get("source_url", "")
        if url and url not in seen_urls:
            seen_urls.append(url)
            n = len(seen_urls)
            title = record.get("title", url)
            date  = record.get("published_date", "")
            sources_md += f"{n}. [{title}]({url})"
            if date:
                sources_md += f" — {date}"
            sources_md += "\n"

    # TODO[AGENT]: CITATION-AGENT — replace stub above with real claim matching.
    # For now, append uncited notice so human reviewers know to check.
    uncited_notice = (
        "\n## ⚠️ Citation Status\n"
        "_Inline citation matching not yet implemented. "
        "All claims should be verified against the Sources list above "
        "before treating this brief as a finished assessment._\n"
    )

    final_report = synthesis + sources_md + uncited_notice

    # Write to disk
    slug = state["topic"][:50].lower().replace(" ", "-").replace("/", "-")
    date_str = datetime.date.today().isoformat()
    output_path = Config.OUTPUT_DIR / f"{slug}-{date_str}.md"

    header = (
        f"# Intelligence Brief: {state['topic']}\n"
        f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Run ID:** `{state['run_id']}`  \n"
        f"**Sources indexed:** {len(seen_urls)}  \n"
        f"**Iterations:** {state.get('iterations', 0)}  \n\n---\n\n"
    )
    output_path.write_text(header + final_report, encoding="utf-8")
    print(f"  ✅ Brief written → {output_path}")

    return {"final_report": header + final_report}


# ──────────────────────────────────────────────────────────────────────────────
# ROUTER — reads EvalResult.status, not an iteration counter
# ──────────────────────────────────────────────────────────────────────────────

def route_after_evaluator(state: AgentState) -> str:
    eval_result = state.get("eval_result")
    if eval_result and eval_result.get("status") == "continue":
        return "continue_research"
    return "synthesize"


# ──────────────────────────────────────────────────────────────────────────────
# GRAPH ASSEMBLY
# ──────────────────────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Assembles the LangGraph execution graph.

    Current flow (sequential MVP):
      lead_researcher → cross_examiner → timeline_compiler
                                               ↓
                                       sufficiency_evaluator
                                         ↙            ↘
                               (continue)              (synthesize)
                                   ↓                       ↓
                            lead_researcher           synthesis
                                                          ↓
                                                    citation_agent → END

    TODO[AGENT]: PARALLEL-SUBAGENTS
      Replace the lead_researcher → cross_examiner edge with:
        lead_researcher → Send("subagent", task) × N (parallel dispatch)
        subagent × N   → cross_examiner (fan-in after all subagents complete)
      Reference: LangGraph docs → Parallel Branches / Send API
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("lead_researcher",       lead_researcher_node)
    workflow.add_node("cross_examiner",        cross_examiner_node)
    workflow.add_node("timeline_compiler",     timeline_compiler_node)
    workflow.add_node("sufficiency_evaluator", sufficiency_evaluator_node)
    workflow.add_node("synthesis",             synthesis_node)
    workflow.add_node("citation_agent",        citation_agent_node)

    workflow.set_entry_point("lead_researcher")
    workflow.add_edge("lead_researcher",       "cross_examiner")
    workflow.add_edge("cross_examiner",        "timeline_compiler")
    workflow.add_edge("timeline_compiler",     "sufficiency_evaluator")

    workflow.add_conditional_edges(
        "sufficiency_evaluator",
        route_after_evaluator,
        {
            "continue_research": "lead_researcher",
            "synthesize":        "synthesis",
        }
    )

    workflow.add_edge("synthesis",      "citation_agent")
    workflow.add_edge("citation_agent", END)

    return workflow.compile()


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

def run(topic: str) -> str:
    """
    Run Sentinel for a given topic. Returns the final brief as a string.

    Cost-conscious defaults:
      MAX_RESEARCH_ITERATIONS = 2  (set in .env or Config)
      MAX_SEARCH_CALLS        = 2  (per iteration)

    Raise these only after confirming quota headroom.
    """
    print(f"\n{'═'*60}")
    print(f"  SENTINEL — Geopolitical Intelligence Agent")
    print(f"  Model:    {Config.LLM_MODEL}")
    print(f"  Search:   {Config.SEARCH_PROVIDER.upper()}")
    print(f"  Max iter: {Config.MAX_RESEARCH_ITERATIONS}")
    print(f"  Topic:    {topic}")
    print(f"{'═'*60}\n")

    app = build_graph()
    run_id = datetime.date.today().isoformat() + "-" + uuid.uuid4().hex[:6]

    initial_state: AgentState = {
        "topic":              topic,
        "run_id":             run_id,
        "plan_path":          "",
        "research_backlog":   [],
        "subagent_artifacts": [],
        "raw_intel":          [],
        "bias_matrix":        [],
        "chronology":         [],
        "iterations":         0,
        "eval_result":        None,
        "synthesis":          "",
        "final_report":       "",
    }

    final_state = app.invoke(initial_state)
    return final_state.get("final_report", "")


if __name__ == "__main__":
    # ── TEST TOPIC ────────────────────────────────────────────────────────────
    # Deliberately short and contained:
    #   - One clear geopolitical event cluster
    #   - Multiple actor positions to test bias detection
    #   - Enough recent coverage for Tavily to find 6+ sources
    #   - Should complete in 1–2 iterations without hitting free-tier limits
    #
    # Change this to any topic once the architecture is working.
    # DO NOT use a broad topic (e.g. "US-China relations") during development —
    # it will exhaust iterations without producing a focused brief.
    # ─────────────────────────────────────────────────────────────────────────
    TEST_TOPIC = "India-China LAC border disengagement agreements 2024-2025"

    result = run(TEST_TOPIC)

    print(f"\n{'─'*60}")
    print("  Brief preview (first 500 chars):")
    print(f"{'─'*60}")
    print(result[:500])
    print(f"\n  Full brief saved to: {Config.OUTPUT_DIR}/")