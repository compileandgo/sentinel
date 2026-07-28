import requests
import json
from typing import List, Dict, Any
from src.agent.state import RawIntel

# Custom User-Agent header for public API compliance (e.g., SEC EDGAR, OpenAlex)
HEADERS = {
    "User-Agent": "SentinelGeopoliticalIntelligence/1.0 (https://sentinel.org; contact@sentinel.org)"
}

def query_wikidata(query: str, subagent_id: str = "lead", max_results: int = 3) -> List[RawIntel]:
    """Query Wikidata REST API for entity facts, history, and cross-domain knowledge (No API key required)."""
    try:
        url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={requests.utils.quote(query)}&language=en&format=json&limit={max_results}"
        res = requests.get(url, headers=HEADERS, timeout=6)
        if res.status_code != 200:
            return []
        data = res.json()
        results = []
        for item in data.get("search", []):
            label = item.get("label", "")
            description = item.get("description", "Wikidata entity entry")
            concept_id = item.get("id", "")
            item_url = item.get("concepturi", f"https://www.wikidata.org/wiki/{concept_id}")
            
            snippet = f"Entity: {label} ({concept_id}). Description: {description}."
            results.append(RawIntel(
                source_url=item_url,
                title=f"Wikidata: {label}",
                snippet=snippet,
                published_date="",
                query=query,
                subagent_id=subagent_id
            ))
        return results
    except Exception as e:
        print(f"  [Wikidata API Error]: {e}")
        return []

def query_openalex(query: str, subagent_id: str = "lead", max_results: int = 3) -> List[RawIntel]:
    """Query OpenAlex for academic literature, research works, and citations (No API key required)."""
    try:
        url = f"https://api.openalex.org/works?search={requests.utils.quote(query)}&per-page={max_results}"
        res = requests.get(url, headers=HEADERS, timeout=6)
        if res.status_code != 200:
            return []
        data = res.json()
        results = []
        for work in data.get("results", []):
            title = work.get("title", "Scholarly Work")
            pub_year = work.get("publication_year", "")
            work_url = work.get("doi") or work.get("id") or "https://openalex.org"
            cited_by = work.get("cited_by_count", 0)
            
            # Reconstruct abstract inverted index if available
            abstract = ""
            abs_dict = work.get("abstract_inverted_index")
            if abs_dict:
                words = []
                for word, positions in abs_dict.items():
                    for pos in positions:
                        words.append((pos, word))
                words.sort(key=lambda x: x[0])
                abstract = " ".join([w[1] for w in words[:100]])
                if len(words) > 100:
                    abstract += "..."

            snippet = f"Academic Paper ({pub_year}). Citations: {cited_by}. Abstract: {abstract if abstract else title}"
            results.append(RawIntel(
                source_url=work_url,
                title=f"OpenAlex: {title}",
                snippet=snippet,
                published_date=str(pub_year),
                query=query,
                subagent_id=subagent_id
            ))
        return results
    except Exception as e:
        print(f"  [OpenAlex API Error]: {e}")
        return []

def query_worldbank(query: str, subagent_id: str = "lead", max_results: int = 3) -> List[RawIntel]:
    """Query World Bank Indicators Open API for economic/demographic data (No API key required)."""
    try:
        # Search for indicators matching the query
        search_url = f"http://api.worldbank.org/v2/indicator?format=json&q={requests.utils.quote(query)}"
        res = requests.get(search_url, headers=HEADERS, timeout=6)
        if res.status_code != 200:
            return []
        data = res.json()
        if len(data) < 2 or not data[1]:
            return []
            
        indicators = data[1][:max_results]
        results = []
        for ind in indicators:
            ind_id = ind.get("id", "")
            ind_name = ind.get("name", "")
            source_note = ind.get("sourceNote", "")
            if len(source_note) > 220:
                source_note = source_note[:220] + "..."
            
            item_url = f"https://data.worldbank.org/indicator/{ind_id}"
            snippet = f"World Bank Indicator ({ind_id}): {ind_name}. Context: {source_note}"
            results.append(RawIntel(
                source_url=item_url,
                title=f"World Bank: {ind_name}",
                snippet=snippet,
                published_date="",
                query=query,
                subagent_id=subagent_id
            ))
        return results
    except Exception as e:
        print(f"  [World Bank API Error]: {e}")
        return []

def query_pubmed(query: str, subagent_id: str = "lead", max_results: int = 3) -> List[RawIntel]:
    """Query NCBI PubMed Entrez API for biomedical and scientific literature (No API key required)."""
    try:
        esearch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={requests.utils.quote(query)}&retmode=json&retmax={max_results}"
        res = requests.get(esearch_url, headers=HEADERS, timeout=6)
        if res.status_code != 200:
            return []
        data = res.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []
            
        ids_str = ",".join(id_list)
        esummary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={ids_str}&retmode=json"
        sum_res = requests.get(esummary_url, headers=HEADERS, timeout=6)
        if sum_res.status_code != 200:
            return []
            
        sum_data = sum_res.json().get("result", {})
        results = []
        for pmid in id_list:
            item = sum_data.get(pmid, {})
            title = item.get("title", "PubMed Article")
            pub_date = item.get("pubdate", "")
            source = item.get("source", "Biomedical Literature")
            item_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            
            results.append(RawIntel(
                source_url=item_url,
                title=f"PubMed: {title}",
                snippet=f"Journal: {source}. Published: {pub_date}. Title: {title}",
                published_date=pub_date,
                query=query,
                subagent_id=subagent_id
            ))
        return results
    except Exception as e:
        print(f"  [PubMed API Error]: {e}")
        return []

def query_all_open_databases(query: str, subagent_id: str = "lead", max_results: int = 2) -> List[RawIntel]:
    """
    Unified Open Data connector.
    Queries Wikidata, OpenAlex, World Bank, and PubMed concurrently without any API keys.
    """
    combined = []
    
    # 1. Wikidata
    try:
        wikidata_items = query_wikidata(query, subagent_id=subagent_id, max_results=max_results)
        combined.extend(wikidata_items)
    except Exception:
        pass

    # 2. OpenAlex (Academia & Papers)
    try:
        openalex_items = query_openalex(query, subagent_id=subagent_id, max_results=max_results)
        combined.extend(openalex_items)
    except Exception:
        pass

    # 3. World Bank (Economics & Metrics)
    try:
        wb_items = query_worldbank(query, subagent_id=subagent_id, max_results=max_results)
        combined.extend(wb_items)
    except Exception:
        pass

    # 4. PubMed (Biomedical/Scientific)
    try:
        pm_items = query_pubmed(query, subagent_id=subagent_id, max_results=max_results)
        combined.extend(pm_items)
    except Exception:
        pass

    return combined
