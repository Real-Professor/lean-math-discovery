#!/usr/bin/env python3
"""
scripts/autoformalize.py
Phase 4: Autoformalize sound mathematical conjectures into typed Lean 4 code
and execute an automated proof tactic search loop using basic Lean 4 automation
(omega, decide, rfl, ring, linarith, aesop). Captures compilation diagnostics
and updates conjectures_master.json.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from scripts.llm_client import generate_text, detect_provider
except ImportError:
    try:
        from llm_client import generate_text, detect_provider
    except ImportError:
        generate_text = None
        detect_provider = None


DEFAULT_IMPORTS = [
    "import Mathlib.Data.Nat.Basic",
    "import Mathlib.Data.Nat.Prime.Basic",
    "import Mathlib.Data.Nat.ModEq",
    "import Mathlib.Data.Nat.Totient",
    "import Mathlib.Tactic.Ring",
    "import Mathlib.Tactic.Linarith",
]

CORE_FALLBACK_HEADER = """
-- Core Lean 4 definitions fallback when Mathlib is not in path
abbrev ℕ := Nat
def Nat.Prime (p : Nat) : Prop := p > 1 ∧ ∀ m, m ∣ p → m = 1 ∨ m = p
def Nat.ModEq (n a b : Nat) : Prop := a % n = b % n
notation:50 a " ≡ " b " [MOD " n "]" => Nat.ModEq n a b
opaque Nat.totient (n : Nat) : Nat
"""


def load_conjectures(filepath: str) -> List[Dict[str, Any]]:
    """Loads conjecture records from a JSON file."""
    if not os.path.exists(filepath):
        print(f"Error: Conjectures file not found: {filepath}", file=sys.stderr)
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_conjectures(conjectures: List[Dict[str, Any]], filepath: str):
    """Saves conjecture records to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(conjectures, f, indent=2)
    print(f"Updated conjectures saved to '{filepath}'.")


def run_lean_checker(lean_source: str, working_dir: Optional[str] = None, timeout: int = 90) -> Tuple[int, List[Dict[str, Any]], str]:
    """
    Invokes the Lean 4 compiler on the provided source code string with --json output.
    Returns (return_code, diagnostic_messages_list, raw_stderr).
    """
    if working_dir and os.path.exists(working_dir):
        temp_dir = os.path.abspath(working_dir)
        temp_lean_path = os.path.join(temp_dir, f"_temp_eval_{os.getpid()}.lean")
        with open(temp_lean_path, "w", encoding="utf-8") as f:
            f.write(lean_source)
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as f:
            f.write(lean_source)
            temp_lean_path = os.path.abspath(f.name)

    try:
        cmd = ["lean", "--json", temp_lean_path]
        
        # If a lakefile exists in working_dir, execute inside lake env using cwd
        if working_dir and (os.path.exists(os.path.join(working_dir, "lakefile.toml")) or os.path.exists(os.path.join(working_dir, "lakefile.lean"))):
            cmd = ["lake", "env", "lean", "--json", temp_lean_path]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.path.abspath(working_dir) if working_dir else os.getcwd(),
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return 1, [{"severity": "error", "data": f"Compilation timed out after {timeout}s"}], "Timeout"

        messages = []
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                messages.append(msg)
            except json.JSONDecodeError:
                pass

        return proc.returncode, messages, proc.stderr
    finally:
        try:
            if os.path.exists(temp_lean_path):
                os.remove(temp_lean_path)
        except Exception:
            pass


def check_mathlib_available(working_dir: Optional[str] = None) -> bool:
    """Checks whether Mathlib imports are accessible in the current Lean environment."""
    if not working_dir or not os.path.exists(working_dir):
        return False
    pkg_mathlib = os.path.join(working_dir, ".lake", "packages", "mathlib")
    if not os.path.exists(pkg_mathlib):
        return False
    test_code = "import Mathlib.Data.Nat.Basic\n#check Nat\n"
    ret, msgs, _ = run_lean_checker(test_code, working_dir=working_dir, timeout=60)
    has_error = any(m.get("severity") == "error" for m in msgs)
    return ret == 0 and not has_error


def clean_statement_syntax(stmt: str) -> str:
    """Normalizes whitespace and strips trailing proof blocks or comments from a Lean 4 statement."""
    s = stmt.strip()
    # Strip any trailing := by ... or := sorry
    s = re.sub(r':=\s*(?:by\s+.*|sorry.*)$', '', s, flags=re.DOTALL).strip()
    return s


