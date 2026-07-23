import os
import sys
import re
import json
from typing import Dict, Any, List

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.search import search
from src.tools.rag_search import rag_search
from src.agent.state import RawIntel

INTENT_SYSTEM_PROMPT = """You are an intent classifier for a smart intelligence assistant.
Your job is to determine whether answering the user's message requires searching external web news or local research reports (statistics, recent geopolitical/economic events, factual verification, public opinion, current affairs).

Rules:
1. "needs_search": true if the query asks about current events, news, statistics, public opinion, specific reports, recent geopolitical developments, or facts that cannot be confidently answered from static knowledge.
2. "needs_search": false if the query is a simple greeting ("hi", "hello"), general coding/math ("write a python function", "2+2"), creative writing, summarizing provided text, or follow-up conversational chat.

Respond ONLY with valid JSON in this exact structure:
{
    "needs_search": true,
    "search_query": "3 to 6 word search query optimized for vector and web search",
    "reasoning": "brief 1-line reason"
}"""

def evaluate_search_intent(query: str) -> Dict[str, Any]:
    """
    Evaluates whether a user's chat query requires web/RAG search.
    Uses fast heuristic rules first, falling back to a quick LLM check if ambiguous.
    """
    clean_q = query.strip().lower()
    
    # 1. Fast Heuristics: Greetings & Simple Conversational -> No Search
    greetings = {"hi", "hello", "hey", "thanks", "thank you", "who are you", "what is sentinel", "good morning", "good evening"}
    if clean_q in greetings or len(clean_q.split()) <= 2 and any(g in clean_q for g in greetings):
        return {
            "needs_search": False,
            "search_query": "",
            "reasoning": "Conversational greeting"
        }
        
    # Fast Heuristics: Explicit Search Keywords & Price/News/Facts Queries -> Force Search
    search_triggers = [
        "search for", "look up", "recent news", "pew research", "pew report",
        "latest statistics", "current status of", "what happened in", "who won",
        "public opinion on", "survey data", "latest trends", "price of", "cost of",
        "current price", "stock price", "crude oil", "bitcoin", "weather in",
        "rate of", "how much is", "what is the price", "today", "latest"
    ]
    if any(t in clean_q for t in search_triggers):
        clean_query = re.sub(r'^(search for|look up|find|get)\s+', '', query, flags=re.IGNORECASE)
        return {
            "needs_search": True,
            "search_query": clean_query.strip(),
            "reasoning": "Instant search trigger keyword detected"
        }
        
    # Fast Heuristics: Code/Math -> No Search
    if re.search(r'^(write|code|create|generate|fix|debug)\s+(a\s+)?(python|js|script|function|code|class|html|css|sql)', clean_q):
        return {
            "needs_search": False,
            "search_query": "",
            "reasoning": "Coding task"
        }
        
    # 2. LLM Intent Classifier for ambiguous queries
    try:
        from src.tools.llm import safe_llm_invoke
        from langchain_core.messages import SystemMessage, HumanMessage
        from src.config import Config

        res = safe_llm_invoke(
            [
                SystemMessage(content=INTENT_SYSTEM_PROMPT),
                HumanMessage(content=f"User Query: {query}")
            ],
            model=Config.SUBAGENT_MODEL,
            temperature=0.0
        )
        
        raw_text = res.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw_text)
        return {
            "needs_search": bool(data.get("needs_search", False)),
            "search_query": data.get("search_query", query).strip(),
            "reasoning": data.get("reasoning", "LLM evaluation")
        }
    except Exception as e:
        print(f"  [SmartSearch] Intent classification fallback: {e}")
        q_words = clean_q.split()
        is_question = len(q_words) >= 5 and any(w in clean_q for w in ["what", "why", "how", "who", "where", "when", "is", "are"])
        return {
            "needs_search": is_question,
            "search_query": query,
            "reasoning": "Fallback heuristic"
        }

def execute_smart_search(search_query: str, subagent_id: str = "chat") -> Dict[str, Any]:
    """
    Executes hybrid RAG vector search + live web search concurrently in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor
    print(f"  [SmartSearch] Executing parallel search for: '{search_query}'")
    
    rag_intel: List[RawIntel] = []
    web_intel: List[RawIntel] = []
    
    def _run_rag():
        try:
            return rag_search(search_query, subagent_id=subagent_id, max_results=2)
        except Exception as e:
            print(f"  [SmartSearch] RAG search error: {e}")
            return []
            
    def _run_web():
        try:
            return search(search_query, subagent_id=subagent_id, max_results=3, enable_rss=False)
        except Exception as e:
            print(f"  [SmartSearch] Web search error: {e}")
            return []
            
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_rag = executor.submit(_run_rag)
        f_web = executor.submit(_run_web)
        rag_intel = f_rag.result()
        web_intel = f_web.result()

    # 3. Combine & Deduplicate by URL
    combined_intel: List[RawIntel] = []
    seen_urls = set()
    
    for item in rag_intel + web_intel:
        url = item.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        combined_intel.append(item)
        
    if not combined_intel:
        return {
            "intel": [],
            "formatted_context": "",
            "sources": []
        }
        
    # 4. Format context block for LLM prompt
    context_lines = ["=== GROUNDED SEARCH FINDINGS & REPORTS ==="]
    sources = []
    
    for idx, item in enumerate(combined_intel, 1):
        title = item.get("title", "Untitled Source")
        url = item.get("source_url", "")
        snippet = item.get("full_text") or item.get("snippet", "")
        pub_date = item.get("published_date", "")
        
        content_preview = snippet[:1500] if snippet else ""
        
        context_lines.append(
            f"Source [{idx}]: {title}\n"
            f"URL: {url}\n"
            f"Date: {pub_date}\n"
            f"Content: {content_preview}\n"
            f"---"
        )
        sources.append({
            "index": idx,
            "title": title,
            "url": url,
            "published_date": pub_date
        })
        
    context_lines.append("=== END GROUNDED FINDINGS ===")
    formatted_context = "\n".join(context_lines)
    
    return {
        "intel": combined_intel,
        "formatted_context": formatted_context,
        "sources": sources
    }
