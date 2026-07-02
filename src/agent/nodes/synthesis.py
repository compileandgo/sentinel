from typing import Dict
from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.state import AgentState
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import SYNTHESIS_SYSTEM, SYNTHESIS_USER

def synthesis_node(state: AgentState) -> Dict:
    print(f"\n [SynthesisEngine] Compiling intelligence brief...")

    # Build structured contexts
    timeline_md = "\n".join(
        f"- **{e['date']}** — {e['event']}"
        f"{'  CONFLICT' if e['conflict_flag'] else ''}"
        f" [{e['confidence']} confidence]"
        for e in sorted(state.get("chronology", []), key=lambda x: x["date"])
    ) or "No dated events extracted."

    bias_md = "\n".join(
        f"- `{e['domain']}` → {e['lean']} | reliability: {e['reliability']}"
        f"{' |  MODEL DISAGREEMENT' if e['model_disagreement'] else ''}"
        for e in state.get("bias_matrix", [])
    ) or "No bias classifications available."

    intel_items = state.get("raw_intel", [])[:20]
    intel_md = "\n\n".join(
        f"**[{r.get('published_date','?')}] {r.get('title','Untitled')}**\n"
        f"{r.get('snippet','')[:800]}\n"
        f"Source: {r.get('source_url','')}"
        for r in intel_items
    ) or "No intel records."

    prompt = SYNTHESIS_USER.format(
        topic=state["topic"],
        timeline_md=timeline_md,
        bias_md=bias_md,
        intel_md=intel_md
    )

    res = safe_llm_invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM),
        HumanMessage(content=prompt),
    ])

    print(f"  Synthesis complete ({len(res.content)} chars)")
    return {"synthesis": res.content}
