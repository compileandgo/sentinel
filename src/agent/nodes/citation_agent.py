import re
import datetime
from pathlib import Path
from typing import Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import Config
from src.agent.state import AgentState
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import CITATION_SYSTEM, CITATION_USER

def citation_agent_node(state: AgentState) -> Dict:
    print(f"\n [CitationAgent] Aligning claims with source citations...")

    synthesis = state.get("synthesis", "")
    raw_intel = state.get("raw_intel", [])

    # Extract unique source URLs
    seen_urls: List[str] = []
    sources_list_lines: List[str] = []
    
    for r in raw_intel:
        url = r.get("source_url")
        if url and url not in seen_urls:
            seen_urls.append(url)
            num = len(seen_urls)
            title = r.get("title", url)
            date = r.get("published_date", "")
            date_str = f" — {date}" if date else ""
            sources_list_lines.append(f"[{num}] {title} ({url}){date_str}")

    if not seen_urls:
        print("  No sources available for citation matching.")
        return {"final_report": synthesis}

    sources_list_str = "\n".join(sources_list_lines)
    prompt = CITATION_USER.format(
        sources_list=sources_list_str,
        synthesis=synthesis
    )

    try:
        res = safe_llm_invoke([
            SystemMessage(content=CITATION_SYSTEM),
            HumanMessage(content=prompt),
        ], temperature=0.1)
        annotated_brief = res.content
    except Exception as e:
        print(f"  Citation matching LLM call failed: {e}. Appending standard list.")
        annotated_brief = synthesis

    # Extract uncited sentences
    # Split by standard sentence delimiters (.!?) followed by spaces
    sentences = re.split(r'(?<=[.!?])\s+', annotated_brief)
    uncited_claims = []
    for s in sentences:
        if "[UNCITED]" in s:
            claim = s.replace("[UNCITED]", "").strip()
            # Clean up wrapping quotes if any
            claim = re.sub(r'^["\'“]+|["\'”]+$', '', claim).strip()
            # Remove markdown header signs to prevent nested header rendering
            claim = claim.replace("#", "").strip()
            if claim:
                uncited_claims.append(claim)

    # Build the final markdown sources section
    sources_md = "\n\n## Sources\n"
    for i, url in enumerate(seen_urls, 1):
        title = url
        date = ""
        # Find matching details
        for r in raw_intel:
            if r.get("source_url") == url:
                title = r.get("title", url)
                date = r.get("published_date", "")
                break
        date_str = f" — {date}" if date else ""
        sources_md += f"{i}. [{title}]({url}){date_str}\n"

    final_report = annotated_brief + sources_md

    # Write report to disk
    slug = state["topic"][:50].lower().replace(" ", "-").replace("/", "-")
    date_slug = datetime.date.today().isoformat()
    output_path = Config.OUTPUT_DIR / f"{slug}-{date_slug}.md"

    header = (
        f"# Intelligence Brief: {state['topic']}\n"
        f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Run ID:** `{state['run_id']}`  \n"
        f"**Sources indexed:** {len(seen_urls)}  \n"
        f"**Iterations:** {state.get('iterations', 0)}  \n\n---\n\n"
    )

    try:
        output_path.write_text(header + final_report, encoding="utf-8")
        print(f"   Final Brief written → {output_path}")
    except Exception as e:
        print(f"   Failed to save final brief to disk: {e}")

    return {"final_report": header + final_report}
