import json
from pathlib import Path
from typing import Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import Config
from src.agent.state import AgentState, SubagentTask
from src.tools.llm import safe_llm_invoke       
from src.agent.prompts import (
    LEAD_RESEARCHER_SYSTEM,
    LEAD_RESEARCHER_PLAN_USER,
    LEAD_RESEARCHER_REPLAN_USER,
)

def write_plan(run_id: str, topic: str, backlog: List[str]) -> str:
    """Persists the LeadResearcher's plan to disk for reference."""
    plan_dir = Config.SUBAGENT_DIR / run_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = str(plan_dir / "plan.md")
    content = f"# Sentinel Research Plan\n\n**Topic:** {topic}\n\n## Research Backlog\n"
    for i, q in enumerate(backlog, 1):
        content += f"{i}. {q}\n"
    Path(plan_path).write_text(content, encoding="utf-8")
    return plan_path


def classify_topic_domain(topic: str) -> str:
    """
    Classifies the topic into one of: 'GEOPOLITICAL', 'ECONOMIC', 'SCIENTIFIC'.
    Uses local keyword matching, fallback to LLM.
    """
    topic_lower = topic.lower()
    
    # Keyword signals
    geopolitical_signals = [
        "sanction", "policy", "election", "crisis", "geopolitical", "geopolitics", 
        "nato", "military conflict", "export control", "treaty", "accord", "protest", 
        "minister", "government", "war", "tariff", "trade war", "diplomatic", "bilateral"
    ]
    economic_signals = [
        "economic", "finance", "market", "trade", "currency", "inflation", "tariff",
        "export", "import", "gdp", "growth rate", "invest", "fiscal", "supply chain", "pricing"
    ]
    scientific_signals = [
        "agentic", "neural network", "machine learning", "deep learning", "llm", 
        "software architecture", "algorithm", "ancient history", "dynasty", 
        "empirical study", "methodology", "framework", "tutorial", "how-to",
        "scientific", "physics", "chemistry", "biology", "space", "quantum", "cancer"
    ]
    
    if any(sig in topic_lower for sig in geopolitical_signals):
        print(f"  [LeadResearcher] Geopolitical keyword detected: domain set to GEOPOLITICAL.")
        return "GEOPOLITICAL"
    if any(sig in topic_lower for sig in economic_signals):
        print(f"  [LeadResearcher] Economic keyword detected: domain set to ECONOMIC.")
        return "ECONOMIC"
    if any(sig in topic_lower for sig in scientific_signals):
        print(f"  [LeadResearcher] Tech/Academic keyword detected: domain set to SCIENTIFIC.")
        return "SCIENTIFIC"
        
    # Fallback to LLM classification
    prompt = (
        "Classify the following research topic into one of three domains:\n"
        "1. 'GEOPOLITICAL' (if it concerns government, policy, international relations, military, treaties, or conflicts)\n"
        "2. 'ECONOMIC' (if it concerns market data, trade volumes, finance, investments, growth, or fiscal policies)\n"
        "3. 'SCIENTIFIC' (if it concerns science, engineering, technology, academic studies, history, or algorithms)\n\n"
        f"Topic: {topic}\n\n"
        "Respond with ONLY one word: either GEOPOLITICAL, ECONOMIC, or SCIENTIFIC. Do not include any other text."
    )
    try:
        res = safe_llm_invoke([HumanMessage(content=prompt)], temperature=0.0)
        ans = res.content.strip().upper()
        if "GEOPOLITICAL" in ans:
            print(f"  [LeadResearcher] LLM classified topic as GEOPOLITICAL.")
            return "GEOPOLITICAL"
        elif "ECONOMIC" in ans:
            print(f"  [LeadResearcher] LLM classified topic as ECONOMIC.")
            return "ECONOMIC"
        else:
            print(f"  [LeadResearcher] LLM classified topic as SCIENTIFIC.")
            return "SCIENTIFIC"
    except Exception as e:
        print(f"  [LeadResearcher] Topic classification LLM call failed ({e}). Defaulting to GEOPOLITICAL.")
        return "GEOPOLITICAL"


