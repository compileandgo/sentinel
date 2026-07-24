import os
import sys
import re
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


def _rrf_fuse(*ranked_lists, k: int = 60) -> list:
    """
    Reciprocal Rank Fusion across N ranked retrieval channels.
    RRF score = Σ  1 / (k + rank_i)  across all channels a chunk appears in.
    Chunks appearing in multiple channels get a compounded rank boost.
    k=60 is the standard constant (Robertson et al., 2009 / Cormack et al., 2009).
    """
    scores: Dict[str, float] = {}
    for rlist in ranked_lists:
        for rank, match in enumerate(rlist):
            cid = match["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def rag_search(query: str, subagent_id: str = "lead", max_results: int = 5) -> List[RawIntel]:
    """
    Production Multi-Channel Hybrid RAG Search:
      1. Dense embedding (BGE bi-encoder, 768-dim).
      2. BM25 sparse encoding (pinecone-text BM25Encoder, corpus-fitted IDF).
      3. Multi-Channel Retrieval:
         - Channel A: Pinecone Dense Vector Search (top-25)
         - Channel B: PostgreSQL Full-Text Keyword Search (top-25)
         - Channel C: Local BM25 Corpus-Weighted Scoring (top-25)
      4. Reciprocal Rank Fusion (RRF, k=60) merges all channels into a unified ranking.
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

    # ── Step 2: Channel A — Dense Vector Search (Pinecone) ────────────────────
    dense_matches = []
    try:
        resp = index.query(vector=query_vector, top_k=25, include_metadata=True)
        dense_matches = resp.get("matches", [])
    except Exception as e:
        print(f"  [RAG Search] Dense Pinecone query failed: {e}")

    dense_ids = [m["id"] for m in dense_matches]

    # ── Step 3: Channel B — PostgreSQL Full-Text Search (Supabase) ───────────
    fts_matches = []
    supabase_client = get_admin_client()
    clean_terms = " & ".join([word for word in re.findall(r"\w+", query) if len(word) > 2])
    if clean_terms:
        try:
            text_res = supabase_client.table("research_chunks").select("id").not_.is_("parent_id", "null").text_search("chunk_text", clean_terms, options={"config": "english"}).execute()
            fts_matches = [{"id": row["id"]} for row in (text_res.data or [])[:25]]
        except Exception as e:
            print(f"  [RAG Search] FTS search failed: {e}")

    # Collect candidate IDs from Dense + FTS
    candidate_ids = list(dict.fromkeys(dense_ids + [m["id"] for m in fts_matches]))

    if not candidate_ids:
        print("  [RAG Search] No results from retrieval channels.")
        return []

    # Fetch candidate chunk texts for BM25 & Reranking
    child_map: Dict[str, Dict[str, Any]] = {}
    try:
        resp = supabase_client.table("research_chunks").select(
            "id, parent_id, chunk_text, title, document_url, authors, published_date"
        ).in_("id", candidate_ids).execute()
        for row in (resp.data or []):
            child_map[row["id"]] = row
    except Exception as e:
        print(f"  [RAG Search] Supabase chunk fetch failed: {e}")

    # ── Step 4: Channel C — BM25 Corpus-Weighted Sparse Scoring ──────────────
    bm25_matches = []
    encoder = _get_bm25_encoder()
    if encoder and child_map:
        try:
            query_sparse = encoder.encode_queries(query)
            q_indices = set(query_sparse.get("indices", []))
            q_values = dict(zip(query_sparse.get("indices", []), query_sparse.get("values", [])))

            bm25_scores = []
            for cid, row in child_map.items():
                doc_sparse = encoder.encode_documents(row["chunk_text"])
                score = 0.0
                for idx, val in zip(doc_sparse.get("indices", []), doc_sparse.get("values", [])):
                    if idx in q_indices:
                        score += q_values[idx] * val
                bm25_scores.append((cid, score))

            # Rank by BM25 score
            bm25_scores.sort(key=lambda x: x[1], reverse=True)
            bm25_matches = [{"id": cid} for cid, score in bm25_scores if score > 0]
        except Exception as e:
            print(f"  [RAG Search] BM25 scoring failed: {e}")

    # ── Step 5: Reciprocal Rank Fusion (RRF) ─────────────────────────────────
    active_channels = [m for m in [dense_matches, bm25_matches, fts_matches] if m]
    rrf_ranked = _rrf_fuse(*active_channels)
    fused_ids = [cid for cid, _ in rrf_ranked[:40]]

    if not fused_ids:
        print("  [RAG Search] No results from retrieval channels.")
        return []

    bm25_active = bool(bm25_matches)
    print(f"  [RAG Search] RRF fused {len(fused_ids)} candidates across {len(active_channels)} channels "
          f"({'Dense + BM25 + FTS' if bm25_active else 'Dense + FTS'}).")

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
