import json
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agent.state import AgentState, BiasEntry
from src.tools.llm import safe_llm_invoke
from src.agent.prompts import BIAS_CLASSIFICATION_USER

# Load bias ratings table once on startup
_BIAS_TABLE: Dict[str, dict] = {}

def _load_bias_table():
    global _BIAS_TABLE
    # Look for table at root data/ bias_ratings.json
    table_path = Path("data/bias_ratings.json")
    if table_path.exists():
        try:
            with open(table_path) as f:
                _BIAS_TABLE = json.load(f)
            print(f"  [CrossExaminer] Loaded {len(_BIAS_TABLE)} entries from bias_ratings.json")
        except Exception as e:
            print(f"  [CrossExaminer] Failed to load bias_ratings.json: {e}")
    else:
        print("  [CrossExaminer] data/bias_ratings.json not found — LLM will classify all domains")

_load_bias_table()


def classify_domain(domain: str) -> dict:
    """
    Returns bias classification for a domain.
    Checks static table first, falls back to safe LLM invoke if unknown.
    """
    key = domain.replace("www.", "")
    if key in _BIAS_TABLE:
        entry = _BIAS_TABLE[key]
        return {
            "lean": entry.get("lean", "unknown"),
            "reliability": entry.get("reliability", "unknown"),
            "method": "static-table",
            "notes": entry.get("notes", "")
        }

    # Fall back to safe LLM invoke
    prompt = BIAS_CLASSIFICATION_USER.format(domain=domain)
    try:
        res = safe_llm_invoke([HumanMessage(content=prompt)])
        raw = res.content.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(raw)
        return {
            "lean": parsed.get("lean", "unknown"),
            "reliability": parsed.get("reliability", "unknown"),
            "method": "llm",
            "notes": parsed.get("notes", "")
        }
    except Exception:
        return {
            "lean": "unknown",
            "reliability": "unknown",
            "method": "llm-failed",
            "notes": ""
        }


def cross_examiner_node(state: AgentState) -> Dict:
    print(f"\n  [CrossExaminer] Tagging {len(state['raw_intel'])} intel records...")

    seen_domains = {e["domain"] for e in state.get("bias_matrix", [])}
    unique_domains = set()

    for record in state["raw_intel"]:
        url = record.get("source_url", "")
        if not url:
            continue
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = url
        if domain not in seen_domains:
            unique_domains.add(domain)

    if not unique_domains:
        return {"bias_matrix": []}

    new_bias_entries: List[BiasEntry] = []
    unknown_domains = []

    # 1. Resolve from static table first
    for domain in unique_domains:
        key = domain.replace("www.", "")
        if key in _BIAS_TABLE:
            entry = _BIAS_TABLE[key]
            new_bias_entries.append(BiasEntry(
                domain=domain,
                lean=entry.get("lean", "unknown"),
                reliability=entry.get("reliability", "unknown"),
                method="static-table",
                model_disagreement=False,
                notes=entry.get("notes", ""),
            ))
            print(f"  {domain:35s} → {entry.get('lean', 'unknown'):25s} [static-table]")
        else:
            unknown_domains.append(domain)

    # 2. Batch-classify remaining unknown domains in a single LLM call
    if unknown_domains:
        print(f"  [CrossExaminer] Batch classifying {len(unknown_domains)} domains via LLM...")
        batch_prompt = (
            "Classify the political bias lean (e.g., left, left-center, centrist, right-center, right, unknown) "
            "and factual reliability (e.g., high, mixed, low, unknown) for the following news and information domains.\n"
            "Return a JSON array containing objects with keys: 'domain', 'lean', 'reliability', and 'notes'.\n"
            "Do not return markdown code blocks or formatting. Return raw JSON text only.\n\n"
            f"Domains to classify:\n" + "\n".join(f"- {d}" for d in unknown_domains)
        )
        
        try:
            res = safe_llm_invoke([HumanMessage(content=batch_prompt)])
            raw = res.content.strip().replace("```json", "").replace("```", "")
            classifications = json.loads(raw)
            if not isinstance(classifications, list):
                classifications = []
            
            for item in classifications:
                domain = item.get("domain", "")
                if not domain:
                    continue
                entry = BiasEntry(
                    domain=domain,
                    lean=item.get("lean", "unknown"),
                    reliability=item.get("reliability", "unknown"),
                    method="llm-batch",
                    model_disagreement=False,
                    notes=item.get("notes", ""),
                )
                new_bias_entries.append(entry)
                print(f"  {domain:35s} → {entry['lean']:25s} [llm-batch]")
                
                # Remove from unknown list so we don't treat them as failed
                if domain in unknown_domains:
                    unknown_domains.remove(domain)
        except Exception as e:
            print(f"  ❌ [CrossExaminer] Batch LLM classification failed: {e}")

        # Fallback for any domains that the LLM failed to return or parse
        for domain in unknown_domains:
            entry = BiasEntry(
                domain=domain,
                lean="unknown",
                reliability="unknown",
                method="llm-batch-failed",
                model_disagreement=False,
                notes="Batch classification failed",
            )
            new_bias_entries.append(entry)

    return {"bias_matrix": new_bias_entries}
