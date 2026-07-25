# 3-Channel Hybrid Search & Reciprocal Rank Fusion (RRF)

Sentinel implements a multi-channel hybrid retrieval engine in `src/tools/rag_search.py`. Dense-only vector search often misses exact acronyms, numbers, or specific names, while keyword-only search misses semantic synonyms. Sentinel combines 3 distinct search channels using **Reciprocal Rank Fusion (RRF)**.

---

## Key Libraries Used

* **`pinecone`**: Retrieves candidate matches based on **Dense Cosine Vector Similarity**.
* **`pinecone-text.sparse.BM25Encoder`**: Scores candidates locally using **Best Matching 25 (BM25)** term frequency / inverse document frequency metrics.
* **`supabase`**: Executes **PostgreSQL Full-Text Search (`tsquery`)** over `research_chunks` table.

---

## Retrieval Channels

```
 User Search Query
 │
 ┌─────────────────────────┼─────────────────────────┐
 ▼ ▼ ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Channel 1: Dense │ │ Channel 2: BM25 │ │ Channel 3: FTS │
│ Vector Search │ │ Local Encoder │ │ Postgres tsquery │
│ (Pinecone Top 25)│ │ (Local Top 25) │ │ (Supabase Top 25)│
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
 │ │ │
 └─────────────────────────┼─────────────────────────┘
 │
 ▼
 ┌────────────────────────┐
 │ Reciprocal Rank Fusion │
 │ RRF(d) = ∑ 1/(60+r) │
 └───────────┬────────────┘
 │
 ▼
 Top 25 Unified Results
```

### Channel 1: Pinecone Dense Vector Search
Generates a 768-dim BGE vector for the query and executes a cosine similarity search against Pinecone:
```python
dense_vector = make_embeddings().embed_query(query)
pinecone_res = index.query(vector=dense_vector, top_k=25, include_metadata=True)
```

### Channel 2: Local BM25 Scoring
Loads the fitted `BM25Encoder` from `.bm25_cache/bm25_encoder.json` and computes term scores against candidate chunk texts.

### Channel 3: Supabase PostgreSQL Full-Text Search
Executes a SQL `websearch_to_tsquery` or `textSearch` query over the `research_chunks` table in Supabase.

---

## Reciprocal Rank Fusion (RRF) Formula

RRF merges rankings from multiple channels into a single unified score without requiring score normalization across different scales:

$$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

* $M$: Set of search channels ($M = \{\text{Dense}, \text{BM25}, \text{FTS}\}$).
* $r_m(d)$: The 1-based rank position of document $d$ in channel $m$.
* $k$: Smoothing constant (standard $k = 60$).

### RRF Code Implementation (`src/tools/rag_search.py`)

```python
def _rrf_fuse(*channel_results: List[Dict], k: int = 60) -> List[Dict]:
 scores = {}
 doc_map = {}

 for channel in channel_results:
 for rank, doc in enumerate(channel, start=1):
 doc_id = doc.get("id") or doc.get("chunk_id")
 if not doc_id:
 continue
 doc_map[doc_id] = doc
 scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))

 sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
 return [doc_map[doc_id] for doc_id in sorted_ids]
```

---

## Performance Impact

Benchmarking shows the algorithm overhead of RRF fusion across all 3 channels is **< 5ms**, while retrieval accuracy increases significantly for technical and acronym-heavy queries.
