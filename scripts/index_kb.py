#!/usr/bin/env python3
"""
scripts/index_kb.py
Index seed knowledge base theorems into ChromaDB for vector-based context retrieval.
"""

import argparse
import json
import os
import sys
import chromadb
from chromadb.config import Settings


def load_knowledge_base(kb_path: str):
    """Loads records from a JSONL knowledge base file."""
    records = []
    if not os.path.exists(kb_path):
        raise FileNotFoundError(f"Knowledge base file not found: {kb_path}")
    
    with open(kb_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping invalid JSON at line {line_num}: {e}", file=sys.stderr)
    return records


def index_knowledge_base(kb_path: str, db_dir: str, collection_name: str = "number_theory_kb", reset: bool = False):
    """Indexes knowledge base records into ChromaDB persistent database."""
    records = load_knowledge_base(kb_path)
    print(f"Loaded {len(records)} records from '{kb_path}'.")

    client = chromadb.PersistentClient(path=db_dir)
    
    if reset:
        try:
            client.delete_collection(collection_name)
            print(f"Deleted existing collection '{collection_name}'.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"description": "Elementary Number Theory seed theorems and formal Lean 4 signatures"}
    )

    documents = []
    metadatas = []
    ids = []

    for r in records:
        # Construct search text incorporating concept name, subtopic, informal statement, and tags
        tags_str = ", ".join(r.get("tags", []))
        doc_text = (
            f"Concept: {r.get('concept_name', '')}\n"
            f"Subtopic: {r.get('subtopic', '')}\n"
            f"Statement: {r.get('informal_statement', '')}\n"
            f"Tags: {tags_str}"
        )
        
        # Prepare metadata scalar values for ChromaDB
        meta = {
            "id": str(r.get("id", "")),
            "concept_name": str(r.get("concept_name", "")),
            "subtopic": str(r.get("subtopic", "")),
            "formal_type": str(r.get("formal_type", "")),
            "lean4_signature": str(r.get("lean4_signature", "")),
            "informal_statement": str(r.get("informal_statement", "")),
            "lean4_imports": json.dumps(r.get("lean4_imports", [])),
            "tags": tags_str,
            "related_ids": json.dumps(r.get("related_ids", []))
        }

        documents.append(doc_text)
        metadatas.append(meta)
        ids.append(str(r.get("id")))

    if ids:
        collection.upsert(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Successfully indexed {len(ids)} theorems into ChromaDB collection '{collection_name}' at '{db_dir}'.")

    return client, collection


def query_index(db_dir: str, query_text: str, top_k: int = 3, collection_name: str = "number_theory_kb"):
    """Queries the ChromaDB collection and prints top matching documents."""
    client = chromadb.PersistentClient(path=db_dir)
    collection = client.get_collection(name=collection_name)
    
    results = collection.query(
        query_texts=[query_text],
        n_results=top_k
    )

    print(f"\n--- Search Results for Query: '{query_text}' (top {top_k}) ---")
    if not results or not results.get("ids") or not results["ids"][0]:
        print("No matching results found.")
        return []

    matched_records = []
    for i in range(len(results["ids"][0])):
        res_id = results["ids"][0][i]
        metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
        document = results["documents"][0][i] if results.get("documents") else ""
        distance = results["distances"][0][i] if results.get("distances") else None
        
        print(f"\nResult {i+1} [ID: {res_id}] (Distance: {distance:.4f} if distance else 'N/A'):")
        print(f"  Concept: {metadata.get('concept_name')}")
        print(f"  Subtopic: {metadata.get('subtopic')}")
        print(f"  Informal: {metadata.get('informal_statement')}")
        print(f"  Lean 4: {metadata.get('lean4_signature')}")

        matched_records.append({
            "id": res_id,
            "metadata": metadata,
            "document": document,
            "distance": distance
        })
    return matched_records


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="Index knowledge_base.jsonl into ChromaDB")
    parser.add_argument("--kb_path", type=str, default="knowledge_base.jsonl", help="Path to knowledge_base.jsonl")
    parser.add_argument("--db_dir", type=str, default="chroma_db", help="Directory for ChromaDB persistent storage")
    parser.add_argument("--collection", type=str, default="number_theory_kb", help="ChromaDB collection name")
    parser.add_argument("--reset", action="store_true", help="Reset existing collection before indexing")
    parser.add_argument("--query", type=str, default=None, help="Optional test query to run after indexing")
    parser.add_argument("--top_k", type=int, default=3, help="Number of results for test query")

    args = parser.parse_args()

    index_knowledge_base(args.kb_path, args.db_dir, collection_name=args.collection, reset=args.reset)

    if args.query:
        query_index(args.db_dir, args.query, top_k=args.top_k, collection_name=args.collection)


if __name__ == "__main__":
    main()
