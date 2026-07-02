from langgraph.graph import StateGraph, END
from langgraph.constants import Send
from src.agent.state import AgentState
from src.agent.nodes.lead_researcher import lead_researcher_node
from src.agent.nodes.subagent import subagent_node
from src.agent.nodes.cross_examiner import cross_examiner_node
from src.agent.nodes.timeline_compiler import timeline_compiler_node
from src.agent.nodes.sufficiency_evaluator import sufficiency_evaluator_node
from src.agent.nodes.synthesis import synthesis_node
from src.agent.nodes.citation_agent import citation_agent_node

def route_to_subagents(state: AgentState):
    """
    Conditional edge router for parallel subagent dispatch.
    Returns a list of Send operations or routes straight to cross_examiner
    if no subagent tasks exist.
    """
    tasks = state.get("subagent_tasks", [])
    if not tasks:
        print("   [Routing] No subagent tasks generated! Bypassing to CrossExaminer.")
        return "cross_examiner"
    
    # Return list of Send operations (each targets 'subagent' node with a single task spec)
    return [Send("subagent", task) for task in tasks]


def route_after_eval(state: AgentState) -> str:
    """
    Conditional edge router from sufficiency evaluator.
    Returns 'lead_researcher' to continue or 'synthesis' to build the brief.
    """
    eval_res = state.get("eval_result")
    if eval_res and eval_res.get("status") == "continue":
        return "lead_researcher"
    return "synthesis"


def build_graph():
    builder = StateGraph(AgentState)

    # Add all Sentinel nodes
    builder.add_node("lead_researcher", lead_researcher_node)
    builder.add_node("subagent", subagent_node)
    builder.add_node("cross_examiner", cross_examiner_node)
    builder.add_node("timeline_compiler", timeline_compiler_node)
    builder.add_node("sufficiency_evaluator", sufficiency_evaluator_node)
    builder.add_node("synthesis", synthesis_node)
    builder.add_node("citation_agent", citation_agent_node)

    # Entry point is lead_researcher
    builder.set_entry_point("lead_researcher")

    # Map phase: Route dynamically from LeadResearcher to Subagents or fallback
    builder.add_conditional_edges(
        "lead_researcher",
        route_to_subagents,
        {
            "subagent": "subagent",
            "cross_examiner": "cross_examiner"
        }
    )

    # Reduce phase: Subagents fan-in — both analysis nodes run in parallel
    # cross_examiner and timeline_compiler both only read raw_intel → safe to parallelize
    builder.add_edge("subagent", "cross_examiner")
    builder.add_edge("subagent", "timeline_compiler")

    # Both analysis nodes converge at sufficiency_evaluator
    builder.add_edge("cross_examiner", "sufficiency_evaluator")
    builder.add_edge("timeline_compiler", "sufficiency_evaluator")

    # Loop checking: Continue research or finalize synthesis
    builder.add_conditional_edges(
        "sufficiency_evaluator",
        route_after_eval,
        {
            "lead_researcher": "lead_researcher",
            "synthesis": "synthesis"
        }
    )

    # Brief formulation and citation generation
    builder.add_edge("synthesis", "citation_agent")
    builder.add_edge("citation_agent", END)

    return builder.compile()
