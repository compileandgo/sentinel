import os
import sys
from typing import List, Dict, Any

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.agent.state import RawIntel
from src.tools.llm import make_embeddings
from src.web.db import get_admin_client

# ── Singletons ────────────────────────────────────────────────────────────────
_ranker = None
_bm25_encoder = None

def _get_ranker():
    global _ranker
    if _ranker is None:
        try:
            from flashrank import Ranker
            _ranker = Ranker(cache_dir="./.flashrank_cache")
        except Exception as e:
            print(f"  [FlashRank] Warning: Failed to initialize Ranker: {e}.")
    return _ranker


def _get_bm25_encoder():
    """Lazy-load the fitted BM25Encoder from .bm25_cache/bm25_encoder.json."""
    global _bm25_encoder
    if _bm25_encoder is not None:
        return _bm25_encoder
    try:
        from pinecone_text.sparse import BM25Encoder
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        bm25_path = os.path.join(project_root, ".bm25_cache", "bm25_encoder.json")
        if os.path.exists(bm25_path):
            enc = BM25Encoder()
            enc.load(bm25_path)
            _bm25_encoder = enc
            print("  [BM25] Loaded fitted BM25Encoder from .bm25_cache/")
        else:
            print("  [BM25] bm25_encoder.json not found — run scripts/fit_bm25.py to enable sparse retrieval.")
    except Exception as e:
        print(f"  [BM25] Could not load BM25Encoder: {e}")
    return _bm25_encoder


