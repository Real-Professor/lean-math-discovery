#!/usr/bin/env python3
"""
scripts/run_pipeline.py
End-to-End Orchestrator for AI-Assisted Mathematical Discovery in Lean 4.
Executes the closed-loop multi-stage validation funnel:
  1. Knowledge Base Verification & Vector Context Retrieval
  2. Candidate Conjecture Generation (Gemini API / OpenAI / Fallback)
  3. Automated Counterexample Search & Refutation Routing (SymPy)
  4. Lean 4 Autoformalization & Proof Tactic Search Loop
"""

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Automatically load .env if python-dotenv is present
try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

try:
    from scripts.index_kb import index_knowledge_base
    from scripts.generate_conjectures import (
        retrieve_rag_context,
        generate_llm_conjectures,
        generate_fallback_conjectures,
    )
    from scripts.evaluate_empirical import run_empirical_evaluation
    from scripts.autoformalize import process_autoformalization
    from scripts.llm_client import detect_provider
except ImportError:
    from index_kb import index_knowledge_base
    from generate_conjectures import (
        retrieve_rag_context,
        generate_llm_conjectures,
        generate_fallback_conjectures,
    )
    from evaluate_empirical import run_empirical_evaluation
    from autoformalize import process_autoformalization
    from llm_client import detect_provider


def print_banner(title: str):
    line = "=" * 70
    print(f"\n{line}\n  {title}\n{line}", flush=True)


def print_step(step_num: int, title: str):
    print(f"\n[Stage {step_num}] {title}", flush=True)
    print("-" * 50, flush=True)


