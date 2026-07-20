import re
import datetime
import time
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
    parts = re.split(r'\n##\s+', synthesis)

    if len(parts) > 1:
        # Parallel sectional citation alignment
        from concurrent.futures import ThreadPoolExecutor

        def _align_section_citations(section_index: int, title: str, body: str) -> str:
            print(f"  [CitationAgent] Aligning section {section_index} ({title[:40]}...)...")
            prompt = CITATION_USER.format(
                sources_list=sources_list_str,
                synthesis=body
            )
            try:
                res = safe_llm_invoke([
                    SystemMessage(content=CITATION_SYSTEM),
                    HumanMessage(content=prompt),
                ], temperature=0.1)
                return res.content
            except Exception as e:
                print(f"  ⚠️ [CitationAgent] Section {section_index} alignment failed: {e}")
                return body

        futures = []
        with ThreadPoolExecutor(max_workers=min(len(parts) - 1, 8)) as executor:
            for idx, part in enumerate(parts[1:], 1):
                lines = part.split('\n', 1)
                title = lines[0].strip()
                body = lines[1] if len(lines) > 1 else ""
                
                future = executor.submit(_align_section_citations, idx, title, body)
                futures.append((title, future))

        annotated_parts = [parts[0]]
        for title, future in futures:
            annotated_body = future.result()
            annotated_parts.append(f"\n## {title}\n{annotated_body}")
        
        annotated_brief = "".join(annotated_parts)
    else:
        # Fallback to monolithic alignment if no sections found
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

    # Build the final markdown references section in research paper format
    sources_md = "\n\n## References\n"
    for i, url in enumerate(seen_urls, 1):
        title = url
        date = ""
        # Find matching details
        for r in raw_intel:
            if r.get("source_url") == url:
                title = r.get("title", url)
                date = r.get("published_date", "")
                break
        date_str = f" ({date})." if date else "."
        sources_md += f"{i}. {title}. URL: [{url}]({url}){date_str}\n"

    # Clean [UNCITED] tags and normalize spacing for final output
    clean_brief = annotated_brief.replace("[UNCITED]", "")
    clean_brief = re.sub(r'\s+([.,!?])', r'\1', clean_brief)
    clean_brief = re.sub(r' {2,}', ' ', clean_brief)

    final_report = clean_brief + sources_md

    # Write report to disk
    slug = state["topic"][:50].lower().replace(" ", "-").replace("/", "-")
    date_slug = datetime.date.today().isoformat()
    output_path = Config.OUTPUT_DIR / f"{slug}-{date_slug}.md"

    uncited_count = annotated_brief.count("[UNCITED]")
    total_sentences = len(sentences)
    uncited_ratio = uncited_count / max(total_sentences, 1)

    start_time = state.get("start_time")
    if start_time:
        duration = time.time() - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
    else:
        duration_str = "unknown"

    header = (
        f"# Research Paper: {state['topic']}\n"
        f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"**Time taken:** {duration_str}  \n"
        f"**Sources indexed:** {len(seen_urls)}  \n"
        f"**Iterations:** {state.get('iterations', 0)}  \n"
        f"**Uncited sentences:** {uncited_count} / {total_sentences} ({uncited_ratio:.1%})  \n\n---\n\n"
    )

    return_data = {
        "final_report": header + final_report,
        "uncited_ratio": uncited_ratio
    }

    if uncited_ratio > 0.25:
        print(f"  ⚠️ [CitationAgent] WARNING: High uncited ratio detected: {uncited_ratio:.1%} ({uncited_count} out of {total_sentences} sentences).")
        current_iter = state.get("iterations", 0)
        if current_iter < Config.MAX_RESEARCH_ITERATIONS:
            # Trigger dynamic re-research by setting status to continue and listing top unresolved uncited claims as backlog
            from src.agent.state import EvalResult
            print(f"  [CitationAgent] Re-research trigger: setting eval_result status='continue' with {len(uncited_claims)} claims to verify.")
            # Map claims to specific prompt queries or instructions for the subagent
            unresolved = [f"Find credible sources and facts verifying: {claim}" for claim in uncited_claims[:3]]
            eval_res = EvalResult(
                status="continue",
                confidence=0.5,
                unresolved_questions=unresolved,
                reasoning=f"High uncited claims ratio ({uncited_ratio:.1%}). Verified sources needed."
            )
            return_data["eval_result"] = eval_res
    else:
        print(f"  [CitationAgent] Report groundness check: {uncited_ratio:.1%} uncited sentences ({uncited_count} out of {total_sentences}).")

    try:
        output_path.write_text(header + final_report, encoding="utf-8")
        print(f"   Final Brief written → {output_path}")
    except Exception as e:
        print(f"   Failed to save final brief to disk: {e}")

    return return_data
