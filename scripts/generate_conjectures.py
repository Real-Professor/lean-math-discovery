#!/usr/bin/env python3
"""
scripts/generate_conjectures.py
Generate mathematical candidate conjectures in Elementary Number Theory using ChromaDB context retrieval.
"""

import argparse
import json
import os
import sys
import uuid
import datetime
from typing import Any, Dict, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import chromadb
try:
    from scripts.llm_client import generate_json, detect_provider
except ImportError:
    try:
        from llm_client import generate_json, detect_provider
    except ImportError:
        generate_json = None
        detect_provider = None


def retrieve_rag_context(db_dir: str, query: str, top_k: int = 3, collection_name: str = "number_theory_kb"):
    """Queries ChromaDB to retrieve relevant seed theorem context."""
    if not os.path.exists(db_dir):
        print(f"Warning: ChromaDB directory '{db_dir}' not found. Run scripts/index_kb.py first.", file=sys.stderr)
        return []

    try:
        client = chromadb.PersistentClient(path=db_dir)
        collection = client.get_collection(name=collection_name)
        results = collection.query(query_texts=[query], n_results=top_k)
        
        context_seeds = []
        if results and results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                context_seeds.append({
                    "id": results["ids"][0][i],
                    "concept_name": meta.get("concept_name"),
                    "subtopic": meta.get("subtopic"),
                    "informal_statement": meta.get("informal_statement"),
                    "lean4_signature": meta.get("lean4_signature")
                })
        return context_seeds
    except Exception as e:
        print(f"Error querying ChromaDB: {e}", file=sys.stderr)
        return []


