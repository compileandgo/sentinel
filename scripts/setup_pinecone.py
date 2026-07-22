#!/usr/bin/env python3
import os
import sys
import time
from dotenv import load_dotenv

# Ensure parent directory is in sys.path to import src.config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config

def main():
    load_dotenv()
    api_key = Config.PINECONE_API_KEY
    index_name = Config.PINECONE_INDEX_NAME
    
    if not api_key:
        print("Error: PINECONE_API_KEY is not set.")
        sys.exit(1)
        
    print(f"Initializing Pinecone client...")
    from pinecone import Pinecone, ServerlessSpec
    
    pc = Pinecone(api_key=api_key)
    
    print("Checking existing indexes...")
    try:
        existing = [idx.name for idx in pc.list_indexes()]
        print(f"Existing indexes: {existing}")
    except Exception as e:
        print(f"Failed to list indexes: {e}")
        sys.exit(1)
    
    if index_name not in existing:
        print(f"Creating index '{index_name}' (dimension=768, metric=cosine)...")
        try:
            pc.create_index(
                name=index_name,
                dimension=768,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                )
            )
            print(f"Index '{index_name}' created successfully. Waiting for it to become ready...")
            
            # Wait until ready
            while not pc.describe_index(index_name).status.ready:
                print("Waiting for index to be ready...")
                time.sleep(5)
                
            print(f"Index '{index_name}' is ready for use.")
        except Exception as e:
            print(f"Failed to create index: {e}")
            sys.exit(1)
    else:
        print(f"Index '{index_name}' already exists.")

if __name__ == "__main__":
    main()
