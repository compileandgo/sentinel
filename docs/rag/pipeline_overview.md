# Retrieval-Augmented Generation (RAG) Engine Overview

Sentinel's RAG pipeline ingests research reports and documents, breaks them into contextual chunks, generates dense and sparse vector representations, and retrieves top relevant intelligence during Q&A and research loops.

---

## Key Libraries Used

* **`fastembed.TextEmbedding`**: Generates 768-dimensional dense vector embeddings locally using ONNX-optimized BGE (`BAAI/bge-base-en-v1.5`).
* **`pinecone-text.sparse.BM25Encoder`**: Computes sparse term frequency metrics locally.
* **`pinecone.Pinecone`**: Cloud vector database client for dense vector similarity queries.
* **`postgrest` / `supabase`**: Executes PostgreSQL Full-Text Search (`tsquery`) queries.

---

## RAG Pipeline Workflow

```
1. Document Ingestion ──► 2. Parent-Child Chunking ──► 3. Dual Embedding Generation
(Markdown / PDF / Text) (Parent: 1000w, Child: 200w) (Dense BGE + Sparse BM25)
 │
 ▼
4. Synthesis Generation ◄── 5. Reciprocal Rank Fusion ◄── 4. Multi-Channel Search
 (Gemini / Groq LLM) (Fuses 3 channels, k=60) (Pinecone, BM25, Postgres FTS)
```

---

## Parent-Child Chunking Strategy (`scripts/ingest_documents.py`)

To solve the tradeoff between **retrieval accuracy** (small chunks) and **LLM context depth** (large chunks), Sentinel uses a **Parent-Child Chunking** model:

* **Parent Chunks (~800–1200 words)**: High-level section or full document context. Preserved in Supabase `research_chunks` database table.
* **Child Chunks (~150–250 words)**: Atomic paragraphs optimized for fine-grained vector embedding search. Child chunks store a foreign key `parent_id` linking back to their parent.

During retrieval, child chunks match the user's specific query, but the RAG engine returns the **Parent Chunk** to the LLM so it receives full surrounding context without truncated facts.
