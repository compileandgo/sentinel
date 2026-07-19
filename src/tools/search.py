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


def search(query: str, subagent_id: str = "lead", max_results: int = 3, enable_rss: bool = True) -> List[RawIntel]:
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
        results = _tavily_search(query, subagent_id, max_results)
    else:
        results = _duckduckgo_search(query, subagent_id, max_results)

    if Config.ENABLE_RSS_FEEDS and enable_rss:
        print(f"   [Search] RSS feed supplement enabled. Fetching wire-service feeds...")
        rss_results = _fetch_rss_feeds(query, subagent_id, max_results=2)
        print(f"     → Supplemented search results with {len(rss_results)} RSS items.")
        results.extend(rss_results)

    return results


def _fetch_rss_feeds(query: str, subagent_id: str, max_results: int = 2) -> List[RawIntel]:
    import requests
    import urllib.parse
    import xml.etree.ElementTree as ET
    import re
    from src.agent.state import RawIntel

    results = []
    
    # 1. Try Google News RSS search query restricted to major wire sites (Reuters, AP, Bloomberg)
    google_news_rss = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}+site:reuters.com+OR+site:apnews.com+OR+site:bloomberg.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        resp = requests.get(google_news_rss, headers=headers, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            for item in items:
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                pub_date_el = item.find("pubDate")
                
                title = title_el.text if title_el is not None else ""
                link = link_el.text if link_el is not None else ""
                desc = desc_el.text if desc_el is not None else ""
                pub_date = pub_date_el.text if pub_date_el is not None else ""
                
                # Clean description of HTML tags
                desc_clean = re.sub(r'<[^>]*>', '', desc) if desc else ""
                if not desc_clean:
                    desc_clean = title
                
                results.append(RawIntel(
                    source_url=link,
                    title=title,
                    snippet=desc_clean,
                    published_date=pub_date,
                    query=query,
                    subagent_id=subagent_id,
                ))
                if len(results) >= max_results:
                    break
    except Exception as e:
        print(f"  [RSS] Google News search feed failed: {e}")

    # 2. Fallback to generic Top News feeds and filter by query keywords if search returns nothing
    if not results:
        fallback_feeds = [
            "http://feeds.bbci.co.uk/news/rss.xml",
            "https://apnews.com/feed/"
        ]
        
        keywords = [kw.lower() for kw in query.split() if len(kw) > 3]
        
        for feed in fallback_feeds:
            try:
                resp = requests.get(feed, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                for item in items:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")
                    pub_date_el = item.find("pubDate")
                    
                    title = title_el.text if title_el is not None else ""
                    link = link_el.text if link_el is not None else ""
                    desc = desc_el.text if desc_el is not None else ""
                    pub_date = pub_date_el.text if pub_date_el is not None else ""
                    
                    # Filter by keywords if keywords exist
                    if keywords:
                        search_text = f"{title} {desc}".lower()
                        if not any(kw in search_text for kw in keywords):
                            continue
                            
                    desc_clean = re.sub(r'<[^>]*>', '', desc) if desc else ""
                    if not desc_clean:
                        desc_clean = title
                        
                    results.append(RawIntel(
                        source_url=link,
                        title=title,
                        snippet=desc_clean,
                        published_date=pub_date,
                        query=query,
                        subagent_id=subagent_id,
                    ))
                    if len(results) >= max_results:
                        break
            except Exception as e:
                print(f"  [RSS] Fallback feed {feed} failed: {e}")
            if len(results) >= max_results:
                break
                
    return results


def gdelt_search(query: str, max_results: int = 10) -> List[dict]:
    """
    Search GDELT Doc 2.0 API. Returns list of articles/events.
    """
    import requests
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max_results
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("articles", [])
        else:
            print(f"  [GDELT] API returned status code {resp.status_code}")
    except Exception as e:
        print(f"  [GDELT] API request failed: {e}")
    return []
