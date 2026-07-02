import json
from typing import Dict
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import Config
from src.agent.state import AgentState, EvalResult
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import SUFFICIENCY_EVAL_USER

def sufficiency_evaluator_node(state: AgentState) -> Dict:
    print(f"\n [SufficiencyEvaluator] Checking research coverage...")

    current_iter = state.get("iterations", 0)
    # Hard cap — safety valve regardless of LLM decision
    if current_iter >= Config.MAX_RESEARCH_ITERATIONS:
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

    prompt = SUFFICIENCY_EVAL_USER.format(
        topic=state["topic"],
        backlog=backlog_str,
        intel_count=intel_count,
        chron_count=chron_count,
        bias_count=bias_count
    )

    try:
        res = safe_llm_invoke([
            SystemMessage(content="Return only valid JSON. No markdown fences."),
            HumanMessage(content=prompt),
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

    print(f"  Status: {result['status'].upper()} | Confidence: {result['confidence']:.0%} | {result['reasoning']}")
    return {"eval_result": result}
