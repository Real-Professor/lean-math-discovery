# AI-Assisted Mathematical Conjecture Generation & Formal Verification in Lean 4

This repository contains the codebase, verification pipeline, and datasets for the thesis project on automated mathematical discovery, empirical verification, and formal theorem proving in **Elementary Number Theory**.

## 📌 Overview

The system establishes an end-to-end, closed-loop AI pipeline designed to eliminate hallucinations in automated mathematical reasoning by passing candidate conjectures through a multi-stage validation funnel:

1. **Contextual Conjecture Generation**: Domain-grounded generation via structured knowledge retrieval (RAG with ChromaDB).
2. **Quality & Syntax Filtering**: Heuristic checks, domain consistency, and syntactic schema validation.
3. **Empirical Counterexample Testing**: High-throughput falsification testing over large integer domains in Python.
4. **Autoformalization**: Translating verified informal conjectures into strictly typed Lean 4 statements.
5. **Formal Verification in Lean 4**: Automated compilation and tactic-driven proof verification within Lean 4.

For detailed architecture, mathematical targets, and design specifications, refer to [PROJECT_SPEC.md](PROJECT_SPEC.md).

---

## 📁 Repository Structure

```text
├── math_discovery/            # Lean 4 project and verified theorems
│   ├── MathDiscovery/         # Lean source files (Basic.lean, Theorems.lean)
│   ├── lakefile.toml          # Lake build configuration
│   └── lean-toolchain         # Lean version specification
├── scripts/                   # Core Python automation pipeline
│   ├── index_kb.py            # Embeds knowledge base into vector store
│   ├── generate_conjectures.py# LLM-guided conjecture generation
│   ├── evaluate_empirical.py  # Empirical counterexample search
│   └── autoformalize.py       # Autoformalization & Lean verification loop
├── conjectures_master.json    # Master registry of generated conjectures
├── counterexamples_db.json    # Logged counterexamples and falsified candidates
├── knowledge_base.jsonl       # Seed axioms, theorems, and definitions
├── Theorems.lean              # Standalone Lean formalization file
├── thesis_into_doc.pdf        # Thesis introductory documentation
└── PROJECT_SPEC.md            # Detailed system and architecture specifications
```

---

## 🚀 Getting Started

### Prerequisites

- **Python**: 3.10+
- **Lean 4 & Lake**: Installed via `elan` ([Lean installation guide](https://lean-lang.org/lean4/doc/quickstart.html))

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/<your-username>/<repo-name>.git
   cd <repo-name>
   ```

2. **Python Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt  # If requirements.txt is provided
   ```

3. **Build Lean Environment**:
   ```bash
   cd math_discovery
   lake exe cache get  # Fetch mathlib build cache
   lake build
   cd ..
   ```

---

## 🔬 Pipeline Workflow

1. **Index Knowledge Base**:
   ```bash
   python scripts/index_kb.py
   ```
2. **Generate Candidate Conjectures**:
   ```bash
   python scripts/generate_conjectures.py
   ```
3. **Run Empirical Counterexample Search**:
   ```bash
   python scripts/evaluate_empirical.py
   ```
4. **Autoformalize & Verify in Lean 4**:
   ```bash
   python scripts/autoformalize.py
   ```
