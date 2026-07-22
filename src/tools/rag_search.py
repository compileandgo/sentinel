import os
import sys
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
            # Lazy load the lightweight MiniLM model
            _ranker = Ranker(model_name="ms-marco-MiniLM-L-6-v2", cache_dir="./.flashrank_cache")
        except Exception as e:
            print(f"  [FlashRank] Warning: Failed to initialize Ranker: {e}. Falling back to default retrieval.")
    return _ranker

def rag_search(query: str, subagent_id: str = "lead", max_results: int = 5) -> List[RawIntel]:
    """
    RAG search utility:
      1. Embed query using text-embedding-004.
      2. Dense vector search against Pinecone (retrieving top 25 children).
      3. Retrieve child chunks text from Supabase.
      4. Rerank child chunks using local FlashRank.
      5. Fetch matching parent chunks for high-context snippets.
    """
    api_key = Config.PINECONE_API_KEY
    index_name = Config.PINECONE_INDEX_NAME
    
    if not api_key:
        print("  [RAG Search] Warning: PINECONE_API_KEY is not configured.")
        return []
        
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        # Verify index exists
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

    # 2. Query Pinecone
    try:
        # Retrieve top 25 to give FlashRank enough documents to filter
        search_response = index.query(
            vector=query_vector,
            top_k=25,
            include_metadata=True
        )
        matches = search_response.get("matches", [])
        if not matches:
            print("  [RAG Search] No semantic matches found in Pinecone.")
            return []
    except Exception as e:
        print(f"  [RAG Search] Pinecone query failed: {e}")
        return []

    # Extract child IDs (which are the Pinecone record IDs)
    child_ids = [match["id"] for match in matches]
    
    # 3. Retrieve child chunks from Supabase
    try:
        supabase = get_admin_client()
        # Query research_chunks table for child details
        response = supabase.table("research_chunks").select(
            "id, parent_id, chunk_text, title, document_url, authors, published_date"
        ).in_("id", child_ids).execute()
        
        child_rows = response.data or []
        if not child_rows:
            print("  [RAG Search] No matching chunk records found in Supabase.")
            return []
    except Exception as e:
        print(f"  [RAG Search] Supabase query failed: {e}")
        return []

    # Map database rows to the matched child chunks
    child_map = {row["id"]: row for row in child_rows}
    
    # Format passages for FlashRank
    passages = []
    for match in matches:
        cid = match["id"]
        if cid in child_map:
            row = child_map[cid]
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

    # 4. Rerank using FlashRank
    ranker = _get_ranker()
    if ranker and passages:
        try:
            from flashrank import RerankRequest
            rerank_request = RerankRequest(query=query, passages=passages)
            reranked_results = ranker.rerank(rerank_request)
            # Reranked list contains dictionaries with {"id", "text", "meta", "score"}
            top_passages = reranked_results[:max_results]
        except Exception as e:
            print(f"  [RAG Search] Reranking failed: {e}. Falling back to default ordering.")
            top_passages = passages[:max_results]
    else:
        top_passages = passages[:max_results]

    # 5. Fetch parent chunks for top reranked passages to ensure high context
    parent_ids = list(set([p["meta"]["parent_id"] for p in top_passages if p["meta"].get("parent_id")]))
    parent_texts = {}
    
    if parent_ids:
        try:
            parent_response = supabase.table("research_chunks").select("id, chunk_text").in_("id", parent_ids).execute()
            for row in (parent_response.data or []):
                parent_texts[row["id"]] = row["chunk_text"]
        except Exception as e:
            print(f"  [RAG Search] Failed to fetch parent chunks: {e}. Using child text instead.")

    # Format as list of RawIntel objects
    results = []
    for p in top_passages:
        parent_id = p["meta"]["parent_id"]
        # Use parent text if available, otherwise fallback to child text
        parent_text = parent_texts.get(parent_id, p["text"])
        
        # We populate snippet with a concise preview and full_text with the full parent context
        snippet_preview = parent_text[:300] + "..." if len(parent_text) > 300 else parent_text
        
        results.append(RawIntel(
            source_url=p["meta"]["url"],
            title=p["meta"]["title"],
            snippet=snippet_preview,
            full_text=parent_text,
            published_date=p["meta"]["published_date"] or "",
            query=query,
            subagent_id=subagent_id,
        ))

    print(f"  [RAG Search] Retrieved {len(results)} high-context results.")
    return results
