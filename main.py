import sys
import uuid
import datetime
import time
from src.agent.graph import build_graph

def main():
    # Use topic from CLI args if provided, otherwise use default test topic
    topic = ""
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])

    run_id = f"{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:6]}"

    print("=" * 60)
    print(f"   Starting Sentinel Research Agent")
    print(f"   Topic:  '{topic}'")
    print(f"   Run ID: {run_id}")
    print("=" * 60)

    # Compile the LangGraph state graph
    app = build_graph()

    initial_state = {
        "topic": topic,
        "run_id": run_id,
        "plan_path": "",
        "start_time": time.time(),
        "research_backlog": [],
        "subagent_artifacts": [],
        "subagent_tasks": [],
        "raw_intel": [],
        "bias_matrix": [],
        "chronology": [],
        "iterations": 0,
        "eval_result": None,
        "uncited_ratio": None,
        "synthesis": "",
        "final_report": "",
    }

    try:
        final_state = app.invoke(initial_state)
        print("\n" + "=" * 60)
        print("Sentinel Research completed successfully!")
        print(f"   Plan saved to: {final_state.get('plan_path')}")
        print("=" * 60)
    except Exception as e:
        import traceback
        print(f"\nResearch run failed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