def autoformalize_with_llm(
    conjecture: Dict[str, Any],
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    few_shot_seeds: Optional[List[Dict[str, Any]]] = None
) -> Optional[str]:
    """
    Translates an informal mathematical statement into typed Lean 4 theorem declaration using LLM API (Gemini or OpenAI).
    """
    informal = conjecture.get("informal_statement", "")
    test_vars = conjecture.get("test_variables", [])

    system_instruction = (
        "You are an expert formal mathematician specializing in Lean 4 and Mathlib. "
        "Translate informal Elementary Number Theory conjectures into valid Lean 4 theorem signatures. "
        "Output ONLY the theorem declaration line without markdown or explanations, e.g. "
        "'theorem prime_example (p : ℕ) (hp : Nat.Prime p) : ...' "
        "Do NOT include proofs, ':= by', or 'sorry'."
    )

    prompt = (
        f"Translate the following informal Elementary Number Theory conjecture into a single, valid Lean 4 theorem signature.\n"
        f"Informal Statement: {informal}\n"
        f"Test Variables: {json.dumps(test_vars)}\n"
    )

    if few_shot_seeds:
        prompt += "\nExamples from Knowledge Base:\n"
        for s in few_shot_seeds[:3]:
            prompt += f"- Informal: {s.get('informal_statement')}\n  Lean 4: {s.get('lean4_signature')}\n"

    if generate_text:
        res, used_prov = generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            provider=provider,
            api_key=api_key,
            model=model,
            temperature=0.0
        )
        if res:
            print(f"  Autoformalized with {used_prov}")
            return clean_statement_syntax(res)

    openai_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if provider in (None, "openai") and openai_key.startswith(("sk-", "sk-proj-")):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model=model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            content = resp.choices[0].message.content.strip()
            content = re.sub(r'^```(?:lean4?|lean)?', '', content).strip()
            content = re.sub(r'```$', '', content).strip()
            return clean_statement_syntax(content)
        except Exception as e:
            print(f"Warning: LLM autoformalization call failed: {e}", file=sys.stderr)
    return None


def attempt_proof_tactics(
    statement: str,
    tactics: List[str],
    use_mathlib: bool = True,
    working_dir: Optional[str] = None,
    verbose: bool = False
) -> Tuple[str, Optional[str], List[str]]:
    """
    Attempts to close the proof of a theorem statement using candidate tactics.
    Returns (status, proof_script, list_of_compiler_errors).
    Statuses: 'proved', 'unproved', 'type_error'.
    """
    stmt_clean = clean_statement_syntax(statement)
    header = "\n".join(DEFAULT_IMPORTS) + "\n\n" if use_mathlib else CORE_FALLBACK_HEADER + "\n\n"

    # Step 1: Syntactic & Type Elaboration check using 'sorry'
    test_sorry_source = f"{header}{stmt_clean} := by\n  sorry\n"
    ret, msgs, stderr = run_lean_checker(test_sorry_source, working_dir=working_dir)

    errors = [m.get("data", "") for m in msgs if m.get("severity") == "error"]
    if errors or ret != 0:
        if not errors:
            errors = [m.get("data", "") for m in msgs if m.get("data")]
            if not errors and stderr:
                errors = [stderr.strip()]
            if not errors:
                errors = [f"Compilation failed with exit code {ret}"]
        if verbose:
            print(f"  Elaboration/Type Error: {errors}", flush=True)
        return "type_error", None, errors

    # Step 2: Proof closure tactic search loop
    for tac in tactics:
        if verbose:
            print(f"  Attempting tactic: '{tac}'...", flush=True)
        candidate_source = f"{header}{stmt_clean} := by\n  {tac}\n"
        c_ret, c_msgs, _ = run_lean_checker(candidate_source, working_dir=working_dir)
        c_errors = [m.get("data", "") for m in c_msgs if m.get("severity") == "error"]
        c_warnings = [m.get("data", "") for m in c_msgs if m.get("severity") == "warning" and "sorry" in m.get("data", "")]

        # Proved if clean exit with no errors and no sorry warnings
        if c_ret == 0 and not c_errors and not c_warnings:
            if verbose:
                print(f"  -> Proof closed with tactic: 'by {tac}'", flush=True)
            return "proved", f"by {tac}", []

    # Step 3: Could not close proof, but statement is syntactically sound
    if verbose:
        print("  -> Statement is syntactically sound, but tactics did not close the proof.", flush=True)
    return "unproved", "by sorry", []


