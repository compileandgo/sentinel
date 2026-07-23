import os
import sys
import re
from typing import List, Dict, Any, Optional

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.agent.state import RawIntel
from src.tools.llm import make_embeddings
from src.web.db import get_admin_client

# Global Ranker instance for lazy-loaded singleton to optimize memory/speed
_ranker = None

def _get_ranker():
    global _ranker
    if _ranker is None:
        try:
            from flashrank import Ranker
            # Lazy load the lightweight default FlashRank model (TinyBERT)
            _ranker = Ranker(cache_dir="./.flashrank_cache")
        except Exception as e:
            print(f"  [FlashRank] Warning: Failed to initialize Ranker: {e}. Falling back to default retrieval.")
    return _ranker

def rag_search(query: str, subagent_id: str = "lead", max_results: int = 5) -> List[RawIntel]:
    """
    Production Hybrid RAG Search utility:
      1. Embed query using FastEmbed (768-dim BAAI/bge-base-en-v1.5).
      2. Dense vector search against Pinecone (retrieving top 25 children).
      3. Keyword / Full-Text search against Supabase PostgreSQL text index.
      4. Combine and deduplicate candidate child passages.
      5. Rerank candidates using local CPU FlashRank.
      6. Retrieve high-context 1000-word parent chunks from Supabase.
      7. Return typed RawIntel with chunk attribution metadata.
    """
    api_key = Config.PINECONE_API_KEY
    index_name = Config.PINECONE_INDEX_NAME
    
    if not api_key:
        print("  [RAG Search] Warning: PINECONE_API_KEY is not configured.")
        return []
        
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            print(f"  [RAG Search] Warning: Index '{index_name}' does not exist.")
            return []
        index = pc.Index(index_name)
    except Exception as e:
        print(f"  [RAG Search] Error initializing Pinecone: {e}")
        return []

    # 1. Embed query
    try:
        embeddings_model = make_embeddings()
        query_vector = embeddings_model.embed_query(query)
    except Exception as e:
        print(f"  [RAG Search] Error generating embedding: {e}")
        return []

    # 2. Dense Vector Search in Pinecone
    matches = []
    try:
        search_response = index.query(
            vector=query_vector,
            top_k=25,
            include_metadata=True
        )
        matches = search_response.get("matches", [])
    except Exception as e:
        print(f"  [RAG Search] Pinecone query failed: {e}")

    child_ids = [match["id"] for match in matches]
    supabase = get_admin_client()
    
    child_map: Dict[str, Dict[str, Any]] = {}
    
    # 3. Retrieve dense vector child chunks from Supabase
    if child_ids:
        try:
            response = supabase.table("research_chunks").select(
                "id, parent_id, chunk_text, title, document_url, authors, published_date"
            ).in_("id", child_ids).execute()
            for row in (response.data or []):
                child_map[row["id"]] = row
        except Exception as e:
            print(f"  [RAG Search] Supabase vector row fetch failed: {e}")

    # 4. Keyword / Full-Text Search in Supabase for Hybrid Retrieval
    clean_terms = " & ".join([word for word in re.findall(r"\w+", query) if len(word) > 2])
    if clean_terms:
        try:
            text_res = supabase.table("research_chunks").select(
                "id, parent_id, chunk_text, title, document_url, authors, published_date"
            ).not_("parent_id", "is", None).text_search("chunk_text", clean_terms, options={"config": "english"}).limit(15).execute()
            for row in (text_res.data or []):
                if row["id"] not in child_map:
                    child_map[row["id"]] = row
        except Exception as e:
            # Fallback to simple text matching if tsquery has complex terms
            pass

    if not child_map:
        print("  [RAG Search] No matching chunk records found in Pinecone or Supabase.")
        return []

    # Assemble passages for FlashRank reranking
    passages = []
    for cid, row in child_map.items():
        passages.append({
            "id": cid,
            "text": row["chunk_text"],
            "meta": {
                "parent_id": row["parent_id"],
                "title": row["title"],
                "url": row["document_url"],
                "authors": row["authors"],
                "published_date": row["published_date"]
            }
        })

    # 5. Rerank using FlashRank
    ranker = _get_ranker()
    if ranker and passages:
        try:
            from flashrank import RerankRequest
            rerank_request = RerankRequest(query=query, passages=passages)
            reranked_results = ranker.rerank(rerank_request)
            top_passages = reranked_results[:max_results]
        except Exception as e:
            print(f"  [RAG Search] Reranking failed: {e}. Falling back to default ordering.")
            top_passages = passages[:max_results]
    else:
        top_passages = passages[:max_results]

    # 6. Fetch parent chunks for top reranked passages to ensure high context
    parent_ids = list(set([p["meta"]["parent_id"] for p in top_passages if p["meta"].get("parent_id")]))
    parent_texts = {}
    
    if parent_ids:
        try:
            parent_response = supabase.table("research_chunks").select("id, chunk_text").in_("id", parent_ids).execute()
            for row in (parent_response.data or []):
                parent_texts[row["id"]] = row["chunk_text"]
        except Exception as e:
            print(f"  [RAG Search] Failed to fetch parent chunks: {e}. Using child text instead.")

    # 7. Format as list of RawIntel objects with provenance attribution
    results = []
    for p in top_passages:
        parent_id = p["meta"]["parent_id"]
        parent_text = parent_texts.get(parent_id, p["text"])
        snippet_preview = parent_text[:300] + "..." if len(parent_text) > 300 else parent_text
        
        # Attribution info embedded in title/provenance header
        title_with_attribution = f"{p['meta']['title']} [Chunk: {p['id'][:8]}]"
        
        intel_item = RawIntel(
            source_url=p["meta"]["url"],
            title=title_with_attribution,
            snippet=snippet_preview,
            full_text=parent_text,
            published_date=p["meta"]["published_date"] or "",
            query=query,
            subagent_id=subagent_id,
        )
        results.append(intel_item)

    print(f"  [Hybrid RAG Search] Retrieved {len(results)} high-context results.")
    return results
