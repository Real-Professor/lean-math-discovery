```markdown
# Specification: AI-Assisted Mathematical Conjecture Generation and Formal Verification in Lean 4

## 1. Project Overview & Objective

This project implements an end-to-end, closed-loop AI system that automates mathematical discovery, empirical verification, and formal theorem proving. The system targets **Elementary Number Theory** (divisibility, congruences, modular arithmetic, prime distributions, and Diophantine equations).

The objective is to eliminate hallucination in mathematical reasoning by enforcing a multi-stage validation funnel:

1. Contextual conjecture generation using structured knowledge retrieval.
2. Formal syntactic and heuristic quality filtering.
3. Automated empirical testing and counterexample elimination across large integer domains.
4. Autoformalization into typed Lean 4 code.
5. Formal verification via Lean 4 compiler tactics and LLM-guided proof-repair loops.

---

## 2. System Architecture
```

[Knowledge Base (JSONL)] ──► [ChromaDB Vector Store]
│ (Nearest-k Context)
▼
[LLM Generation Stage]
│ (Raw Candidate Conjectures)
▼
[Quality & Syntax Filter]
│ (Valid Schema)
▼
[Python Counterexample Search Engine]
│
┌───────────────────┴───────────────────┐
▼ ▼
[Counterexample Found] [Empirically Sound]
(Log to `refuted_db.json`) │
▼
[Lean 4 Autoformalizer]
│ (Typed Lean 4 Code)
▼
[Proof & Verification Loop]
(LeanDojo / `lake build`)
│
┌───────────┴───────────┐
▼ ▼
[Proof Closed] [Compiler Failure]
(Log Theorem) (Tactic Search Loop)

````

---

## 3. Data Schemas

### A. Seed Knowledge Base Schema (`knowledge_base.jsonl`)
```json
{
  "id": "KB_NT_001",
  "domain": "Elementary Number Theory",
  "subtopic": "Modular Congruences",
  "concept_name": "Fermat's Little Theorem",
  "informal_statement": "If p is prime and a is an integer coprime to p, then a^(p-1) ≡ 1 (mod p).",
  "formal_type": "theorem",
  "lean4_signature": "theorem ZMod.pow_card_sub_one_eq_one {p : ℕ} [Fact p.Prime] {a : ZMod p} (ha : a ≠ 0) : a ^ (p - 1) = 1",
  "lean4_imports": ["Mathlib.Data.ZMod.Basic"],
  "tags": ["prime", "congruence", "exponentiation", "order"],
  "related_ids": []
}

````

### B. Conjecture Record Schema (`conjectures_master.json`)

```json
{
  "conjecture_id": "CONJ_2026_001",
  "generation_strategy": "theorem_neighborhood",
  "seed_ids_used": ["KB_NT_001"],
  "informal_statement": "If p is prime and p > 3, then p^2 ≡ 1 (mod 24).",
  "test_variables": [
    { "name": "p", "type": "int", "constraints": "is_prime(p) and p > 3" }
  ],
  "verification_status": "empirically_plausible",
  "counterexample": null,
  "tested_bound": 100000,
  "lean4_statement": "theorem prime_sq_mod_24 (p : ℕ) (hp : Nat.Prime p) (hgt : p > 3) : p^2 ≡ 1 [MOD 24]",
  "proof_status": "unverified",
  "compiler_errors": []
}
```

### C. Refuted Counterexample Schema (`counterexamples_db.json`)

```json
{
  "conjecture_id": "CONJ_2026_002",
  "informal_statement": "For any odd integer n, 2^(n-1) ≡ 1 (mod n).",
  "falsified_at": {
    "n": 9,
    "evaluated_left": 256,
    "evaluated_right": 1,
    "modulus": 9,
    "discrepancy": "256 % 9 = 4 != 1"
  }
}
```

---

## 4. Conjecture Evaluation Metric

Filter generated conjectures using the composite quality score:

$$C(Q) = w_1 V + w_2 N + w_3 P + w_4 G + w_5 I + w_6 D$$

- $V \in \{0, 1\}$: Syntactic validity and JSON parse rate.
- $N \in [0, 1]$: Non-triviality score (penalizes tautologies like $a + b = b + a$).
- $P \in [0, 1]$: Empirical plausibility (counterexample survival rate over parameter range).
- $G \in [0, 1]$: Generality (number of free parameters, absence of hyper-specific constants).
- $I \in [0, 1]$: Mathematical interestingness (structural connections across subtopics).
- $D \in [0, 1]$: Distance from existing known theorems in the seed database.

---

## 5. Tooling & Technology Stack

| Layer                 | Technology                                              | Role                                                   |
| --------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| **Generation Engine** | Gemini 2.5 Flash / Claude 3.5 Sonnet API                | Conjecture formulation & Lean 4 autoformalization      |
| **Retrieval Engine**  | ChromaDB + `sentence-transformers` (`all-MiniLM-L6-v2`) | Sub-millisecond context retrieval of seed theorems     |
| **Empirical Engine**  | Python 3.11+, SymPy, NumPy                              | Automated brute-force counterexample checking          |
| **Proof Environment** | Lean 4 (`v4.8.0`+), Mathlib, `lake`                     | Interactive theorem prover & kernel-level verification |
| **Prover Interface**  | LeanDojo (`lean-dojo`) or Lean LSP server               | Programmatic tactic submission and feedback capture    |

---

## 6. Implementation Roadmap

### Phase 1: Environment & Corpus Curation

- [x] Initialize Lean 4 project with Mathlib (`lake new math_discovery math`).
- [ ] Curate 25 foundational Elementary Number Theory theorems in `knowledge_base.jsonl`.
- [x] Build vector retrieval script (`scripts/index_kb.py`) using ChromaDB.

### Phase 2: Hypothesis Generation Pipeline

- [x] Implement `scripts/generate_conjectures.py` interfacing with the LLM API.
- [x] Enforce structured JSON schema output containing informal math and execution-ready variable constraints.
- [x] Add baseline switches: `from_definitions`, `from_examples`, and `rag_retrieval`.

### Phase 3: Automated Counterexample Engine

- [x] Build `scripts/evaluate_empirical.py` using SymPy to parse test expressions.
- [x] Run brute-force loops across variable bounds ($N \in [-1000, 1000]$ or primes $p \le 10^5$).
- [x] Auto-route failed items to `counterexamples_db.json` and sound candidates to Lean formalization.

### Phase 4: Lean 4 Autoformalization & Proof Tactic Search

- [x] Build `scripts/autoformalize.py` to translate sound statements into typed Lean syntax.
- [x] Attempt automated proof closure using basic Lean automation: `omega`, `ring`, `linarith`, and `aesop`.
- [x] Connect Lean 4 compiler / Lake diagnostics to capture compilation feedback and errors for iterative repair.

```

---

### Suggested First Prompt in Antigravity

Open the Antigravity agent panel and run:

> *"Inspect `PROJECT_SPEC.md`. Let's begin with Phase 1 and Phase 2. First, create `knowledge_base.jsonl` containing 10 foundational Elementary Number Theory seeds (with Lean 4 signatures and informal descriptions). Then, create `scripts/index_kb.py` using ChromaDB and `scripts/generate_conjectures.py` to query the index and produce structured JSON conjectures."*

```
