import json
from pathlib import Path
from typing import Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import Config
from src.agent.state import SubagentTask, RawIntel
from src.tools.search import search
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import (
    SUBAGENT_SYSTEM,
    SUBAGENT_DECISION_USER,
    SUBAGENT_REPORT_USER,
)

def _build_intel_brief_summary(intel_list: List[RawIntel]) -> str:
    """Helper to stringify search results briefly for the LLM decision loop to save tokens."""
    if not intel_list:
        return "No search results gathered yet."
    summary_lines = []
    for i, r in enumerate(intel_list, 1):
        snippet_preview = r.get('snippet', '')
        if len(snippet_preview) > 100:
            snippet_preview = snippet_preview[:100] + "..."
        summary_lines.append(
            f"Source [{i}]: {r.get('title', 'Untitled')}\n"
            f"URL: {r.get('source_url', '')}\n"
            f"Snippet Preview: {snippet_preview}\n"
            f"Query: {r.get('query', '')}\n"
            f"---"
        )
    return "\n".join(summary_lines)


def _build_intel_full_summary(intel_list: List[RawIntel]) -> str:
    """Helper to stringify search results with full snippets or body texts for compiling the final report."""
    if not intel_list:
        return "No search results gathered yet."
    summary_lines = []
    for i, r in enumerate(intel_list, 1):
        text_content = r.get("full_text") or r.get("snippet", "")
        if text_content:
            text_content = text_content[:4000] # Cap per source to avoid token blowup
        summary_lines.append(
            f"Source [{i}]: {r.get('title', 'Untitled')}\n"
            f"URL: {r.get('source_url', '')}\n"
            f"Content: {text_content}\n"
            f"Published: {r.get('published_date', '')}\n"
            f"Query: {r.get('query', '')}\n"
            f"---"
        )
    return "\n".join(summary_lines)


def subagent_node(task: SubagentTask) -> Dict:
    """
    Subagent node that runs in parallel.
    Receives a SubagentTask object, executes a search-evaluate-refine loop,
    writes a markdown report to the disk, and returns the gathered raw intel.
    """
    subagent_id = task["subagent_id"]
    topic = task["topic"]
    task_desc = task["task"]
    if isinstance(task_desc, dict):
        task_desc = "\n".join(f"{k.capitalize()}: {v}" for k, v in task_desc.items())
    elif not isinstance(task_desc, str):
        task_desc = str(task_desc)

    output_path = task["output_path"]
    print(f"\\[Subagent:{subagent_id}] Starting task: {task_desc[:60]}...")

    local_intel: List[RawIntel] = []
    calls_made = 0
    max_calls = Config.MAX_SEARCH_CALLS_PER_SUBAGENT

    # --- Search-Evaluate-Refine loop ---
    while calls_made < max_calls:
        intel_summary = _build_intel_brief_summary(local_intel)
        prompt = SUBAGENT_DECISION_USER.format(
            task=task_desc,
            topic=topic,
            intel_summary=intel_summary,
            calls_made=calls_made,
            max_calls=max_calls
        )

        try:
            res = safe_llm_invoke([
                SystemMessage(content=SUBAGENT_SYSTEM),
                HumanMessage(content=prompt),
            ], model=Config.SUBAGENT_MODEL, temperature=0.1)
            raw = res.content.strip().replace("```json", "").replace("```", "")
            decision = json.loads(raw)
        except Exception as e:
            print(f"  [Subagent:{subagent_id}] Decision parsing failed: {e} — finalizing loop")
            break

        action = decision.get("action", "finalize")
        reasoning = decision.get("reasoning", "")

        if action == "search":
            query = decision.get("query", "")
            if not query:
                print(f"  [Subagent:{subagent_id}] LLM requested search but query was empty. Finalizing.")
                break
            
            print(f"   [Subagent:{subagent_id}] (Call {calls_made+1}/{max_calls}) Searching: '{query}'")
            results = search(query, subagent_id=subagent_id, max_results=3, enable_rss=task.get("enable_rss", True))
            
            # Fetch full text for the retrieved search results
            from src.tools.fetch import fetch_article
            for r in results:
                url = r.get("source_url")
                if url:
                    print(f"   [Subagent:{subagent_id}] Fetching full text for {url[:60]}...")
                    body = fetch_article(url)
                    r["full_text"] = body if body else None
                else:
                    r["full_text"] = None

            local_intel.extend(results)
            print(f"     → Found {len(results)} results ({reasoning[:50]}...)")
            calls_made += 1
        else:
            print(f"   [Subagent:{subagent_id}] Finalizing research. Reasoning: {reasoning}")
            break

    # --- Finalize and write report to disk ---
    print(f"   [Subagent:{subagent_id}] Writing research report...")
    intel_summary = _build_intel_full_summary(local_intel)
    report_prompt = SUBAGENT_REPORT_USER.format(
        task=task_desc,
        topic=topic,
        intel_summary=intel_summary,
        subagent_id=subagent_id
    )

    try:
        res = safe_llm_invoke([
            SystemMessage(content=SUBAGENT_SYSTEM),
            HumanMessage(content=report_prompt),
        ], model=Config.SUBAGENT_MODEL, temperature=0.2)
        report_content = res.content
    except Exception as e:
        print(f"  [Subagent:{subagent_id}] Both Gemini and Groq failed for report generation: {type(e).__name__}: {e}")
        report_content = f"# Research Report: {subagent_id}\n\nFailed to compile findings. Gathered {len(local_intel)} sources."

    # Write artifact file to output directory
    try:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report_content, encoding="utf-8")
        print(f"   [Subagent:{subagent_id}] Artifact saved → {output_path}")
    except Exception as e:
        print(f"   [Subagent:{subagent_id}] Failed to write artifact to filesystem: {e}")

    # Return lists to be merged by state reducers (operator.add)
    return {
        "raw_intel": local_intel,
        "subagent_artifacts": [output_path]
    }
