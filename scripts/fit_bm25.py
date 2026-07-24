#!/usr/bin/env python3
"""
fit_bm25.py — One-time BM25 corpus fitting script.

Loads all child chunks from Supabase research_chunks, fits a BM25Encoder
on the full corpus, and saves the model to .bm25_cache/bm25_encoder.json.

Run this:
  uv run python scripts/fit_bm25.py

Re-run after ingesting new documents to keep the IDF weights current.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from src.web.db import get_admin_client

CACHE_DIR = Path(".bm25_cache")
ENCODER_PATH = CACHE_DIR / "bm25_encoder.json"
PAGE_SIZE = 1000


def fetch_all_child_chunks(supabase) -> list:
    """Paginate through research_chunks and return all child chunk texts."""
    texts = []
    offset = 0
    while True:
        try:
            res = (
                supabase.table("research_chunks")
                .select("chunk_text")
                .not_.is_("parent_id", "null")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
        except Exception as e:
            print(f"  [BM25 Fit] Supabase fetch error at offset {offset}: {e}")
            break

        rows = res.data or []
        if not rows:
            break
        texts.extend(row["chunk_text"] for row in rows if row.get("chunk_text"))
        print(f"  Fetched {offset + len(rows)} chunks so far...")
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return texts


def main():
    print("=== BM25 Encoder Fitting ===")
    supabase = get_admin_client()

    print("Fetching all child chunks from Supabase...")
    corpus = fetch_all_child_chunks(supabase)
    if not corpus:
        print("ERROR: No child chunks found. Ingest documents first.")
        sys.exit(1)

    print(f"Corpus size: {len(corpus)} child chunks. Fitting BM25Encoder...")

    try:
        from pinecone_text.sparse import BM25Encoder
    except ImportError:
        print("ERROR: pinecone-text not installed. Run: uv add pinecone-text")
        sys.exit(1)

    encoder = BM25Encoder()
    encoder.fit(corpus)

    CACHE_DIR.mkdir(exist_ok=True)
    encoder.dump(str(ENCODER_PATH))
    print(f"BM25Encoder saved to {ENCODER_PATH}")
    print(f"Done. {len(corpus)} chunks indexed with corpus-wide IDF weights.")


if __name__ == "__main__":
    main()