def generate_llm_conjectures(
    prompt: str,
    seed_ids: list,
    strategy: str,
    count: int,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Invokes LLM API (Gemini or OpenAI) to generate structured candidate conjectures."""
    system_prompt = (
        "You are an expert mathematical AI system specializing in Elementary Number Theory. "
        "Generate creative, novel, non-trivial candidate mathematical conjectures based on seed context. "
        "Each output MUST be a JSON array of objects (or an object with a 'conjectures' array) adhering strictly to this schema:\n"
        "[\n"
        "  {\n"
        '    "conjecture_id": "CONJ_2026_XXX",\n'
        '    "generation_strategy": "...",\n'
        '    "seed_ids_used": ["..."],\n'
        '    "informal_statement": "If ... then ...",\n'
        '    "test_variables": [ {"name": "p", "type": "int", "constraints": "is_prime(p) and p > 3"} ],\n'
        '    "verification_status": "unverified",\n'
        '    "counterexample": null,\n'
        '    "tested_bound": 0,\n'
        '    "lean4_statement": "theorem prime_example (p : ℕ) (hp : Nat.Prime p) : ...",\n'
        '    "proof_status": "unverified",\n'
        '    "compiler_errors": []\n'
        "  }\n"
        "]"
    )

    if generate_json:
        data, used_prov = generate_json(
            prompt=prompt,
            system_instruction=system_prompt,
            provider=provider,
            api_key=api_key,
            model=model
        )
        if data is not None:
            print(f"Generated conjectures using {used_prov}")
            if isinstance(data, list):
                conjs = data
            elif isinstance(data, dict) and "conjectures" in data:
                conjs = data["conjectures"]
            elif isinstance(data, dict):
                conjs = [data]
            else:
                conjs = []

            # Normalize conjecture records
            normalized = []
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            for idx, c in enumerate(conjs):
                if not isinstance(c, dict):
                    continue
                cid = c.get("conjecture_id") or f"CONJ_2026_{timestamp}_{idx+1:03d}"
                c["conjecture_id"] = cid
                c["generation_strategy"] = strategy
                if not c.get("seed_ids_used"):
                    c["seed_ids_used"] = seed_ids
                c.setdefault("verification_status", "unverified")
                c.setdefault("counterexample", None)
                c.setdefault("tested_bound", 0)
                c.setdefault("proof_status", "unverified")
                c.setdefault("compiler_errors", [])
                normalized.append(c)
            return normalized

    # Fallback to direct OpenAI only if OpenAI was requested or provider was not explicitly set to gemini
    openai_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if provider in (None, "openai") and openai_key.startswith(("sk-", "sk-proj-")):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model=model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "conjectures" in data:
                return data["conjectures"]
            elif isinstance(data, dict):
                return [data]
        except Exception as e:
            print(f"Direct OpenAI generation failed: {e}", file=sys.stderr)

    return []


def generate_fallback_conjectures(strategy: str, seeds: list, count: int):
    """Fallback generator producing valid structured Elementary Number Theory candidate conjectures for testing."""
    timestamp = datetime.datetime.now().strftime("%H%M%S")
    seed_ids = [s["id"] for s in seeds] if seeds else ["KB_NT_001"]

    candidate_templates = [
        {
            "informal_statement": "For any prime p > 3, p^2 - 1 is divisible by 24.",
            "test_variables": [
                {"name": "p", "type": "int", "constraints": "is_prime(p) and p > 3"}
            ],
            "lean4_statement": "theorem prime_sq_sub_one_mod_24 (p : ℕ) (hp : Nat.Prime p) (hgt : p > 3) : 24 ∣ (p^2 - 1)"
        },
        {
            "informal_statement": "For any odd prime p, 2^(p-1) ≡ 1 (mod p).",
            "test_variables": [
                {"name": "p", "type": "int", "constraints": "is_prime(p) and p % 2 != 0"}
            ],
            "lean4_statement": "theorem pow_two_sub_one_mod_prime (p : ℕ) (hp : Nat.Prime p) (hodd : p % 2 = 1) : 2^(p-1) ≡ 1 [MOD p]"
        },
        {
            "informal_statement": "If a and b are coprime positive integers, then a^(Nat.totient b) + b^(Nat.totient a) ≡ 1 (mod a*b) is false in general, but a^(Nat.totient b) ≡ 1 (mod b).",
            "test_variables": [
                {"name": "a", "type": "int", "constraints": "a > 1"},
                {"name": "b", "type": "int", "constraints": "b > 1 and gcd(a,b) == 1"}
            ],
            "lean4_statement": "theorem euler_totient_coprime (a b : ℕ) (h : Nat.Coprime a b) : a ^ (Nat.totient b) ≡ 1 [MOD b]"
        },
        {
            "informal_statement": "For any integer n > 1, the sum of all positive integers less than n and coprime to n is n * φ(n) / 2.",
            "test_variables": [
                {"name": "n", "type": "int", "constraints": "n > 1"}
            ],
            "lean4_statement": "theorem sum_coprime_eq_totient_mul (n : ℕ) (hn : n > 1) : 2 * (Nat.sum_coprime n) = n * Nat.totient n"
        },
        {
            "informal_statement": "For any natural number n, n^5 - n is always divisible by 30.",
            "test_variables": [
                {"name": "n", "type": "int", "constraints": "n >= 0"}
            ],
            "lean4_statement": "theorem pow_five_sub_self_dvd_30 (n : ℕ) : 30 ∣ (n^5 - n)"
        }
    ]

    conjectures = []
    for i in range(min(count, len(candidate_templates))):
        tmpl = candidate_templates[i]
        conj_id = f"CONJ_2026_{timestamp}_{i+1:03d}"
        conjectures.append({
            "conjecture_id": conj_id,
            "generation_strategy": strategy,
            "seed_ids_used": seed_ids,
            "informal_statement": tmpl["informal_statement"],
            "test_variables": tmpl["test_variables"],
            "verification_status": "unverified",
            "counterexample": None,
            "tested_bound": 0,
            "lean4_statement": tmpl["lean4_statement"],
            "proof_status": "unverified",
            "compiler_errors": []
        })

    return conjectures


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="Generate structured candidate conjectures using ChromaDB context retrieval.")
    parser.add_argument("--strategy", type=str, default="rag_retrieval", choices=["rag_retrieval", "from_definitions", "from_examples"], help="Conjecture generation strategy switch")
    parser.add_argument("--query", type=str, default="modular congruences prime squares divisibility", help="Retrieval query for RAG context")
    parser.add_argument("--db_dir", type=str, default="chroma_db", help="ChromaDB vector store directory")
    parser.add_argument("--top_k", type=int, default=3, help="Number of seed context theorems to retrieve")
    parser.add_argument("--count", type=int, default=3, help="Number of candidate conjectures to generate")
    parser.add_argument("--output", type=str, default="conjectures_master.json", help="Output JSON file for generated conjectures")
    parser.add_argument("--append", action="store_true", help="Append conjectures to existing output file if it exists")
    parser.add_argument("--provider", type=str, default="auto", choices=["auto", "gemini", "openai"], help="LLM provider: gemini, openai, or auto")
    parser.add_argument("--model", type=str, default=None, help="LLM model name (e.g. gemini-3.8-flash or gpt-4o-mini)")
    parser.add_argument("--api_key", type=str, default=None, help="Explicit API key for Gemini or OpenAI")

    args = parser.parse_args()

    print(f"Executing conjecture generation [Strategy: {args.strategy}]...")

    # 1. Retrieve RAG context from ChromaDB
    seed_context = []
    if args.strategy == "rag_retrieval":
        seed_context = retrieve_rag_context(args.db_dir, args.query, top_k=args.top_k)
        print(f"Retrieved {len(seed_context)} seed theorems from ChromaDB for query '{args.query}':")
        for s in seed_context:
            print(f"  - [{s['id']}] {s['concept_name']}: {s['informal_statement']}")

    # 2. Generate conjectures via LLM API or structured fallback
    conjectures = []
    prov, detected_key = detect_provider(args.provider if args.provider != "auto" else None, args.api_key) if detect_provider else ("none", None)
    
    if prov != "none":
        try:
            print(f"Connecting to {prov.upper()} API for conjecture generation...")
            prompt = (
                f"Strategy: {args.strategy}\n"
                f"Query Context: {args.query}\n"
                f"Seed Theorems:\n" + json.dumps(seed_context, indent=2) + f"\n"
                f"Generate exactly {args.count} candidate conjectures in Elementary Number Theory. "
                "Ensure each has informal_statement, test_variables with python-executable constraints, and lean4_statement."
            )
            conjectures = generate_llm_conjectures(
                prompt=prompt,
                seed_ids=[s['id'] for s in seed_context],
                strategy=args.strategy,
                count=args.count,
                provider=prov,
                api_key=detected_key,
                model=args.model
            )
        except Exception as e:
            print(f"API call failed: {e}. Falling back to structured heuristic generator.", file=sys.stderr)
            conjectures = []

    if not conjectures:
        if prov == "none":
            print("No Gemini or OpenAI API key found in environment or arguments. Using structured fallback generator for offline testing.")
        else:
            print("Using structured fallback generator.")
        conjectures = generate_fallback_conjectures(args.strategy, seed_context, args.count)

    # 3. Save to output JSON file
    existing_conjectures = []
    if args.append and os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                existing_conjectures = json.load(f)
                if not isinstance(existing_conjectures, list):
                    existing_conjectures = []
        except Exception:
            existing_conjectures = []

    combined = existing_conjectures + conjectures
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print(f"\nGenerated {len(conjectures)} conjectures. Total stored in '{args.output}': {len(combined)}")
    for c in conjectures:
        print(f"\nID: {c['conjecture_id']}")
        print(f"  Informal: {c['informal_statement']}")
        print(f"  Lean 4: {c['lean4_statement']}")


if __name__ == "__main__":
    main()
