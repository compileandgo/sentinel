# 🛰️ Sentinel — Autonomous Geopolitical Intelligence Agent

> A multi-agent, bias-aware research system for political, national, and international topics — built on Anthropic's orchestrator-parallel-subagent architecture, entirely on free-tier tooling.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-1c1c1c)](https://github.com/langchain-ai/langgraph) ![Cost](https://img.shields.io/badge/cost-%240%20%2Fmonth-brightgreen) [![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](file:///home/thelostpointer/research_agent/LICENSE)


## Table of Contents

1. [Why Sentinel Exists](#why-sentinel-exists)

2. \[Architecture — What Anthropic Taught Us\](\#architecture--wha\[x\] GitHub Actions scheduled runst-anthropic-taught-us)

3. [Key Features](#key-features)

4. [Graph State](#graph-state)

5. [Node Responsibilities](#node-responsibilities)

6. [Prompt Engineering Principles](#prompt-engineering-principles)

7. [Context & Token Management](#context--token-management)

8. [Evaluation Harness](#evaluation-harness)

9. [Target vs. Current MVP](#target-vs-current-mvp)

10. [Project Structure](#project-structure)

11. [Tech Stack (All Free)](#tech-stack-all-free)

12. [Getting Started](#getting-started)

13. [Configuration](#configuration)

14. [Usage](#usage)

15. [Sample Output](#sample-output)

16. [Extending the Agent](#extending-the-agent)

17. [Optional Free Enhancements](#optional-free-enhancements)

18. [Roadmap](#roadmap)

19. [Limitations & Responsible Use](#limitations--responsible-use)

20. [Contributing](#contributing)

21. [Acknowledgments & Prior Art](#acknowledgments--prior-art)

22. [License](#license)


## Why Sentinel Exists

Researching political and geopolitical topics with a single-shot LLM prompt produces shallow, biased, and temporally confused output. Sources contradict each other, state-affiliated outlets push narrative framing, op-eds masquerade as reporting, and event timelines get scrambled with historical background.

Sentinel addresses this by implementing the same **orchestrator-parallel-subagent** pattern used in Anthropic's production Research system — adapted for a zero-cost stack. A lead agent plans and delegates; parallel subagents explore independent angles simultaneously; a citation agent attributes every claim; a bias-aware cross-examiner tags every source. The graph loops until a sufficiency evaluator confirms the research is genuinely complete.

The entire core stack is free: **Gemini 2.5 Flash** (Google AI Studio), **Tavily Search** (1,000 free credits/month), and **LangGraph** for orchestration — with DuckDuckGo as a no-key fallback. Optional free add-ons (GDELT, Groq cross-checking, LangSmith tracing, GitHub Actions scheduling) extend it further at zero cost.

> **Model note:** Gemini 1.5 Flash and 2.0 Flash/Flash-Lite are deprecated as of June 2026. Use `gemini-2.5-flash` (or `gemini-3-flash` if available on your account). Both remain free on Google AI Studio.


## Architecture — What Anthropic Taught Us

Sentinel's architecture is directly informed by Anthropic's engineering post on their production Research system. Here are the specific lessons we adapted and how:

| Anthropic's production finding | How Sentinel adapts it (free-tier version) |
| - | - |
| Lead agent + parallel subagents outperformed single-agent by 90.2% | Sentinel uses a LeadResearcher that spawns 2–5 parallel Subagents per iteration, bounded to stay within free-tier token budgets |
| Token usage explains 80% of quality variance | Subagent count and tool-call budget are the primary tuning levers; both are configurable in `.env` |
| Subagents writing to filesystem prevents "game of telephone" token loss | Subagents write markdown artifacts to `output/subagents/\<run\_id\>/` and pass lightweight file references to the lead agent |
| Start wide, then narrow — short broad queries before specific ones | Director prompt explicitly instructs: first query broad (1–3 words), evaluate coverage, then narrow on gaps |
| Scale effort to query complexity | Scaling rules embedded in prompts: simple fact → 1 subagent/3–10 calls; comparison → 2–4 subagents; complex research → up to 5 subagents (free-tier cap) |
| CitationAgent as a dedicated final stage | Sentinel adds a CitationAgent node that post-processes the synthesis, matches claims to source URLs, and flags uncited assertions |
| Lead agent saves plan to Memory before context can overflow | LeadResearcher writes its plan to `output/subagents/\<run\_id\>/plan.md` at start; recovered on context overflow |
| LLM-as-judge eval aligned best with human judgment | Sentinel includes an optional eval harness (`src/eval/`) with a single-call rubric scorer |
| Extended/interleaved thinking improves subagent quality | Subagents prompt includes an explicit self-evaluation step after each tool result before issuing the next query |


### Architecture Diagram

```
                    ┌───────────────────────────────────┐  
                    │          User Research Topic      │  
                    └─────────────────┬─────────────────┘  
                                      │  
                                      ▼  
                    ┌───────────────────────────────────┐  
          ┌────────▶│        LeadResearcher Agent       │◀──────────────────┐  
          │         │  1. Saves plan to filesystem      │                   │  
          │         │  2. Decomposes topic into N tasks │                   │  
          │         │  3. Scales N to query complexity  │                   │  
          │         └──────┬──────┬──────┬──────────────┘                   │  
          │                │      │      │  (spawns in parallel)            │  
          │                ▼      ▼      ▼                                  │  
          │    ┌───────────┐ ┌───────────┐ ┌───────────┐                    │  
          │    │ Subagent 1│ │ Subagent 2│ │ Subagent N│                    │  
          │    │ (angle A) │ │ (angle B) │ │ (angle N) │                    │  
          │    │ searches  │ │ searches  │ │ searches  │                    │  
          │    │ evaluates │ │ evaluates │ │ evaluates │                    │  
          │    │ writes    │ │ writes    │ │ writes    │                    │  
          │    │ artifact  │ │ artifact  │ │ artifact  │                    │  
          │    └─────┬─────┘ └─────┬─────┘ └─────┬─────┘                    │  
          │          │             │             │                          │  
          │          └─────────────┴─────────────┘                          │  
          │                        │ (lightweight file references)          │  
          │                        ▼                                        │  
          │         ┌──────────────────────────────┐                        │  
          │         │       Cross-Examiner         │                        │  
          │         │  bias tagging + static table │                        │  
          │         └──────────────┬───────────────┘                        │  
          │                        │                                        │  
          │                        ▼                                        │  
          │         ┌──────────────────────────────┐                        │  
          │         │       Timeline Compiler      │                        │  
          │         │  date extraction + GDELT opt.│                        │  
          │         └──────────────┬───────────────┘                        │  
          │                        │                                        │  
          │                        ▼                                        │  
          │         ┌──────────────────────────────┐                        │  
          │         │     Sufficiency Evaluator    │──── (needs more) ──────┘  
          │         └──────────────┬───────────────┘  
          │                        │ (backlog resolved)  
          │                        ▼  
          │         ┌──────────────────────────────┐  
          │         │      Synthesis Engine        │  
          │         │  bias-weighted, neutral brief│  
          │         └──────────────┬───────────────┘  
          │                        │  
          │                        ▼  
          │         ┌──────────────────────────────┐  
          └─────────│       Citation Agent         │  
                    │  matches claims → source URLs│  
                    │  flags uncited assertions    │  
                    └──────────────┬───────────────┘  
                                   │  
                                   ▼  
                    ┌──────────────────────────────┐  
                    │   Final Markdown Intelligence│  
                    │   Brief (with citations)     │  
                    └──────────────────────────────┘
```


## Key Features

- **Orchestrator-parallel-subagent graph** — LeadResearcher decomposes the topic and spawns 2–5 parallel Subagents, each with a distinct research angle and its own search context, bounded to stay within free-tier quotas.

- **Filesystem artifact pattern** — Subagents write their findings directly to disk and return lightweight file references. This prevents "game of telephone" token loss when aggregating through the lead agent.

- **Query scaling rules** — The LeadResearcher's prompt encodes explicit effort budgets: simple queries get 1 subagent and 3–10 search calls; complex multi-angle topics get up to 5 subagents with divided responsibilities.

- **Bias-aware ingestion** — Cross-Examiner tags every source with a narrative-lean classification (optionally backed by a static bias-rating table), producing a structured `bias\_matrix` rather than free-text opinions.

- **Structured temporal reconciliation** — Timeline Compiler extracts dated events into typed records, resolves conflicts, and optionally cross-references GDELT for structured event grounding.

- **Iterative sufficiency loop** — Sufficiency Evaluator reviews the backlog against current evidence and decides whether to spawn another research round or proceed to synthesis — replacing a naive iteration counter with a genuine completion check.

- **Dedicated Citation Agent** — Final node post-processes the synthesis to match every claim to a source URL and flag anything uncited, following Anthropic's production pattern.

- **Dual-model bias cross-check (optional)** — Runs bias analysis through both Gemini and a Groq-hosted open model; disagreements are recorded as metadata rather than silently resolved.

- **LangSmith tracing (optional)** — Step-by-step visual trace of every graph execution for debugging the research loop.

- **Zero infrastructure** — Single Python process, filesystem-based output; optionally scheduled via free GitHub Actions.


## Graph State

All nodes read and write a single `AgentState` TypedDict that persists for the run. Subagent outputs go to disk; only lightweight references travel through the state object.

| Field | Type | Purpose |
| - | - | - |
| `topic` | `str` | The core research question. |
| `research\_backlog` | `List\[str\]` | Open sub-questions still requiring evidence. |
| `subagent\_tasks` | `List\[Dict\]` | Task specs dispatched to each parallel subagent: angle, query guidance, tool hints, output path. |
| `subagent\_artifacts` | `List\[str\]` | File paths to subagent markdown outputs — lightweight references, not the content itself. |
| `raw\_intel` | `List\[Dict\]` | Typed records: `\{source\_url, title, snippet, published\_date, query, subagent\_id\}`. |
| `bias\_matrix` | `List\[Dict\]` | Typed records: `\{domain, lean, reliability, method, model\_disagreement\}`. |
| `chronology` | `List\[Dict\]` | Typed records: `\{date, event, source\_url, confidence, conflict\_flag\}`. |
| `plan\_path` | `str` | Filesystem path where LeadResearcher wrote its plan (recovered on context overflow). |
| `iterations` | `int` | Loop counter / hard safety cap. |
| `synthesis` | `str` | Intermediate synthesis from Synthesis Engine. |
| `final\_report` | `str` | Final brief with citations from Citation Agent. |



## Node Responsibilities

### 1. LeadResearcher (Orchestrator)

The entry point and loop controller. On first entry it writes a research plan to `output/subagents/\<run\_id\>/plan.md` (persists across context overflows), then decomposes the topic into parallel task specs. On subsequent iterations it reads artifact summaries from the previous round and issues refined tasks.

**Scaling rules embedded in prompt:**

- Simple fact / single event → 1 subagent, 3–10 tool calls

- Comparison / position mapping → 2–3 subagents, clearly divided by country/actor/timeframe

- Deep multi-angle research → 4–5 subagents (free-tier cap), each with non-overlapping scope

### 2. Subagents (Parallel Workers)

Each subagent receives a specific task spec (angle, search guidance, output path) and independently executes a search-evaluate-refine loop:

1. Issue a **short broad query** first — evaluate coverage.

2. Based on results, narrow and issue 2–3 targeted follow-up queries.

3. After each tool result, run a **self-evaluation step** before issuing the next query (explicit in the subagent prompt — mirrors Anthropic's interleaved thinking pattern).

4. Write a structured markdown artifact to its assigned `output\_path` with sections: Summary, Key Facts, Dates Extracted, Source List, Open Questions.

5. Return a lightweight file reference to the LeadResearcher.

Subagents run concurrently using LangGraph's `Send` API.

### 3. Cross-Examiner (Bias Analyzer)

Reads subagent artifacts, checks each source domain against `data/bias\_ratings.json` (static table, checked first), and falls back to an LLM call for unknown domains. Produces typed `bias\_matrix` records. When `ENABLE\_CROSS\_MODEL\_BIAS\_CHECK=true`, runs the same prompt through Groq and records disagreements.

### 4. Timeline Compiler

Extracts dated events from `raw\_intel` into typed `chronology` records. Deduplicates by semantic similarity of the event description, flags conflicts where two sources give different dates for the same event. Optionally queries GDELT DOC 2.0 API for the topic to cross-reference LLM-extracted dates with structured event records.

### 5. Sufficiency Evaluator

Reviews `research\_backlog` against `raw\_intel`, `bias\_matrix`, and `chronology`. Uses a lightweight LLM call with a structured rubric (not free-text). Returns `\{status: "continue" | "synthesize", unresolved\_questions: \[...\], confidence: 0.0–1.0\}`. If `status == "continue"`, loops back to LeadResearcher with the unresolved questions added to the backlog.

### 6. Synthesis Engine

Reads typed structured data (not stringified blobs): `raw\_intel`, `bias\_matrix`, `chronology`, plus subagent artifact summaries. Writes the brief in an intelligence-report tone, explicitly weighting claims by corroboration count and source independence. Does **not** write citations — that is the Citation Agent's job.

### 7. Citation Agent

Receives the synthesis and the full `raw\_intel` record list. Matches each factual claim to a source URL, inserts inline citation markers, and appends a numbered source list at the bottom. Flags any claims it could not attribute — these appear as `\[UNCITED\]` markers for human review. This separation of synthesis from citation follows Anthropic's production pattern: a general coordinator produces better prose than one burdened with tracking attribution inline.


## Prompt Engineering Principles

These principles are drawn directly from Anthropic's engineering findings. Coding agents and contributors should treat them as the primary design constraints when writing or modifying prompts in `src/agent/prompts.py`.

**1. Scale effort to query complexity.** Embed explicit resource-budgeting rules in the LeadResearcher's system prompt. The agent should not be allowed to decide subagent count from scratch — it should pick from a defined tier table. This prevents both under-investment (missing angles) and over-investment (burning through free-tier tokens on simple queries).

**2. Teach the orchestrator how to delegate precisely.** Each subagent task spec must include: objective, expected output format, which tools/sources to prioritize, and explicit scope boundaries (e.g. "cover only events from 2024-01 onward; do not duplicate the semiconductor angle assigned to Subagent 2"). Vague delegation causes duplicated work and gaps.

**3. Start wide, then narrow.** Subagent prompts should explicitly instruct: first query is short (1–3 words + topic keyword), evaluate what's available, then issue progressively narrower queries to fill gaps. Agents default to overly specific queries that return few results.

**4. Self-evaluate after every tool result.** After each search result, subagents should be prompted to ask: "Does this answer my sub-question? What gaps remain? What should my next query be?" This is the free-tier equivalent of Anthropic's interleaved thinking — make the reasoning explicit in the prompt rather than relying on implicit chain-of-thought.

**5. Never inline prompt strings in node files.** All system and user prompts live in `src/agent/prompts.py`, keyed by node name and version. This makes prompt iteration trackable and prevents scattered, unversioned prompt strings spread across the codebase.

**6. Prefer heuristics over rigid rules.** Prompts should encode strategies (how to think about a problem) not scripts (what exact steps to take). Rigid scripts break on edge cases; good heuristics generalize.

**7. Tool descriptions are as important as prompts.** A subagent given a vague tool description will misuse the tool or ignore it. Every tool function must have a clear docstring specifying: what it returns, when to use it vs. alternatives, and what queries work best with it.


## Context & Token Management

Token usage is the primary quality lever in multi-agent research (Anthropic's internal data: token usage explains 80% of quality variance, and multi-agent systems use ~15× more tokens than single-turn chats). For a free-tier system, this requires careful budgeting.

**Subagent count cap.** The primary lever for free-tier cost control. `MAX\_SUBAGENTS=5` (default) is intentionally conservative. For most political research topics, 3 well-scoped subagents with 5–8 searches each produces a better brief than 5 poorly-scoped ones with 3 searches each.

**Filesystem artifact pattern.** Subagents write findings to disk and return file paths. The LeadResearcher reads only the artifact *summaries* (a short header from each file), not the full content. This avoids copying large subagent outputs through the conversation history repeatedly — the biggest hidden token cost in naive aggregation architectures.

**Plan persistence.** The LeadResearcher writes its decomposition plan to `output/subagents/\<run\_id\>/plan.md` before spawning subagents. If the context approaches the model's limit, a fresh continuation can read the plan from disk rather than re-deriving it.

**Model tiering.** The LeadResearcher and Sufficiency Evaluator need strong reasoning. Subagents, Cross-Examiner, and Timeline Compiler can run on a lighter model. Both are Gemini 2.5 Flash in the default config, but the `SUBAGENT\_MODEL` env var allows them to be split if a lighter free-tier option becomes available.

**Hard iteration cap.** `MAX\_RESEARCH\_ITERATIONS` (default: 5) is a safety valve — the Sufficiency Evaluator should terminate the loop before this, but the cap prevents runaway loops that exhaust free-tier quotas on a single topic.


## Evaluation Harness

Reliable evaluation is what separates a demo from a dependable tool. Sentinel includes an optional evaluation harness in `src/eval/` based on Anthropic's LLM-as-judge approach.

### How it works

A single LLM call scores each generated brief against a rubric, outputting structured JSON:

```
\{  
  "factual\_accuracy": 0.85,  
  "citation\_accuracy": 0.90,  
  "completeness": 0.75,  
  "source\_quality": 0.80,  
  "tool\_efficiency": 0.70,  
  "pass": true,  
  "notes": "Missing coverage of East Asian regulatory stance post-2025."  
\}
```

**Rubric dimensions:**

- **Factual accuracy** — do claims in the brief match what the cited sources actually say?

- **Citation accuracy** — are citation markers pointing to the correct source?

- **Completeness** — are all the angles from the original backlog addressed?

- **Source quality** — did the agent prefer primary sources (government statements, wire services, academic PDFs) over SEO-optimized content farms?

- **Tool efficiency** — did the agent use a reasonable number of searches, or did it loop excessively?

### Running evals

```
python -m src.eval.run --brief output/my-topic-2026-06-20.md --topic "your topic here"
```

### Start small

Following Anthropic's lesson: don't wait until you have 100 test cases. Start with 5–10 representative topics and run the eval after every significant prompt change. With effect sizes common in early agent development, small sample evals catch large regressions.


## Target vs. Current MVP

This README describes the **target architecture**. The starter script (`intel\_agent.py`) is a working MVP that implements a simplified linear version of this graph. Use this table as the refactoring checklist.

| Component | Target Architecture | Current MVP | Action Needed |
| - | - | - | - |
| LeadResearcher | Plans, saves plan to disk, spawns parallel subagents | ✅ Plans + searches sequentially | Add `Send` API for parallel dispatch; add plan file write |
| Subagents | Parallel workers with task specs + artifact files | ❌ Not present — director node does everything | Extract into dedicated subagent node with `Send` dispatch |
| Filesystem artifacts | Subagents write markdown files; lead reads summaries | ❌ Everything in state string blobs | Implement artifact write in subagent; read summaries in LeadResearcher |
| Cross-Examiner | Typed `bias\_matrix` records + static table + optional Groq cross-check | Partial — free-text analysis only | Add typed output schema; seed `data/bias\_ratings.json` |
| Timeline Compiler | Standalone node, typed records, dedup, conflict flags | Folded into Cross-Examiner | Extract into own node with dedup logic |
| Synthesis Engine | Uses typed structured data | Uses stringified blobs | Pass typed dicts, not joined strings |
| Sufficiency Evaluator | LLM rubric returning structured JSON | Hardcoded `iterations \>= 3` | Replace with structured LLM evaluator |
| Citation Agent | Dedicated final node — matches claims to URLs | ❌ Not present | Add as final node after Synthesis |
| Search provider | Tavily primary / DuckDuckGo fallback, abstracted | Hardcoded `DuckDuckGoSearchRun` | Implement `SearchProvider` interface |
| Eval harness | `src/eval/` with LLM-as-judge rubric scorer | ❌ Not present | Add eval module |


**Coding agents should tackle in this order:**

1. Typed schemas for `raw\_intel`, `bias\_matrix`, and `chronology` — everything else depends on structured data.

2. Subagent node + filesystem artifact pattern + `Send` parallel dispatch.

3. Sufficiency Evaluator with structured JSON output.

4. Citation Agent node.

5. Search provider abstraction (Tavily primary, DuckDuckGo fallback).

6. Eval harness.


## Project Structure

```
sentinel/  
├── .github/  
│   └── workflows/  
│       └── scheduled-research.yml  \# Optional: free daily/weekly runs via GitHub Actions  
├── data/  
│   └── bias\_ratings.json           \# Static domain → \{lean, reliability\} table  
├── src/  
│   ├── agent/  
│   │   ├── state.py                \# AgentState TypedDict + reducers  
│   │   ├── graph.py                \# LangGraph wiring (nodes + edges + Send dispatch)  
│   │   ├── prompts.py              \# ALL prompt templates, centralized and versioned  
│   │   └── nodes/  
│   │       ├── lead\_researcher.py  \# Orchestrator: plan, decompose, dispatch, synthesize loop  
│   │       ├── subagent.py         \# Worker: search-evaluate-refine loop + artifact write  
│   │       ├── cross\_examiner.py   \# Bias tagging → typed bias\_matrix  
│   │       ├── timeline\_compiler.py \# Date extraction → typed chronology  
│   │       ├── sufficiency\_evaluator.py \# Structured JSON rubric → continue | synthesize  
│   │       ├── synthesis.py        \# Neutral brief from typed structured data  
│   │       └── citation\_agent.py   \# Claim → source URL matching + uncited flagging  
│   ├── tools/  
│   │   ├── search.py               \# SearchProvider interface: Tavily primary, DDG fallback  
│   │   ├── source\_classifier.py    \# Domain lookup: bias\_ratings.json → LLM fallback  
│   │   ├── gdelt.py                \# Optional: GDELT DOC 2.0 client for Timeline Compiler  
│   │   ├── rss.py                  \# Optional: wire-service RSS feed reader  
│   │   └── cache.py                \# Optional: local embeddings cache (Chroma/FAISS)  
│   ├── eval/  
│   │   ├── judge.py                \# LLM-as-judge rubric scorer  
│   │   └── run.py                  \# CLI entry point for eval runs  
│   ├── config.py                   \# Env var loading, model config, feature flags  
│   └── main.py                     \# CLI entry point for research runs  
├── output/  
│   ├── subagents/                  \# Per-run subagent artifact directories  
│   │   └── \<run\_id\>/  
│   │       ├── plan.md             \# LeadResearcher plan (persisted for overflow recovery)  
│   │       ├── subagent\_1.md  
│   │       └── subagent\_N.md  
│   └── \<topic-slug\>-\<date\>.md     \# Final intelligence brief  
├── tests/  
│   ├── test\_state.py  
│   ├── test\_nodes.py  
│   └── test\_eval.py  
├── .env.example  
├── requirements.txt  
├── README.md  
└── LICENSE
```


## Tech Stack (All Free)

| Layer | Tool | Free Tier Notes |
| - | - | - |
| Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) | Open source, runs locally; `Send` API enables true parallel subagent dispatch |
| LLM | Gemini 2.5 Flash via [Google AI Studio](https://aistudio.google.com/) | Free API key, no credit card; 1.5 and 2.0 Flash deprecated mid-2026 |
| Search (primary) | [Tavily](https://tavily.com/) Free Research plan | 1,000 API credits/month, no credit card, returns clean structured results ideal for `raw\_intel` |
| Search (fallback) | `duckduckgo-search` (DDGS) | No key required; auto-engaged when Tavily credits run out or request errors |
| Secondary LLM (optional) | [Groq](https://console.groq.com/) (Llama 3.3 70B) | Free tier; used as Gemini fallback and second model in dual-model bias cross-check |
| Event data (optional) | [GDELT Project](https://www.gdeltproject.org/) | Fully free, no key; structured global event records for Timeline Compiler grounding |
| News feeds (optional) | Wire-service RSS (Reuters, AP, BBC) | No key; supplements search with dated, attributed wire-service reporting |
| Tracing (optional) | [LangSmith](https://www.langchain.com/langsmith) free tier | Visual per-node trace of every LangGraph run; fastest debugging tool for the research loop |
| Local cache (optional) | Local embeddings + [Chroma](https://www.trychroma.com/) / FAISS | Runs fully locally; deduplicates sources across iterations and runs |
| Automation (optional) | GitHub Actions | Free for public repos; schedules Sentinel as a standing topic monitor |


> 💡 **Token budget tip:** Anthropic's data shows multi-agent systems use ~15× more tokens than single-turn chats. With Gemini 2.5 Flash's free tier, this is manageable — but keep `MAX\_SUBAGENTS ≤ 5` and `MAX\_SEARCH\_CALLS\_PER\_SUBAGENT ≤ 8` until you've confirmed your daily quota headroom.

> ⚠️ **Tavily note:** Tavily was acquired by Nebius in early 2026. The free Research plan is currently unchanged, but keep the DuckDuckGo fallback functional in case terms shift.


## Getting Started

### Prerequisites

- Python 3.10+

- A free [Google AI Studio](https://aistudio.google.com/) API key (for Gemini 2.5 Flash)

- A free [Tavily](https://tavily.com/) API key (1,000 credits/month, no credit card)

- *(Optional)* a free [Groq](https://console.groq.com/) API key — enables LLM fallback and dual-model bias cross-check

- *(Optional)* a free [LangSmith](https://smith.langchain.com/) API key — enables run tracing

### Installation

```
git clone \<your-repo-url\> sentinel  
cd sentinel  
python -m venv .venv  
source .venv/bin/activate   \# Windows: .venv\\Scripts\\activate  
pip install -r requirements.txt
```

### Set up your API keys

```
cp .env.example .env
```

Edit `.env` and paste in:

- your free Gemini key → [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

- your free Tavily key → [https://app.tavily.com/](https://app.tavily.com/) (no credit card)

- *(optional)* your free Groq key → [https://console.groq.com/keys](https://console.groq.com/keys)

- *(optional)* your free LangSmith key → [https://smith.langchain.com/](https://smith.langchain.com/)

DuckDuckGo, GDELT, and RSS feeds need no key and work out of the box. Leave any optional key blank to disable that feature gracefully.

`requirements.txt`:

```
langgraph  
langchain  
langchain-google-genai  
langchain-community  
tavily-python  
duckduckgo-search  
beautifulsoup4  
requests  
python-dotenv  
  
\# Optional free enhancements (comment out any you don't need)  
langchain-groq        \# Groq fallback LLM + dual-model bias cross-check  
langsmith             \# LangGraph run tracing  
feedparser            \# Wire-service RSS feeds  
chromadb              \# Local embedding cache for dedup  
sentence-transformers \# Local embeddings (no API call)
```


## Usage

### Run a research job

```
python -m src.main --topic "Evaluating 2026 international semiconductor trade policy shifts"
```

### Optional flags

```
python -m src.main \\  
  --topic "Recent developments in EU-Mercosur trade negotiations" \\  
  --max-iterations 4 \\  
  --max-subagents 3 \\  
  --output-dir ./output
```

The brief is written to `output/\<slugified-topic\>-\<date\>.md`. Subagent artifacts are in `output/subagents/\<run\_id\>/`.

### Run the eval harness on a completed brief

```
python -m src.eval.run \\  
  --brief output/semiconductor-trade-2026-06-20.md \\  
  --topic "2026 international semiconductor trade policy shifts"
```


## Sample Output

### Final brief structure

```
\# Intelligence Brief: \<Topic\>  
Generated: \<date\> | Run ID: \<id\> | Subagents used: N | Searches: N  
  
\#\# Executive Summary  
...  
  
\#\# Chronological Context  
| Date | Event | Source | Confidence | Conflicts |  
|---|---|---|---|---|  
| 2024-03 | ... | reuters.com | High | None |  
| 2025-11 | ... | xinhua.net | Medium | See \[3\] |  
  
\#\# Confirmed National/International Positions  
...  
  
\#\# Conflicting Narrative Vectors  
| Claim | Source | Lean | Corroborated By | Model Agreement |  
|---|---|---|---|---|  
| ... | State media (Country X) | Pro-government | Uncorroborated | Gemini/Groq agree |  
| ... | Independent wire | Centrist | 2 sources | \[DISPUTED by Groq\] |  
  
\#\# Geopolitical Outlook  
...  
  
\#\# Sources  
1. \[Title\](url) — Reuters, 2026-04-12  
2. ...  
  
\#\# Uncited Claims \[requires human review\]  
- "..." — no source matched
```


## Extending the Agent

### Add a new search provider

Implement the `SearchProvider` protocol in `src/tools/search.py`:

```
class SearchProvider(Protocol):  
    def search(self, query: str) -\> list\[dict\]:  
        """Return \[\{title, url, snippet, published\_date\}\]."""
```

The default wires up `TavilyProvider` (primary) → `DuckDuckGoProvider` (fallback). To add a third, implement the interface and extend the fallback chain in `config.py`.

### Expand the bias taxonomy

`data/bias\_ratings.json` holds the static domain → `\{lean, reliability\}` table. Extend it with additional state-media domains, regional outlets, or think-tank affiliations. `source\_classifier.py` checks this table first and falls back to an LLM call only for unknown domains — making the common case fast and deterministic.

### Add a new node

1. Write the node function in `src/agent/nodes/`.

2. Add all prompts to `prompts.py` with a version key — never inline strings in node files.

3. Register the node and its edges in `graph.py`.

4. Add unit tests in `tests/test\_nodes.py`.

5. If the node produces new state fields, add them to `AgentState` in `state.py` with appropriate reducers.


## Optional Free Enhancements

None of these are required to run Sentinel — each is gated behind an `ENABLE\_\*` flag in `.env` and defaults to off. They're listed in order of value-for-effort.

### 1. GDELT event grounding for the Timeline Compiler

The [GDELT Project](https://www.gdeltproject.org/) publishes a free, no-key, continuously updated database of global events (actors, actions, locations, dates). `src/tools/gdelt.py` queries GDELT's DOC 2.0 API and passes matching event records into the Timeline Compiler alongside LLM-extracted dates. This grounds `chronology` in structured records — directly reducing temporal hallucination, the most common failure mode in political research agents.

### 2. Static bias-rating table

Seed `data/bias\_ratings.json` with a domain → `\{lean, reliability\}` mapping from publicly available media-bias categorization methodologies. `source\_classifier.py` checks this table first; unknown domains fall back to the LLM. This makes `bias\_matrix` entries reproducible and auditable rather than depending on a single model's per-run judgment.

### 3. Dual-model bias cross-check via Groq

When `ENABLE\_CROSS\_MODEL\_BIAS\_CHECK=true`, the Cross-Examiner sends the same bias-analysis prompt to both Gemini and Groq's Llama model. If they disagree on a source's lean or on which claims are "confirmed" vs "speculative," the disagreement is recorded in `bias\_matrix` as `model\_disagreement: true` — surfacing contested classifications rather than presenting a single model's view as ground truth.

### 4. Wire-service RSS feeds for the LeadResearcher

`src/tools/rss.py` polls free RSS feeds from wire services (Reuters, AP, BBC) using `feedparser`. Every entry already carries a publication date and consistent attribution — exactly the structure Timeline Compiler and Cross-Examiner prefer, with less parsing than general search snippets.

### 5. Local embedding cache for deduplication

When `ENABLE\_LOCAL\_CACHE=true`, `src/tools/cache.py` embeds each new `raw\_intel` entry using a local `sentence-transformers` model (no API call) and checks it against a local Chroma or FAISS store. Near-duplicate results across iterations or runs are collapsed before reaching the Cross-Examiner — saving LLM calls and keeping `raw\_intel` free of restatements of the same source.

### 6. LangSmith tracing

Setting `LANGCHAIN\_TRACING\_V2=true` and `LANGSMITH\_API\_KEY` automatically traces every LangGraph run on LangSmith's free tier — a per-node timeline showing exactly what each node read from and wrote to `AgentState`, and the exact prompts/responses involved. The fastest way to debug a misfiring Sufficiency Evaluator or a subagent that duplicated another's work.

### 7. Scheduled runs via GitHub Actions

For a public repo, GitHub Actions provides free compute minutes for scheduled jobs. `.github/workflows/scheduled-research.yml` can run Sentinel on a cron schedule and commit the generated brief back to `output/` — turning Sentinel into a standing "watch this topic" monitor at zero hosting cost.

```
name: Scheduled Research  
on:  
  schedule:  
    - cron: "0 6 \* \* \*"   \# daily at 06:00 UTC  
  workflow\_dispatch: \{\}  
  
jobs:  
  research:  
    runs-on: ubuntu-latest  
    steps:  
      - uses: actions/checkout@v4  
      - uses: actions/setup-python@v5  
        with:  
          python-version: "3.11"  
      - run: pip install -r requirements.txt  
      - run: python -m src.main --topic "$\{\{ vars.RESEARCH\_TOPIC \}\}"  
        env:  
          GOOGLE\_API\_KEY: $\{\{ secrets.GOOGLE\_API\_KEY \}\}  
          TAVILY\_API\_KEY: $\{\{ secrets.TAVILY\_API\_KEY \}\}  
      - uses: stefanzweifel/git-auto-commit-action@v5  
        with:  
          commit\_message: "chore: add scheduled research brief"
```


## Roadmap

**Core graph (build in this order):**

- [ ] Typed schemas for `raw\_intel`, `bias\_matrix`, `chronology` (foundation for everything else)

- [ ] Subagent node with `Send` parallel dispatch + filesystem artifact write

- [ ] Structured Sufficiency Evaluator (JSON rubric output, not iteration count)

- [ ] Citation Agent node

- [ ] Pluggable `SearchProvider` interface (Tavily primary, DuckDuckGo fallback)

- [ ] Plan persistence to disk (context overflow recovery)

**Quality improvements:**

- [ ] Source credibility scoring based on corroboration count

- [ ] Subagent self-evaluation step after each tool result (prompt-level)

- [ ] Multi-language source ingestion + translation step

- [ ] LLM-as-judge eval harness (`src/eval/`)

**Optional free enhancements:**

- [ ] GDELT-grounded timeline compilation

- [ ] Static bias-rating table (`data/bias\_ratings.json`)

- [ ] Dual-model bias cross-check via Groq

- [ ] Wire-service RSS feed ingestion

- [ ] Local embedding cache for cross-run dedup

- [ ] LangSmith tracing

- [x] GitHub Actions scheduled runs

- [x] Optional Streamlit UI for interactive topic input and live graph trace


## Limitations & Responsible Use

- **Free-tier token budgets are real.** Anthropic's data shows multi-agent systems use ~15× more tokens than single chats. Gemini 2.5 Flash's free daily quota is generous for personal research, but `MAX\_SUBAGENTS` and `MAX\_SEARCH\_CALLS\_PER\_SUBAGENT` are your primary cost controls — keep them conservative until you know your quota headroom.

- **Gemini model availability shifts quickly.** Google deprecated 1.5 Flash, then 2.0 Flash within months of each other. Check AI Studio for the current free model before assuming `.env.example` is still accurate.

- **Tavily's free tier could change.** Tavily was acquired by Nebius in early 2026; the free Research plan is currently unchanged, but keep the DuckDuckGo fallback live.

- **Optional services have separate free-tier caps.** Groq, GDELT, and LangSmith are each generous for personal use but can be exhausted under frequent GitHub Actions automation — disable the relevant `ENABLE\_\*` flag if you hit limits.

- **Bias classification is heuristic, not authoritative.** The `bias\_matrix` reflects pattern-based source tagging (optionally cross-referenced with a static table and a second model), not a definitive editorial judgment.

- **Not a substitute for professional analysis.** Sentinel is a research aggregation and drafting tool. Every output should be reviewed by a human before being treated as a finished assessment, especially for high-stakes decisions.

- **Search coverage is incomplete.** Free search APIs, RSS feeds, and GDELT each index a subset of global reporting and may underrepresent certain regions, languages, or paywalled sources.


## Contributing

Issues and PRs are welcome. Before submitting:

1. Run `pytest` to confirm existing tests pass.

2. Keep all prompts in `prompts.py` — never inline strings in node files.

3. New nodes must declare which `AgentState` fields they read and write in their docstring.

4. New state fields must have typed schemas (not `str` blobs) and appropriate reducers in `state.py`.

5. If you change a prompt, add a version comment noting what you changed and why — prompt history matters for debugging regressions.


## Acknowledgments & Prior Art

Sentinel's architecture is directly informed by **Anthropic's engineering post** on their production Claude Research system (June 2025), which documented the orchestrator-parallel-subagent pattern, filesystem artifact approach, citation agent separation, LLM-as-judge evaluation, and prompt engineering principles for multi-agent research. The supervisor-graph pattern additionally draws on **GPT Researcher**, **LangChain's Open Deep Research** templates, and Stanford OVAL's **STORM** project — all of which demonstrated that specialized parallel agents dramatically outperform single-shot prompts for research tasks. Sentinel adapts these production patterns for the bias-sensitive, time-sensitive domain of political and geopolitical research, while staying entirely within free-tier tooling.


## License

MIT — see [LICENSE](file:///home/thelostpointer/research_agent/LICENSE).