def lead_researcher_node(state: AgentState) -> Dict:
    topic = state["topic"]
    run_id = state["run_id"]
    current_iter = state.get("iterations", 0) + 1
    print(f"\n [LeadResearcher] Iteration {current_iter}/{Config.MAX_RESEARCH_ITERATIONS}")

    subagent_tasks: List[SubagentTask] = []
    backlog = state.get("research_backlog", [])
    plan_path = state.get("plan_path", "")

    # Define recommended angles mapping for each domain
    domain_angles = {
        "GEOPOLITICAL": "actors, timeline, sanctions, responses",
        "ECONOMIC": "market data, policy, forecasts, risks",
        "SCIENTIFIC": "methodology, findings, limitations, applications"
    }

    # --- Iteration 1: Plan and decompose topic ---
    if current_iter == 1:
        domain = classify_topic_domain(topic)
        is_news = (domain in ["GEOPOLITICAL", "ECONOMIC"])
        recommended_angles = domain_angles.get(domain, "timeline, key aspects, implications")
        
        print(f"  Planning research angles for: {topic} in domain: {domain}")
        prompt = LEAD_RESEARCHER_PLAN_USER.format(
            max_subagents=Config.MAX_SUBAGENTS,
            topic=topic,
            domain=domain,
            recommended_angles=recommended_angles
        )
        try:
            res = safe_llm_invoke([
                SystemMessage(content=LEAD_RESEARCHER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            raw = res.content.strip().replace("```json", "").replace("```", "")
            tasks_data = json.loads(raw)
            if not isinstance(tasks_data, list):
                raise ValueError("Response is not a JSON list")
        except Exception as e:
            print(f"  Failed to parse planner LLM output: {e} — falling back to static tasks")
            # Fallback static task decomposition
            if domain == "GEOPOLITICAL":
                tasks_data = [
                    {"subagent_id": "timeline", "task": f"Analyze chronological developments and key events of {topic}."},
                    {"subagent_id": "actors", "task": f"Identify key national/international actor positions and official statements on {topic}."},
                    {"subagent_id": "implications", "task": f"Examine geopolitical implications and future trends of {topic}."}
                ]
            elif domain == "ECONOMIC":
                tasks_data = [
                    {"subagent_id": "market_data", "task": f"Compile market size, economic volumes, and financial data of {topic}."},
                    {"subagent_id": "policy_risks", "task": f"Examine regulatory frameworks, policies, and systemic risks of {topic}."},
                    {"subagent_id": "forecasts", "task": f"Analyze market growth projections, forecasts, and opportunities of {topic}."}
                ]
            else:
                tasks_data = [
                    {"subagent_id": "methodology", "task": f"Review methodology, design, and experimental protocols of {topic}."},
                    {"subagent_id": "findings", "task": f"Synthesize primary research findings, breakthrough achievements, and results of {topic}."},
                    {"subagent_id": "limitations", "task": f"Investigate structural limitations, criticism, and unresolved research gaps of {topic}."}
                ]

        # Limit to max subagents
        tasks_data = tasks_data[:Config.MAX_SUBAGENTS]
        backlog = [t["task"] for t in tasks_data]
        plan_path = write_plan(run_id, topic, backlog)
        print(f"  Plan saved → {plan_path}")

        for t in tasks_data:
            subagent_id = t["subagent_id"]
            output_path = str(Config.SUBAGENT_DIR / run_id / f"{subagent_id}.md")
            subagent_tasks.append(SubagentTask(
                subagent_id=subagent_id,
                topic=topic,
                task=t["task"],
                output_path=output_path,
                enable_rss=is_news
            ))
            print(f"    - Spawn task: [{subagent_id}] {str(t['task'])[:60]}...")

    # --- Iteration > 1: Review feedback and refine ---
    else:
        is_news = state.get("is_news_topic", True)
        # Refine backlog with evaluator feedback
        eval_result = state.get("eval_result")
        unresolved_questions = []
        if eval_result and eval_result.get("unresolved_questions"):
            unresolved_questions = eval_result["unresolved_questions"]
            for uq in unresolved_questions:
                if uq not in backlog:
                    backlog.append(uq)
            print(f"  Backlog updated with {len(unresolved_questions)} unresolved questions")

        # Read subagent report summaries from previous iterations
        summaries = []
        for path_str in state.get("subagent_artifacts", []):
            p = Path(path_str)
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8")
                    summaries.append(f"[{p.name}]:\n{content[:500]}...\n---")
                except Exception as e:
                    print(f"  Error reading artifact {p.name}: {e}")

        summaries_str = "\n".join(summaries) if summaries else "No reports generated yet."
        backlog_str = "\n".join(f"- {q}" for q in backlog)

        prompt = LEAD_RESEARCHER_REPLAN_USER.format(
            topic=topic,
            backlog=backlog_str,
            summaries=summaries_str,
            max_subagents=Config.MAX_SUBAGENTS
        )

        try:
            res = safe_llm_invoke([
                SystemMessage(content=LEAD_RESEARCHER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            raw = res.content.strip().replace("```json", "").replace("```", "")
            tasks_data = json.loads(raw)
            if not isinstance(tasks_data, list):
                raise ValueError("Response is not a JSON list")
        except Exception as e:
            print(f"  Failed to parse replanning LLM output: {e} — falling back to unresolved questions")
            tasks_data = [{"subagent_id": f"refine_{i}", "task": q} for i, q in enumerate(unresolved_questions)]

        tasks_data = tasks_data[:Config.MAX_SUBAGENTS]
        for t in tasks_data:
            subagent_id = t["subagent_id"]
            output_path = str(Config.SUBAGENT_DIR / run_id / f"{subagent_id}.md")
            subagent_tasks.append(SubagentTask(
                subagent_id=subagent_id,
                topic=topic,
                task=t["task"],
                output_path=output_path,
                enable_rss=is_news
            ))
            print(f"    - Refined task: [{subagent_id}] {str(t['task'])[:60]}...")

    return {
        "iterations": current_iter,
        "research_backlog": backlog,
        "plan_path": plan_path,
        "subagent_tasks": subagent_tasks,
        "is_news_topic": is_news,
    }
