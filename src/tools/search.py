from typing import List
from urllib.parse import urlparse
from src.config import Config
from src.agent.state import RawIntel

def _tavily_search(query: str, subagent_id: str, max_results: int = 3) -> List[RawIntel]:
    """Call Tavily Search API. Returns typed RawIntel records."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=Config.TAVILY_API_KEY)
        resp = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_published_date=True,
        )
        results = []
        for r in resp.get("results", []):
            results.append(RawIntel(
                source_url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                published_date=r.get("published_date", ""),
                query=query,
                subagent_id=subagent_id,
            ))
        return results
    except Exception as e:
        print(f"  [Tavily] failed: {e} — falling back to DuckDuckGo")
        return _duckduckgo_search(query, subagent_id, max_results)


def _duckduckgo_search(query: str, subagent_id: str, max_results: int = 3) -> List[RawIntel]:
    """DuckDuckGo fallback. No API key required."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(RawIntel(
                    source_url=r.get("href", ""),
                    title=r.get("title", ""),
                    snippet=r.get("body", ""),
                    published_date="",
                    query=query,
                    subagent_id=subagent_id,
                ))
        return results
    except Exception as e:
        print(f"  [DuckDuckGo] also failed: {e}")
        return []


def search(query: str, subagent_id: str = "lead", max_results: int = 3) -> List[RawIntel]:
    """
    Primary search interface.
    Provider selection: SEARCH_PROVIDER env var. Auto-falls back on error.
    """
    from src.tools.llm import thread_local
    run_id = getattr(thread_local, "run_id", None)
    if run_id:
        try:
            from src.web.app import active_cancellations
            if run_id in active_cancellations:
                raise RuntimeError("Research cancelled by user")
        except ImportError:
            pass

    if Config.SEARCH_PROVIDER == "tavily" and Config.TAVILY_API_KEY:
        return _tavily_search(query, subagent_id, max_results)
    return _duckduckgo_search(query, subagent_id, max_results)