def _rrf_fuse(dense: list, sparse: list, k: int = 60) -> list:
    """
    Reciprocal Rank Fusion.
    Merges two ranked lists into a single ranking.
    RRF score = Σ  1 / (k + rank_i)  across all lists chunk appears in.
    Chunks appearing in BOTH lists get a compounded boost.
    k=60 is the standard constant (Robertson et al., 2009).
    """
    scores: Dict[str, float] = {}
    for rank, match in enumerate(dense):
        cid = match["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    for rank, match in enumerate(sparse):
        cid = match["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def rag_search(query: str, subagent_id: str = "lead", max_results: int = 5) -> List[RawIntel]:
    """
    Production Hybrid RAG Search:
      1. Dense embedding (BGE bi-encoder, 768-dim).
      2. BM25 sparse encoding (pinecone-text BM25Encoder, corpus-fitted IDF).
      3. Two independent Pinecone queries — dense top-25, sparse top-25.
      4. Reciprocal Rank Fusion (RRF, k=60) merges both ranked lists.
         Chunks appearing in BOTH channels get a compounded score boost.
      5. Cross-encoder reranking (FlashRank / ms-marco-TinyBERT-L-2-v2).
      6. Parent Document Retrieval — swap child snippets for 1000-word parents.
      7. Return typed RawIntel objects with full provenance metadata.
    """
    api_key = Config.PINECONE_API_KEY
    index_name = Config.PINECONE_INDEX_NAME

    if not api_key:
        print("  [RAG Search] Warning: PINECONE_API_KEY is not configured.")
        return []

    # ── Pinecone client ───────────────────────────────────────────────────────
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

    # ── Step 1: Dense embedding ───────────────────────────────────────────────
    try:
        query_vector = make_embeddings().embed_query(query)
    except Exception as e:
        print(f"  [RAG Search] Error generating embedding: {e}")
        return []

    # ── Step 2: BM25 sparse encoding ─────────────────────────────────────────
    encoder = _get_bm25_encoder()
    sparse_vector = None
    if encoder:
        try:
            sparse_vector = encoder.encode_queries(query)
        except Exception as e:
            print(f"  [RAG Search] BM25 encode failed: {e}")

    # ── Step 3: Pinecone queries — dense and sparse independently ─────────────
    dense_matches = []
    sparse_matches = []

    try:
        resp = index.query(vector=query_vector, top_k=25, include_metadata=True)
        dense_matches = resp.get("matches", [])
    except Exception as e:
        print(f"  [RAG Search] Dense Pinecone query failed: {e}")

    if sparse_vector:
        try:
            resp = index.query(sparse_vector=sparse_vector, top_k=25, include_metadata=True)
            sparse_matches = resp.get("matches", [])
        except Exception as e:
            print(f"  [RAG Search] Sparse Pinecone query failed (dense-only fallback): {e}")

    # ── Step 4: Reciprocal Rank Fusion ────────────────────────────────────────
    rrf_ranked = _rrf_fuse(dense_matches, sparse_matches)
    fused_ids = [cid for cid, _ in rrf_ranked[:40]]   # generous pre-rerank budget

    if not fused_ids:
        print("  [RAG Search] No results from Pinecone.")
        return []

    bm25_active = bool(sparse_vector and sparse_matches)
    print(f"  [RAG Search] RRF fused {len(fused_ids)} candidates "
          f"({'BM25+Dense' if bm25_active else 'Dense-only — run fit_bm25.py to activate BM25'}).")

    # ── Step 5: Fetch chunk texts from Supabase ───────────────────────────────
    supabase = get_admin_client()
    child_map: Dict[str, Dict[str, Any]] = {}
    try:
        resp = supabase.table("research_chunks").select(
            "id, parent_id, chunk_text, title, document_url, authors, published_date"
        ).in_("id", fused_ids).execute()
        for row in (resp.data or []):
            child_map[row["id"]] = row
    except Exception as e:
        print(f"  [RAG Search] Supabase chunk fetch failed: {e}")

    if not child_map:
        print("  [RAG Search] No chunk records found in Supabase for fused IDs.")
        return []

    # Preserve RRF order for initial passage list fed into reranker
    passages = []
    for cid in fused_ids:
        row = child_map.get(cid)
        if not row:
            continue
        passages.append({
            "id": cid,
            "text": row["chunk_text"],
            "meta": {
                "parent_id": row["parent_id"],
                "title": row["title"],
                "url": row["document_url"],
                "authors": row["authors"],
                "published_date": row["published_date"],
            }
        })

    # ── Step 6: Cross-encoder reranking (FlashRank) ───────────────────────────
    ranker = _get_ranker()
    if ranker and passages:
        try:
            from flashrank import RerankRequest
            reranked = ranker.rerank(RerankRequest(query=query, passages=passages))
            top_passages = reranked[:max_results]
        except Exception as e:
            print(f"  [RAG Search] Reranking failed: {e}. Using RRF order.")
            top_passages = passages[:max_results]
    else:
        top_passages = passages[:max_results]

    # ── Step 7: Parent Document Retrieval (Small-to-Big) ─────────────────────
    parent_ids = list({p["meta"]["parent_id"] for p in top_passages if p["meta"].get("parent_id")})
    parent_texts: Dict[str, str] = {}
    if parent_ids:
        try:
            pr = supabase.table("research_chunks").select("id, chunk_text").in_("id", parent_ids).execute()
            for row in (pr.data or []):
                parent_texts[row["id"]] = row["chunk_text"]
        except Exception as e:
            print(f"  [RAG Search] Parent chunk fetch failed: {e}. Using child text.")

    # ── Step 8: Build RawIntel results ───────────────────────────────────────
    results = []
    for p in top_passages:
        pid = p["meta"]["parent_id"]
        full_text = parent_texts.get(pid, p["text"])
        snippet = full_text[:300] + "..." if len(full_text) > 300 else full_text
        results.append(RawIntel(
            source_url=p["meta"]["url"],
            title=f"{p['meta']['title']} [Chunk: {p['id'][:8]}]",
            snippet=snippet,
            full_text=full_text,
            published_date=p["meta"]["published_date"] or "",
            query=query,
            subagent_id=subagent_id,
        ))

    print(f"  [Hybrid RAG] Returned {len(results)} high-context results.")
    return results