def run_pipeline(
    count: int = 3,
    strategy: str = "rag_retrieval",
    query: str = "modular congruences prime squares divisibility",
    kb_path: str = "knowledge_base.jsonl",
    db_dir: str = "chroma_db",
    conjectures_file: str = "conjectures_master.json",
    counterexamples_file: str = "counterexamples_db.json",
    lean_file: str = "math_discovery/MathDiscovery/Theorems.lean",
    working_dir: str = "math_discovery",
    provider: str = "auto",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_prime: int = 10000,
    max_n: int = 1000,
    samples: int = 500,
    tactics: str = "omega,ring,decide,rfl,linarith,aesop",
    append: bool = False,
    verbose: bool = False
):
    start_time = time.time()
    print_banner("CLOSED-LOOP MATHEMATICAL DISCOVERY PIPELINE (LEAN 4)")
    print(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Strategy: {strategy} | Target Conjectures: {count}")
    
    # -------------------------------------------------------------
    # Stage 0: Detect LLM Provider
    # -------------------------------------------------------------
    prov, effective_key = detect_provider(provider if provider != "auto" else None, api_key)
    if prov != "none":
        model_display = model or ("gemini-3.8-flash" if prov == "gemini" else "gpt-4o-mini")
        print(f"LLM Engine: {prov.upper()} ({model_display})")
    else:
        print("LLM Engine: Offline Heuristic Generator (No GEMINI_API_KEY / OPENAI_API_KEY detected)")

    # -------------------------------------------------------------
    # Stage 1: Knowledge Base & Vector Index Check
    # -------------------------------------------------------------
    print_step(1, "Verifying Knowledge Base & ChromaDB Index")
    if not os.path.exists(kb_path):
        print(f"Error: Knowledge base '{kb_path}' not found!", file=sys.stderr)
        return

    # Check if chroma_db needs initial indexing
    if not os.path.exists(db_dir) or not os.listdir(db_dir):
        print(f"ChromaDB store '{db_dir}' not initialized. Running vector indexing...")
        index_knowledge_base(kb_path=kb_path, db_dir=db_dir)
    else:
        print(f"ChromaDB store verified at '{db_dir}'.")

    # -------------------------------------------------------------
    # Stage 2: Hypothesis Generation Pipeline
    # -------------------------------------------------------------
    print_step(2, "Generating Mathematical Candidate Conjectures")
    seed_context = []
    if strategy == "rag_retrieval":
        seed_context = retrieve_rag_context(db_dir, query, top_k=3)
        print(f"Retrieved {len(seed_context)} context seeds for query: \"{query}\"")
        for s in seed_context:
            print(f"  * [{s['id']}] {s['concept_name']}: {s['informal_statement']}")

    conjectures = []
    seed_ids = [s["id"] for s in seed_context] if seed_context else ["KB_NT_001"]

    if prov != "none":
        try:
            prompt = (
                f"Strategy: {strategy}\n"
                f"Query Context: {query}\n"
                f"Seed Theorems:\n" + json.dumps(seed_context, indent=2) + f"\n"
                f"Generate exactly {count} candidate conjectures in Elementary Number Theory. "
                "Ensure each has informal_statement, test_variables with python-executable constraints, and lean4_statement."
            )
            conjectures = generate_llm_conjectures(
                prompt=prompt,
                seed_ids=seed_ids,
                strategy=strategy,
                count=count,
                provider=prov,
                api_key=effective_key,
                model=model
            )
        except Exception as e:
            print(f"LLM generation failed: {e}. Falling back to templates.", file=sys.stderr)
            conjectures = []

    if not conjectures:
        print("Generating candidate conjectures via structured number theory generator...")
        conjectures = generate_fallback_conjectures(strategy, seed_context, count)

    print(f"Successfully formulated {len(conjectures)} candidate conjectures:")
    for idx, c in enumerate(conjectures, 1):
        print(f"  ({idx}) [{c.get('conjecture_id')}] \"{c.get('informal_statement')}\"")

    # Write initial candidates to file
    existing = []
    if append and os.path.exists(conjectures_file):
        try:
            with open(conjectures_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
        except Exception:
            existing = []

    all_conjectures = existing + conjectures
    with open(conjectures_file, "w", encoding="utf-8") as f:
        json.dump(all_conjectures, f, indent=2)

    # -------------------------------------------------------------
    # Stage 3: Automated Counterexample Engine
    # -------------------------------------------------------------
    print_step(3, "Empirical Counterexample Testing (SymPy)")
    print(f"Testing bounds: primes p <= {max_prime}, integers N <= {max_n}, max samples = {samples}")
    run_empirical_evaluation(
        input_file=conjectures_file,
        output_file=conjectures_file,
        counterexamples_file=counterexamples_file,
        max_prime=max_prime,
        max_n=max_n,
        max_samples=samples,
        verbose=verbose
    )

    # Reload updated conjectures
    with open(conjectures_file, "r", encoding="utf-8") as f:
        evaluated_conjectures = json.load(f)

    # -------------------------------------------------------------
    # Stage 4: Lean 4 Autoformalization & Proof Tactic Search
    # -------------------------------------------------------------
    print_step(4, "Lean 4 Autoformalization & Automated Proof Search")
    tactics_list = [t.strip() for t in tactics.split(",") if t.strip()]
    lean_working_dir = working_dir if os.path.exists(working_dir) else None
    lean_out = lean_file if lean_working_dir else "Theorems.lean"

    process_autoformalization(
        input_file=conjectures_file,
        output_file=conjectures_file,
        lean_output_file=lean_out,
        tactics=tactics_list,
        only_plausible=True,
        working_dir=lean_working_dir,
        use_llm=(prov != "none"),
        provider=prov if prov != "none" else None,
        api_key=effective_key,
        model=model,
        verbose=verbose
    )

    # -------------------------------------------------------------
    # Executive Summary & Performance Dashboard
    # -------------------------------------------------------------
    elapsed = time.time() - start_time
    with open(conjectures_file, "r", encoding="utf-8") as f:
        final_conjectures = json.load(f)

    total_candidates = len(final_conjectures)
    plausible_count = sum(1 for c in final_conjectures if c.get("verification_status") == "empirically_plausible")
    refuted_count = sum(1 for c in final_conjectures if c.get("verification_status") == "refuted")
    proved_count = sum(1 for c in final_conjectures if c.get("proof_status") == "proved")
    unproved_count = sum(1 for c in final_conjectures if c.get("proof_status") == "unproved")
    type_err_count = sum(1 for c in final_conjectures if c.get("proof_status") == "type_error")

    print_banner("EXECUTION SUMMARY REPORT")
    print(f"Total Conjectures Processed : {total_candidates}")
    print(f"  * Empirically Plausible   : {plausible_count} ({plausible_count/total_candidates*100:.1f}%)" if total_candidates else "0")
    print(f"  * Refuted (Counterexample): {refuted_count} ({refuted_count/total_candidates*100:.1f}%)" if total_candidates else "0")
    print(f"Lean 4 Verification:")
    print(f"  * Formally Proved         : {proved_count}")
    print(f"  * Valid Syntax (Open)     : {unproved_count}")
    print(f"  * Type/Elaboration Errors : {type_err_count}")
    print(f"Output Artifacts:")
    print(f"  * Conjectures Database    : {os.path.abspath(conjectures_file)}")
    print(f"  * Counterexamples Log     : {os.path.abspath(counterexamples_file)}")
    print(f"  * Lean 4 Formal Theorems  : {os.path.abspath(lean_out)}")
    print(f"Total Pipeline Runtime      : {elapsed:.2f} seconds")
    print("=" * 70 + "\n", flush=True)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="Run the closed-loop mathematical discovery pipeline in Lean 4.")
    parser.add_argument("--count", type=int, default=3, help="Number of candidate conjectures to generate")
    parser.add_argument("--strategy", type=str, default="rag_retrieval", choices=["rag_retrieval", "from_definitions", "from_examples"], help="Conjecture generation strategy switch")
    parser.add_argument("--query", type=str, default="modular congruences prime squares divisibility", help="Retrieval query for RAG context")
    parser.add_argument("--kb_path", type=str, default="knowledge_base.jsonl", help="Path to seed knowledge base JSONL")
    parser.add_argument("--db_dir", type=str, default="chroma_db", help="ChromaDB vector store directory")
    parser.add_argument("--conjectures", type=str, default="conjectures_master.json", help="Path to conjectures master JSON")
    parser.add_argument("--counterexamples", type=str, default="counterexamples_db.json", help="Path to counterexamples DB")
    parser.add_argument("--lean_file", type=str, default="math_discovery/MathDiscovery/Theorems.lean", help="Path to output Lean 4 theorems file")
    parser.add_argument("--working_dir", type=str, default="math_discovery", help="Lean/Lake package directory")
    parser.add_argument("--provider", type=str, default="auto", choices=["auto", "gemini", "openai"], help="LLM provider: gemini, openai, or auto")
    parser.add_argument("--model", type=str, default=None, help="Model name (e.g. gemini-3.8-flash or gpt-4o-mini)")
    parser.add_argument("--api_key", type=str, default=None, help="Explicit API key for Gemini or OpenAI")
    parser.add_argument("--max_prime", type=int, default=10000, help="Maximum prime bound for testing")
    parser.add_argument("--max_n", type=int, default=1000, help="Maximum integer bound for testing")
    parser.add_argument("--samples", type=int, default=500, help="Max variable assignments per conjecture")
    parser.add_argument("--tactics", type=str, default="omega,ring,decide,rfl,linarith,aesop", help="Comma-separated Lean 4 tactics to try")
    parser.add_argument("--append", action="store_true", help="Append new conjectures instead of replacing")
    parser.add_argument("--verbose", action="store_true", help="Print verbose compiler diagnostics and test traces")

    args = parser.parse_args()

    run_pipeline(
        count=args.count,
        strategy=args.strategy,
        query=args.query,
        kb_path=args.kb_path,
        db_dir=args.db_dir,
        conjectures_file=args.conjectures,
        counterexamples_file=args.counterexamples,
        lean_file=args.lean_file,
        working_dir=args.working_dir,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        max_prime=args.max_prime,
        max_n=args.max_n,
        samples=args.samples,
        tactics=args.tactics,
        append=args.append,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
