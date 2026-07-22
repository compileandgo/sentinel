#!/usr/bin/env python3
import os
import sys
import json
import argparse
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.tools.llm import make_embeddings
from src.web.db import get_admin_client

def split_by_tokens(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        if len(chunk_words) < 10:
            break
        chunks.append(" ".join(chunk_words))
        i += (chunk_size - chunk_overlap)
    return chunks

def extract_text_from_pdf(pdf_path: Path) -> str:
    import pypdf
    try:
        reader = pypdf.PdfReader(pdf_path)
        text_parts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return ""

def main():
    parser = argparse.ArgumentParser(description="Ingest Pew reports into Supabase and Pinecone.")
    parser.add_argument("--dir", default="./pew_reports", help="Directory containing PDFs.")
    parser.add_argument("--metadata", default="./pew_reports/metadata.jsonl", help="Metadata jsonl file.")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for Pinecone upload.")
    args = parser.parse_args()

    load_dotenv()
    
    # Initialize Clients
    api_key = Config.PINECONE_API_KEY
    index_name = Config.PINECONE_INDEX_NAME
    if not api_key:
        print("Error: PINECONE_API_KEY is not set.")
        sys.exit(1)
        
    from pinecone import Pinecone
    pc = Pinecone(api_key=api_key)
    try:
        index = pc.Index(index_name)
    except Exception as e:
        print(f"Error getting Pinecone index {index_name}: {e}. Run setup_pinecone.py first.")
        sys.exit(1)
        
    supabase = get_admin_client()
    
    # Make embeddings model
    embeddings_model = make_embeddings()
    
    meta_path = Path(args.metadata)
    if not meta_path.exists():
        print(f"Error: metadata file not found at {meta_path}")
        sys.exit(1)
        
    # Read metadata file
    records = []
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception as e:
                    print(f"Error parsing metadata line: {e}")
                    
    print(f"Loaded {len(records)} metadata records. Starting ingestion...")
    
    for record_idx, record in enumerate(records):
        url = record.get("url", "")
        title = record.get("title", "")
        published_date = record.get("published", "")
        authors = record.get("authors", [])
        local_pdfs = record.get("local_pdfs", [])
        
        print(f"\nProcessing [{record_idx+1}/{len(records)}]: {title}")
        
        for local_pdf_path_str in local_pdfs:
            pdf_path = Path(local_pdf_path_str)
            # Handle relative pathing just in case
            if not pdf_path.exists():
                # Try relative to the metadata file
                pdf_path = meta_path.parent / pdf_path.name
                if not pdf_path.exists():
                    # Try under subdirectory
                    pdf_path = meta_path.parent / "pdfs" / pdf_path.name
                    if not pdf_path.exists():
                        print(f"  [Warning] PDF file not found at {local_pdf_path_str} or {pdf_path}")
                        continue
            
            print(f"  Extracting text from {pdf_path.name}...")
            full_text = extract_text_from_pdf(pdf_path)
            if not full_text.strip():
                print(f"  [Warning] No text extracted from {pdf_path.name}")
                continue
                
            # Chunking
            # 1. Split into parent chunks (1000 words, 200 overlap)
            parent_chunks = split_by_tokens(full_text, chunk_size=1000, chunk_overlap=200)
            print(f"  Split into {len(parent_chunks)} parent chunks.")
            
            for parent_idx, parent_text in enumerate(parent_chunks):
                # Save parent chunk to Supabase to get its UUID
                try:
                    parent_res = supabase.table("research_chunks").insert({
                        "parent_id": None,
                        "document_url": url,
                        "title": title,
                        "authors": authors,
                        "published_date": published_date,
                        "chunk_index": parent_idx,
                        "chunk_text": parent_text
                    }).execute()
                    
                    if not parent_res.data:
                        print(f"    Failed to insert parent chunk {parent_idx}")
                        continue
                        
                    parent_uuid = parent_res.data[0]["id"]
                except Exception as e:
                    print(f"    Error inserting parent chunk {parent_idx}: {e}")
                    continue
                
                # Split parent chunk into child chunks (200 words, 50 overlap)
                child_chunks = split_by_tokens(parent_text, chunk_size=200, chunk_overlap=50)
                if not child_chunks:
                    continue
                
                # Generate embeddings for all children of this parent
                try:
                    child_embeddings = embeddings_model.embed_documents(child_chunks)
                except Exception as e:
                    print(f"    Error generating embeddings for children of parent {parent_idx}: {e}")
                    continue
                
                pinecone_vectors = []
                supabase_rows = []
                
                for child_idx, (child_text, child_emb) in enumerate(zip(child_chunks, child_embeddings)):
                    child_uuid = str(uuid.uuid4())
                    
                    # Store row for Supabase child
                    supabase_rows.append({
                        "id": child_uuid,
                        "parent_id": parent_uuid,
                        "document_url": url,
                        "title": title,
                        "authors": authors,
                        "published_date": published_date,
                        "chunk_index": child_idx,
                        "chunk_text": child_text
                    })
                    
                    # Store vector for Pinecone
                    pinecone_vectors.append({
                        "id": child_uuid,
                        "values": child_emb,
                        "metadata": {
                            "parent_id": parent_uuid,
                            "title": title,
                            "url": url
                        }
                    })
                
                # Bulk insert to Supabase
                try:
                    supabase.table("research_chunks").insert(supabase_rows).execute()
                except Exception as e:
                    print(f"    Error inserting children to Supabase: {e}")
                    continue
                    
                # Bulk upsert to Pinecone in batches
                try:
                    for i in range(0, len(pinecone_vectors), args.batch_size):
                        batch = pinecone_vectors[i : i + args.batch_size]
                        index.upsert(vectors=batch)
                except Exception as e:
                    print(f"    Error upserting to Pinecone: {e}")
                    continue
                    
                print(f"    Successfully ingested parent chunk {parent_idx+1}/{len(parent_chunks)} with {len(child_chunks)} child vectors.")

    print("\nIngestion complete!")

if __name__ == "__main__":
    main()
