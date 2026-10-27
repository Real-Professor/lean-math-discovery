#!/usr/bin/env python3
"""
scripts/evaluate_empirical.py
Automated empirical counterexample search engine for Elementary Number Theory conjectures.
Uses SymPy and arbitrary-precision integer arithmetic to test candidate conjectures
over bounded integer and prime domains, routing falsified conjectures to counterexamples_db.json
and empirically sound conjectures to the next pipeline stage.
"""

import argparse
import ast
import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
import sympy


class NatNamespace:
    """Namespace allowing Nat.* methods like Nat.totient, Nat.Prime, Nat.gcd in expressions."""
    totient = staticmethod(sympy.totient)
    Prime = staticmethod(sympy.isprime)
    gcd = staticmethod(math.gcd)
    lcm = staticmethod(math.lcm)
    factorial = staticmethod(math.factorial)
    sigma = staticmethod(sympy.divisor_sigma)


def get_safe_eval_globals() -> Dict[str, Any]:
    """Provides a safe dictionary of mathematical functions for constraint and expression evaluation."""
    return {
        "__builtins__": {
            "abs": abs,
            "min": min,
            "max": max,
            "pow": pow,
            "range": range,
            "len": len,
            "int": int,
            "bool": bool,
            "True": True,
            "False": False,
        },
        "isprime": sympy.isprime,
        "is_prime": sympy.isprime,
        "gcd": math.gcd,
        "lcm": math.lcm,
        "totient": sympy.totient,
        "euler_phi": sympy.totient,
        "factorial": math.factorial,
        "divisor_count": sympy.divisor_count,
        "divisor_sigma": sympy.divisor_sigma,
        "sigma": sympy.divisor_sigma,
        "factorint": sympy.factorint,
        "isqrt": math.isqrt,
        "Nat": NatNamespace,
    }


def extract_lean_conclusion(stmt: str) -> str:
    """Extracts the conclusion from a Lean 4 theorem declaration by finding the unnested colon."""
    depth = 0
    for i, ch in enumerate(stmt):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            return stmt[i + 1:].strip()
    return stmt


def clean_python_expr(expr_str: str) -> str:
    """Converts mathematical and Lean 4 syntax into valid Python syntax."""
    s = expr_str.strip()
    
    # Strip enclosing parentheses if the entire string is wrapped in one pair
    while s.startswith("(") and s.endswith(")"):
        # Check if this outer pair encloses the whole string
        depth = 0
        encloses_all = True
        for i in range(len(s) - 1):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    encloses_all = False
                    break
        if encloses_all:
            s = s[1:-1].strip()
        else:
            break

    # Lean function applications without parentheses (e.g. "Nat.totient b" or "totient b")
    s = re.sub(r'\b(?:Nat\.)?totient\s+([a-zA-Z0-9_]+|\([^\)]+\))', r'totient(\1)', s)
    s = re.sub(r'\b(?:Nat\.)?factorial\s+([a-zA-Z0-9_]+|\([^\)]+\))', r'factorial(\1)', s)
    s = re.sub(r'\b(?:Nat\.)?Prime\s+([a-zA-Z0-9_]+|\([^\)]+\))', r'is_prime(\1)', s)
    s = re.sub(r'\b(?:Nat\.)?Coprime\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)', r'gcd(\1, \2) == 1', s)
    s = re.sub(r'\b(?:Nat\.)?gcd\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)', r'gcd(\1, \2)', s)

    # Replace ^ with ** when ^ is used as power
    s = re.sub(r'(?<=[a-zA-Z0-9_\)])\s*\^\s*', '**', s)
    return s


