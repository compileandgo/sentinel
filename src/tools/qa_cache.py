import numpy as np
from typing import Optional, List
from src.tools.llm import make_embeddings
from src.web.db import get_admin_client

def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two vector lists."""
    arr1 = np.array(v1, dtype=np.float32)
    arr2 = np.array(v2, dtype=np.float32)
    norm1 = np.linalg.norm(arr1)
    norm2 = np.linalg.norm(arr2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(arr1, arr2) / (norm1 * norm2))

async def check_semantic_cache(chat_id: str, query: str, threshold: float = 0.90) -> Optional[str]:
    """
    Checks Supabase `qa_cache` for a semantically similar query in the current chat.
    Returns cached response if similarity >= threshold, else None.
    """
    if not chat_id:
        return None
    
    try:
        supabase = get_admin_client()
        res = supabase.table("qa_cache").select("query_text, query_embedding, response_text").eq("chat_id", chat_id).order("created_at", desc=True).limit(20).execute()
        
        rows = res.data or []
        if not rows:
            return None

        # Compute query embedding
        query_emb = make_embeddings().embed_query(query)
        
        best_sim = 0.0
        best_response = None

        for row in rows:
            cached_emb = row.get("query_embedding")
            if not cached_emb or not isinstance(cached_emb, list):
                continue
            
            sim = _cosine_similarity(query_emb, cached_emb)
            if sim > best_sim:
                best_sim = sim
                best_response = row["response_text"]

        if best_sim >= threshold and best_response:
            print(f"  [Semantic Cache HIT] Similarity: {best_sim:.3f} >= {threshold}")
            return best_response
        else:
            print(f"  [Semantic Cache MISS] Best similarity: {best_sim:.3f}")
            return None

    except Exception as e:
        print(f"  [Semantic Cache Error] {e}")
        return None


async def save_semantic_cache(chat_id: str, query: str, response_text: str) -> None:
    """Saves a query-response pair with its vector embedding to `qa_cache`."""
    if not chat_id or not query or not response_text:
        return

    try:
        query_emb = make_embeddings().embed_query(query)
        supabase = get_admin_client()
        supabase.table("qa_cache").insert({
            "chat_id": chat_id,
            "query_text": query,
            "query_embedding": query_emb,
            "response_text": response_text
        }).execute()
        print(f"  [Semantic Cache] Saved entry for chat_id: {chat_id[:8]}...")
    except Exception as e:
        print(f"  [Semantic Cache Save Error] {e}")
