import json
from typing import Dict, List
from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.state import AgentState, ChronEntry
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import TIMELINE_EXTRACT_USER

def timeline_compiler_node(state: AgentState) -> Dict:
    print(f"\n [TimelineCompiler] Extracting dated events...")

    snippets = []
    for record in state["raw_intel"]:
        if record.get("snippet"):
            snippets.append(f"[{record.get('published_date','?')}] {record['snippet'][:200]}")

    if not snippets:
        print("  No snippets to process.")
        return {"chronology": []}

    # Cap snippets to avoid token overflow
    snippets_text = "\n".join(snippets[:10])
    prompt = TIMELINE_EXTRACT_USER.format(topic=state["topic"], snippets=snippets_text)

    try:
        res = safe_llm_invoke([
            SystemMessage(content="Return only valid JSON array. No markdown fences."),
            HumanMessage(content=prompt),
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

        # Simple conflict detection: same date, different event description
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