def parse_statement_claim(conjecture: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses a conjecture's claim to determine whether it is divisibility, modular congruence, or equality.
    Returns structured info for evaluating left, right, modulus, and discrepancy.
    """
    if "test_assertion" in conjecture and conjecture["test_assertion"]:
        return {
            "type": "custom",
            "assertion": clean_python_expr(conjecture["test_assertion"])
        }

    lean_stmt = conjecture.get("lean4_statement", "")
    informal_stmt = conjecture.get("informal_statement", "")

    # Look for conclusion part after unnested colon in Lean 4 statement
    conclusion = extract_lean_conclusion(lean_stmt) if lean_stmt else ""

    # Case A: Divisibility in Lean 4 ("d ∣ n" or "d | n")
    div_match = re.search(r'^\s*([^\s∣\|]+)\s*[∣\|]\s*(.+)$', conclusion)
    if div_match:
        divisor_str = clean_python_expr(div_match.group(1))
        dividend_str = clean_python_expr(div_match.group(2))
        return {
            "type": "divisibility",
            "divisor": divisor_str,
            "dividend": dividend_str
        }

    # Case B: Modular Congruence in Lean 4 ("A ≡ B [MOD M]" or "A ≡ B (mod M)")
    mod_match = re.search(r'(.+?)\s*[≡=]\s*(.+?)\s*\[MOD\s*(.+?)\]', conclusion, re.IGNORECASE)
    if not mod_match:
        mod_match = re.search(r'(.+?)\s*[≡=]\s*(.+?)\s*\(mod\s*(.+?)\)', conclusion, re.IGNORECASE)
    if mod_match:
        lhs_str = clean_python_expr(mod_match.group(1))
        rhs_str = clean_python_expr(mod_match.group(2))
        mod_str = clean_python_expr(mod_match.group(3))
        return {
            "type": "congruence",
            "lhs": lhs_str,
            "rhs": rhs_str,
            "modulus": mod_str
        }

    # Case C: Informal statement divisibility (e.g. "p^2 - 1 is divisible by 24")
    inf_div = re.search(r'(.+?)\s+is (?:always )?divisible by\s+([0-9a-zA-Z_\+\-\*\^\(\)]+)', informal_stmt, re.IGNORECASE)
    if inf_div:
        dividend_raw = inf_div.group(1).split(",")[-1].strip()
        dividend_str = clean_python_expr(dividend_raw)
        divisor_str = clean_python_expr(inf_div.group(2).strip(" ."))
        return {
            "type": "divisibility",
            "divisor": divisor_str,
            "dividend": dividend_str
        }

    # Case D: Informal statement congruence (e.g. "2^(n-1) ≡ 1 (mod n)")
    inf_mod = re.search(r'(.+?)\s*[≡=]\s*(.+?)\s*\((?:mod|MOD)\s*([^\)]+)\)', informal_stmt)
    if inf_mod:
        lhs_str = clean_python_expr(inf_mod.group(1).split(",")[-1].strip())
        rhs_str = clean_python_expr(inf_mod.group(2).strip())
        mod_str = clean_python_expr(inf_mod.group(3).strip())
        return {
            "type": "congruence",
            "lhs": lhs_str,
            "rhs": rhs_str,
            "modulus": mod_str
        }

    # Case E: Equality ("A = B")
    if "=" in conclusion:
        parts = conclusion.split("=", 1)
        return {
            "type": "equality",
            "lhs": clean_python_expr(parts[0]),
            "rhs": clean_python_expr(parts[1])
        }

    return {
        "type": "unknown",
        "raw": conclusion or informal_stmt
    }


def eval_modular_term(expr_str: str, scope: Dict[str, Any], mod_val: int) -> int:
    """Evaluates an expression modulo mod_val efficiently using modular exponentiation if applicable."""
    # Check if expression is base ** exp
    m = re.match(r'^\s*([a-zA-Z0-9_\(\)]+)\s*\*\*\s*(.+)$', expr_str)
    if m and mod_val > 0:
        base_val = eval(m.group(1), scope)
        exp_val = eval(m.group(2), scope)
        if exp_val >= 0:
            return pow(int(base_val), int(exp_val), int(mod_val))
    val = eval(expr_str, scope)
    return int(val) % int(mod_val) if mod_val != 0 else int(val)


def evaluate_claim_instance(claim_info: Dict[str, Any], var_env: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Evaluates a single parameter assignment against the parsed claim.
    Returns (is_satisfied, discrepancy_dict).
    """
    safe_globals = get_safe_eval_globals()
    eval_scope = {**safe_globals, **var_env}

    try:
        ctype = claim_info["type"]
        if ctype == "divisibility":
            divisor = eval(claim_info["divisor"], eval_scope)
            dividend = eval(claim_info["dividend"], eval_scope)
            if divisor == 0:
                return False, {
                    "evaluated_left": dividend,
                    "evaluated_right": 0,
                    "modulus": divisor,
                    "discrepancy": f"Division by zero: divisor {claim_info['divisor']} evaluated to 0"
                }
            remainder = dividend % divisor
            if remainder != 0:
                return False, {
                    "evaluated_left": dividend,
                    "evaluated_right": 0,
                    "modulus": divisor,
                    "discrepancy": f"{claim_info['dividend']} = {dividend}, {dividend} % {divisor} = {remainder} != 0"
                }
            return True, None

        elif ctype == "congruence":
            mod_val = eval(claim_info["modulus"], eval_scope)
            if mod_val == 0:
                return False, {
                    "evaluated_left": None,
                    "evaluated_right": None,
                    "modulus": mod_val,
                    "discrepancy": "Modulo by zero"
                }
            
            lhs_rem = eval_modular_term(claim_info["lhs"], eval_scope, mod_val)
            rhs_rem = eval_modular_term(claim_info["rhs"], eval_scope, mod_val)
            
            # For logging, obtain actual values if small or remainder
            try:
                raw_lhs = eval(claim_info["lhs"], eval_scope)
            except Exception:
                raw_lhs = lhs_rem
            try:
                raw_rhs = eval(claim_info["rhs"], eval_scope)
            except Exception:
                raw_rhs = rhs_rem

            if lhs_rem != rhs_rem:
                return False, {
                    "evaluated_left": raw_lhs if isinstance(raw_lhs, (int, float)) and raw_lhs < 10**9 else lhs_rem,
                    "evaluated_right": raw_rhs if isinstance(raw_rhs, (int, float)) and raw_rhs < 10**9 else rhs_rem,
                    "modulus": mod_val,
                    "discrepancy": f"{claim_info['lhs']} % {mod_val} = {lhs_rem} != {rhs_rem}"
                }
            return True, None

        elif ctype == "equality":
            lhs_val = eval(claim_info["lhs"], eval_scope)
            rhs_val = eval(claim_info["rhs"], eval_scope)
            if lhs_val != rhs_val:
                return False, {
                    "evaluated_left": lhs_val,
                    "evaluated_right": rhs_val,
                    "modulus": None,
                    "discrepancy": f"{claim_info['lhs']} ({lhs_val}) != {claim_info['rhs']} ({rhs_val})"
                }
            return True, None

        elif ctype == "custom":
            res = eval(claim_info["assertion"], eval_scope)
            if not bool(res):
                return False, {
                    "evaluated_left": res,
                    "evaluated_right": True,
                    "modulus": None,
                    "discrepancy": f"Assertion '{claim_info['assertion']}' evaluated to False"
                }
            return True, None

        else:
            return True, None

    except Exception as e:
        return False, {
            "evaluated_left": None,
            "evaluated_right": None,
            "modulus": None,
            "discrepancy": f"Evaluation error: {str(e)}"
        }


def generate_variable_stream(
    test_vars: List[Dict[str, Any]],
    max_prime: int = 10000,
    max_n: int = 1000,
    max_samples: int = 500
) -> List[Dict[str, int]]:
    """
    Generates a list of valid parameter assignment dictionaries satisfying the variable constraints.
    """
    safe_globals = get_safe_eval_globals()
    var_names = [v["name"] for v in test_vars]

    # Pre-parse individual constraints
    constraints_clean = [clean_python_expr(v.get("constraints", "")) for v in test_vars]

    # Generate candidate domains for each variable
    domains = {}
    for i, v in enumerate(test_vars):
        vname = v["name"]
        c_str = constraints_clean[i]
        
        # Check if variable represents a prime
        if "is_prime" in c_str or "isprime" in c_str:
            primes = list(sympy.primerange(2, min(max_prime, 100000) + 1))
            domains[vname] = primes
        elif ">" in c_str or ">=" in c_str or "<" in c_str or "<=" in c_str:
            # Natural number or positive integer
            domains[vname] = list(range(1, min(max_n, 500) + 1))
        else:
            # General integer
            domains[vname] = list(range(0, min(max_n, 500) + 1))

    # Construct joint combinations
    assignments = []
    
    if len(var_names) == 1:
        v0 = var_names[0]
        c0 = constraints_clean[0]
        for val in domains[v0]:
            env = {**safe_globals, v0: val}
            try:
                if c0 and not eval(c0, env):
                    continue
                assignments.append({v0: val})
                if len(assignments) >= max_samples:
                    break
            except Exception:
                continue

    elif len(var_names) == 2:
        v0, v1 = var_names[0], var_names[1]
        c0, c1 = constraints_clean[0], constraints_clean[1]
        dom0 = domains[v0][:min(100, len(domains[v0]))]
        dom1 = domains[v1][:min(100, len(domains[v1]))]
        for val0 in dom0:
            env0 = {**safe_globals, v0: val0}
            if c0:
                try:
                    if not eval(c0, env0):
                        continue
                except Exception:
                    continue
            for val1 in dom1:
                env = {**safe_globals, v0: val0, v1: val1}
                if c1:
                    try:
                        if not eval(c1, env):
                            continue
                    except Exception:
                        continue
                assignments.append({v0: val0, v1: val1})
                if len(assignments) >= max_samples:
                    break
            if len(assignments) >= max_samples:
                break
    else:
        # Default sampling for 3+ variables
        v0 = var_names[0]
        for val in domains[v0][:max_samples]:
            env = {v: val for v in var_names}
            assignments.append(env)

    return assignments


def evaluate_conjecture(
    conjecture: Dict[str, Any],
    max_prime: int = 10000,
    max_n: int = 1000,
    max_samples: int = 500,
    verbose: bool = False
) -> Tuple[str, Optional[Dict[str, Any]], int]:
    """
    Evaluates a single conjecture across parameter assignments.
    Returns (status, counterexample_dict, tested_bound).
    """
    test_vars = conjecture.get("test_variables", [])
    if not test_vars:
        return "empirically_plausible", None, 0

    claim_info = parse_statement_claim(conjecture)
    if claim_info["type"] == "unknown":
        if verbose:
            print(f"Warning: Could not automatically parse claim for {conjecture.get('conjecture_id')}")
        return "unverified", None, 0

    assignments = generate_variable_stream(
        test_vars,
        max_prime=max_prime,
        max_n=max_n,
        max_samples=max_samples
    )

    tested_count = 0
    max_tested_bound = 0

    for assign in assignments:
        is_valid, discrepancy = evaluate_claim_instance(claim_info, assign)
        tested_count += 1
        
        # Track maximum tested value
        for val in assign.values():
            if isinstance(val, int) and val > max_tested_bound:
                max_tested_bound = val

        if not is_valid and discrepancy:
            # Build counterexample record matching schema
            falsified_record = {
                **assign,
                "evaluated_left": discrepancy.get("evaluated_left"),
                "evaluated_right": discrepancy.get("evaluated_right"),
                "modulus": discrepancy.get("modulus"),
                "discrepancy": discrepancy.get("discrepancy")
            }
            if verbose:
                print(f"Counterexample found at {assign}: {discrepancy.get('discrepancy')}")
            return "refuted", falsified_record, max_tested_bound

    return "empirically_plausible", None, max_tested_bound


def run_empirical_evaluation(
    input_file: str,
    output_file: str,
    counterexamples_file: str,
    max_prime: int = 10000,
    max_n: int = 1000,
    max_samples: int = 500,
    target_id: Optional[str] = None,
    verbose: bool = False
):
    """Loads conjectures, executes empirical evaluation, updates records, and routes refuted cases."""
    if not os.path.exists(input_file):
        print(f"Error: Conjectures file not found at '{input_file}'", file=sys.stderr)
        return

    with open(input_file, "r", encoding="utf-8") as f:
        conjectures: List[Dict[str, Any]] = json.load(f)

    print(f"Loaded {len(conjectures)} conjectures from '{input_file}'.")
    print(f"Testing bounds: max_prime={max_prime}, max_n={max_n}, max_samples_per_conj={max_samples}")

    counterexamples_db = []
    if os.path.exists(counterexamples_file):
        try:
            with open(counterexamples_file, "r", encoding="utf-8") as f:
                counterexamples_db = json.load(f)
                if not isinstance(counterexamples_db, list):
                    counterexamples_db = []
        except Exception:
            counterexamples_db = []

    existing_counterexample_ids = {c["conjecture_id"] for c in counterexamples_db if "conjecture_id" in c}

    passed_count = 0
    refuted_count = 0

    for c in conjectures:
        cid = c.get("conjecture_id", "")
        if target_id and cid != target_id:
            continue

        print(f"\nEvaluating [{cid}]: \"{c.get('informal_statement')}\"")
        status, counterexample, bound = evaluate_conjecture(
            c,
            max_prime=max_prime,
            max_n=max_n,
            max_samples=max_samples,
            verbose=verbose
        )

        c["verification_status"] = status
        c["counterexample"] = counterexample
        c["tested_bound"] = bound

        if status == "refuted":
            refuted_count += 1
            print(f"  -> REFUTED (falsified at: {counterexample.get('discrepancy')})")
            refuted_record = {
                "conjecture_id": cid,
                "informal_statement": c.get("informal_statement"),
                "falsified_at": counterexample
            }
            if cid not in existing_counterexample_ids:
                counterexamples_db.append(refuted_record)
                existing_counterexample_ids.add(cid)
        elif status == "empirically_plausible":
            passed_count += 1
            print(f"  -> EMPIRICALLY PLAUSIBLE (tested bound: {bound})")
        else:
            print(f"  -> STATUS: {status}")

    # Save updated conjectures
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(conjectures, f, indent=2)
    print(f"\nSaved updated conjectures to '{output_file}'.")

    # Save counterexamples db
    with open(counterexamples_file, "w", encoding="utf-8") as f:
        json.dump(counterexamples_db, f, indent=2)
    print(f"Saved {len(counterexamples_db)} counterexamples to '{counterexamples_file}'.")

    print(f"\nSummary: {passed_count} sound / empirically plausible, {refuted_count} refuted.")


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="Evaluate conjectures empirically with SymPy counterexample search.")
    parser.add_argument("--input", type=str, default="conjectures_master.json", help="Path to input conjectures JSON")
    parser.add_argument("--output", type=str, default="conjectures_master.json", help="Path to output updated JSON")
    parser.add_argument("--counterexamples", type=str, default="counterexamples_db.json", help="Path to counterexamples DB")
    parser.add_argument("--max_prime", type=int, default=10000, help="Maximum prime bound for testing")
    parser.add_argument("--max_n", type=int, default=1000, help="Maximum integer bound for testing")
    parser.add_argument("--samples", type=int, default=500, help="Max variable assignments per conjecture")
    parser.add_argument("--target_id", type=str, default=None, help="Target specific conjecture ID")
    parser.add_argument("--verbose", action="store_true", help="Print verbose evaluation details")

    args = parser.parse_args()

    run_empirical_evaluation(
        input_file=args.input,
        output_file=args.output,
        counterexamples_file=args.counterexamples,
        max_prime=args.max_prime,
        max_n=args.max_n,
        max_samples=args.samples,
        target_id=args.target_id,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