def process_autoformalization(
    input_file: str,
    output_file: str,
    lean_output_file: str,
    tactics: List[str],
    only_plausible: bool = True,
    target_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    use_llm: bool = False,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    verbose: bool = False
):
    """Orchestrates Phase 4: autoformalization and proof verification loop."""
    conjectures = load_conjectures(input_file)
    if not conjectures:
        return

    print(f"Loaded {len(conjectures)} conjectures from '{input_file}'.", flush=True)
    mathlib_ready = check_mathlib_available(working_dir=working_dir)
    print(f"Lean 4 Environment: Mathlib available = {mathlib_ready}", flush=True)

    proved_count = 0
    unproved_count = 0
    type_err_count = 0

    lean_file_entries = []

    for c in conjectures:
        cid = c.get("conjecture_id", "")
        if target_id and cid != target_id:
            continue

        status_emp = c.get("verification_status", "")
        if only_plausible and status_emp != "empirically_plausible":
            continue

        print(f"\nProcessing [{cid}]: \"{c.get('informal_statement')}\"", flush=True)

        # Obtain or refine Lean 4 statement
        lean_stmt = c.get("lean4_statement")
        if (not lean_stmt or use_llm) and use_llm:
            print("  Querying LLM for autoformalization...", flush=True)
            new_stmt = autoformalize_with_llm(
                c,
                provider=provider,
                api_key=api_key,
                model=model
            )
            if new_stmt:
                lean_stmt = new_stmt
                c["lean4_statement"] = new_stmt
                print(f"  Autoformalized: {lean_stmt}", flush=True)

        if not lean_stmt:
            print(f"  Skipping [{cid}]: No Lean 4 statement available.", flush=True)
            continue

        # Execute proof tactic search loop
        p_status, proof_script, errors = attempt_proof_tactics(
            lean_stmt,
            tactics=tactics,
            use_mathlib=mathlib_ready,
            working_dir=working_dir,
            verbose=verbose
        )

        c["proof_status"] = p_status
        c["proof_script"] = proof_script or "by sorry"
        c["compiler_errors"] = errors

        if p_status == "proved":
            proved_count += 1
            print(f"  -> RESULT: PROVED ({proof_script})", flush=True)
        elif p_status == "unproved":
            unproved_count += 1
            print("  -> RESULT: UNPROVED (valid syntax, proof left as sorry)", flush=True)
        else:
            type_err_count += 1
            print(f"  -> RESULT: TYPE/ELABORATION ERROR: {errors[:1]}", flush=True)

        # Add to output Lean document
        lean_file_entries.append({
            "id": cid,
            "informal": c.get("informal_statement", ""),
            "statement": clean_statement_syntax(lean_stmt),
            "script": c["proof_script"]
        })

    # Save updated master JSON
    save_conjectures(conjectures, output_file)

    # Write out verified theorems Lean 4 module
    header = "\n".join(DEFAULT_IMPORTS) + "\n\n" if mathlib_ready else CORE_FALLBACK_HEADER + "\n\n"
    lean_content = f"{header}/--\n  Generated by AI Mathematical Conjecture Formalizer\n  Target Domain: Elementary Number Theory\n--/\n\n"
    for entry in lean_file_entries:
        lean_content += f"/--\n  ID: {entry['id']}\n  Informal: {entry['informal']}\n--/\n"
        lean_content += f"{entry['statement']} := {entry['script']}\n\n"

    os.makedirs(os.path.dirname(os.path.abspath(lean_output_file)), exist_ok=True)
    with open(lean_output_file, "w", encoding="utf-8") as f:
        f.write(lean_content)
    print(f"Exported {len(lean_file_entries)} autoformalized theorems to '{lean_output_file}'.")

    print(f"\nPhase 4 Summary: {proved_count} proved, {unproved_count} sound syntax unproved, {type_err_count} type errors.")


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="Autoformalize sound conjectures into Lean 4 and execute proof tactic search.")
    parser.add_argument("--input", type=str, default="conjectures_master.json", help="Path to input conjectures JSON")
    parser.add_argument("--output", type=str, default="conjectures_master.json", help="Path to output updated JSON")
    parser.add_argument("--lean_file", type=str, default="math_discovery/MathDiscovery/Theorems.lean", help="Path to output Lean 4 theorems file")
    parser.add_argument("--working_dir", type=str, default="math_discovery", help="Lean/Lake package directory")
    parser.add_argument("--all", action="store_true", help="Process all conjectures instead of only empirically plausible")
    parser.add_argument("--use_llm", action="store_true", help="Use LLM API to autoformalize or re-formalize statements")
    parser.add_argument("--target_id", type=str, default=None, help="Target specific conjecture ID")
    parser.add_argument("--tactics", type=str, default="omega,ring,decide,rfl,linarith,aesop", help="Comma-separated proof tactics to try")
    parser.add_argument("--provider", type=str, default="auto", choices=["auto", "gemini", "openai"], help="LLM provider: gemini, openai, or auto")
    parser.add_argument("--model", type=str, default=None, help="LLM model name (e.g. gemini-3.8-flash or gpt-4o-mini)")
    parser.add_argument("--api_key", type=str, default=None, help="Explicit API key for Gemini or OpenAI")
    parser.add_argument("--verbose", action="store_true", help="Print verbose compiler diagnostics")

    args = parser.parse_args()

    tactics_list = [t.strip() for t in args.tactics.split(",") if t.strip()]

    # If math_discovery directory does not exist, use current directory as working dir
    working_dir = args.working_dir if os.path.exists(args.working_dir) else None
    lean_out = args.lean_file if working_dir else "Theorems.lean"

    process_autoformalization(
        input_file=args.input,
        output_file=args.output,
        lean_output_file=lean_out,
        tactics=tactics_list,
        only_plausible=not args.all,
        target_id=args.target_id,
        working_dir=working_dir,
        use_llm=args.use_llm,
        provider=args.provider if args.provider != "auto" else None,
        api_key=args.api_key,
        model=args.model,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
