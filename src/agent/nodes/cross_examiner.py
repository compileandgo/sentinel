import json
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List
from langchain_core.messages import HumanMessage
from src.agent.state import AgentState, BiasEntry
from src.tools.llm import safe_llm_invoke, safe_gemini_invoke, safe_groq_invoke
from src.agent.prompts import BIAS_CLASSIFICATION_USER
from src.config import Config

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

    # 2. Batch-classify remaining unknown domains
    if unknown_domains:
        batch_prompt = (
            "Classify the political bias lean (e.g., left, left-center, centrist, right-center, right, unknown) "
            "and factual reliability (e.g., high, mixed, low, unknown) for the following news and information domains.\n"
            "Return a JSON array containing objects with keys: 'domain', 'lean', 'reliability', and 'notes'.\n"
            "Do not return markdown code blocks or formatting. Return raw JSON text only.\n\n"
            f"Domains to classify:\n" + "\n".join(f"- {d}" for d in unknown_domains)
        )

        gemini_dict = {}
        groq_dict = {}
        
        # Determine whether we do cross-model check
        do_cross_model = Config.ENABLE_CROSS_MODEL_BIAS and bool(Config.GROQ_API_KEYS)

        if do_cross_model:
            print(f"  [CrossExaminer] Cross-model bias check enabled. Querying both Gemini and Groq...")
            # Query Gemini
            try:
                res_gemini = safe_gemini_invoke([HumanMessage(content=batch_prompt)])
                raw_gemini = res_gemini.content.strip().replace("```json", "").replace("```", "")
                parsed_gemini = json.loads(raw_gemini)
                if isinstance(parsed_gemini, list):
                    for item in parsed_gemini:
                        dom = item.get("domain", "")
                        if dom:
                            gemini_dict[dom] = item
            except Exception as e:
                print(f"  ⚠️ [CrossExaminer] Gemini classification failed: {e}")

            # Query Groq
            try:
                res_groq = safe_groq_invoke([HumanMessage(content=batch_prompt)])
                raw_groq = res_groq.content.strip().replace("```json", "").replace("```", "")
                parsed_groq = json.loads(raw_groq)
                if isinstance(parsed_groq, list):
                    for item in parsed_groq:
                        dom = item.get("domain", "")
                        if dom:
                            groq_dict[dom] = item
            except Exception as e:
                print(f"  ⚠️ [CrossExaminer] Groq classification failed: {e}")
        else:
            # Standard single-model fallback call
            print(f"  [CrossExaminer] Batch classifying {len(unknown_domains)} domains via standard LLM...")
            try:
                res = safe_llm_invoke([HumanMessage(content=batch_prompt)])
                raw = res.content.strip().replace("```json", "").replace("```", "")
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        dom = item.get("domain", "")
                        if dom:
                            gemini_dict[dom] = item
            except Exception as e:
                print(f"  ❌ [CrossExaminer] Batch LLM classification failed: {e}")

        # Now merge results and build BiasEntry
        for domain in list(unknown_domains):
            gemini_item = gemini_dict.get(domain)
            groq_item = groq_dict.get(domain)

            if gemini_item and groq_item:
                # Both succeeded: compare and cross-examine
                g_lean = gemini_item.get("lean", "unknown").strip().lower()
                q_lean = groq_item.get("lean", "unknown").strip().lower()
                g_rel = gemini_item.get("reliability", "unknown").strip().lower()
                q_rel = groq_item.get("reliability", "unknown").strip().lower()

                # Basic disagreement check
                lean_disagree = (g_lean != q_lean) and (g_lean != "unknown") and (q_lean != "unknown")
                rel_disagree = (g_rel != q_rel) and (g_rel != "unknown") and (q_rel != "unknown")
                disagreement = lean_disagree or rel_disagree

                notes = f"Gemini: {gemini_item.get('notes', '').strip()} | Groq: {groq_item.get('notes', '').strip()}"
                
                # If there's disagreement, report both; otherwise use Gemini's values
                lean = gemini_item.get("lean", "unknown")
                reliability = gemini_item.get("reliability", "unknown")
                if disagreement:
                    notes += f" [Disagreement: Gemini={gemini_item.get('lean')}/{gemini_item.get('reliability')}, Groq={groq_item.get('lean')}/{groq_item.get('reliability')}]"

                entry = BiasEntry(
                    domain=domain,
                    lean=lean,
                    reliability=reliability,
                    method="llm-dual-model",
                    model_disagreement=disagreement,
                    notes=notes,
                )
                new_bias_entries.append(entry)
                print(f"  {domain:35s} → {entry['lean']:25s} [llm-dual-model] (disagreement={disagreement})")
                unknown_domains.remove(domain)

            elif gemini_item or groq_item:
                # Only one succeeded
                item = gemini_item or groq_item
                method_name = "llm-gemini-only" if gemini_item else "llm-groq-only"
                entry = BiasEntry(
                    domain=domain,
                    lean=item.get("lean", "unknown"),
                    reliability=item.get("reliability", "unknown"),
                    method=method_name,
                    model_disagreement=False,
                    notes=item.get("notes", ""),
                )
                new_bias_entries.append(entry)
                print(f"  {domain:35s} → {entry['lean']:25s} [{method_name}]")
                unknown_domains.remove(domain)

        # Fallback for any domains that completely failed
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
