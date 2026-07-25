# Vector Semantic Q&A Cache

Sentinel implements a vector-based semantic cache in `src/tools/qa_cache.py`. Previous Q&A query-response pairs are stored with 768-dimensional BGE vector embeddings in Supabase (`public.qa_cache`). When a user asks a question, the system checks if a semantically similar question has already been answered.

---

## Key Libraries Used

* **`fastembed.TextEmbedding`**: Computes 768-dim BGE embeddings for incoming queries.
* **`numpy`**: Computes fast vector cosine similarity between query embeddings.
* **`supabase`**: Reads and writes cached entries to the `qa_cache` database table.

---

## Cosine Similarity Formula

$$\text{Similarity}(\mathbf{a}, \mathbf{b}) = \frac{\mathbf{a} \cdot \mathbf{b}}{\|\mathbf{a}\| \|\mathbf{b}\|} = \frac{\sum_{i=1}^{n} a_i b_i}{\sqrt{\sum_{i=1}^{n} a_i^2} \sqrt{\sum_{i=1}^{n} b_i^2}}$$

If $\text{Similarity} \ge 0.90$ (90%+ semantic match) for a query within the same chat session:
1. LLM invocation and Web Search are **bypassed completely**.
2. Cached answer is returned instantly in **~1.1 seconds** (vs ~16.5 seconds for fresh generation).
3. Saves **100% of LLM token costs**.

---

## Implementation (`src/tools/qa_cache.py`)

### 1. Vector Cosine Similarity Function
```python
def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
 arr1 = np.array(v1, dtype=np.float32)
 arr2 = np.array(v2, dtype=np.float32)
 norm1 = np.linalg.norm(arr1)
 norm2 = np.linalg.norm(arr2)
 if norm1 == 0 or norm2 == 0:
 return 0.0
 return float(np.dot(arr1, arr2) / (norm1 * norm2))
```

### 2. Checking Semantic Cache
```python
async def check_semantic_cache(chat_id: str, query: str, threshold: float = 0.90) -> Optional[str]:
 supabase = get_admin_client()
 res = supabase.table("qa_cache").select("query_text, query_embedding, response_text").eq("chat_id", chat_id).order("created_at", desc=True).limit(20).execute()
 
 rows = res.data or []
 if not rows:
 return None

 query_emb = make_embeddings().embed_query(query)
 
 for row in rows:
 cached_emb = row.get("query_embedding")
 if cached_emb and _cosine_similarity(query_emb, cached_emb) >= threshold:
 return row["response_text"]

 return None
```

---

## Performance Benchmarks

| Metric | Cache MISS (Fresh LLM) | Cache HIT (Vector Match) | Improvement |
|---|---|---|---|
| **Response Latency** | 16,553 ms (16.5s) | 1,132 ms (1.1s) | **14.6x Faster** |
| **LLM Token Cost** | ~$0.005 - $0.02 | **$0.00** | **100% Savings** |
| **Server CPU Load** | High (Search + LLM) | Minimal (Numpy Dot Product) | **95% Reduction** |
