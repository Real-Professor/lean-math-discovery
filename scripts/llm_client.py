#!/usr/bin/env python3
"""
scripts/llm_client.py
Unified LLM client interface for Gemini API (google-genai) and OpenAI API.
Supports automatic provider selection, .env variable loading, JSON response parsing,
and text generation for mathematical conjecture formulation and Lean 4 autoformalization.
"""

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Try loading .env if python-dotenv is available
try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass


def detect_provider(preferred: Optional[str] = None, api_key: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Detects which LLM provider to use based on preferences and environment variables.
    Returns (provider_name, effective_api_key).
    Provider names: 'gemini', 'openai', or 'none'.
    """
    gemini_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai_key = api_key or os.environ.get("OPENAI_API_KEY")

    if preferred:
        pref = preferred.lower().strip()
        if pref in ("gemini", "google") and gemini_key:
            return "gemini", gemini_key
        if pref == "openai" and openai_key:
            return "openai", openai_key
        if pref in ("gemini", "google", "openai"):
            # Preferred was specified but key wasn't in standard env
            key = api_key or os.environ.get(f"{pref.upper()}_API_KEY")
            return pref, key

    # Auto-detection priority: Gemini first (primary per spec), then OpenAI
    if gemini_key:
        return "gemini", gemini_key
    if openai_key:
        return "openai", openai_key

    return "none", None


def extract_json_from_text(text: str) -> Any:
    """Safely extracts JSON object or array from markdown text blocks or raw string."""
    text = text.strip()
    
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Match markdown code block ```json ... ``` or ``` ... ```
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except Exception:
            pass

    # Match outer brackets [ ... ] or { ... }
    arr_match = re.search(r'(\[[\s\S]*\])', text)
    if arr_match:
        try:
            return json.loads(arr_match.group(1))
        except Exception:
            pass

    obj_match = re.search(r'(\{[\s\S]*\})', text)
    if obj_match:
        try:
            return json.loads(obj_match.group(1))
        except Exception:
            pass

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}...")


DEFAULT_GEMINI_FALLBACKS = ["gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


def generate_json(
    prompt: str,
    system_instruction: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.4
) -> Tuple[Optional[Any], str]:
    """
    Generates a structured JSON response using either Gemini or OpenAI API.
    Includes automatic retry and fallback handling for 503 high-demand spikes.
    Returns (parsed_json_data, provider_used).
    """
    prov, key = detect_provider(provider, api_key)

    if prov == "gemini":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key) if key else genai.Client()
            primary_model = model or "gemini-3.8-flash"
            candidate_models = [primary_model] + [m for m in DEFAULT_GEMINI_FALLBACKS if m != primary_model]

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=temperature,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )

            last_err = None
            for m in candidate_models:
                for attempt in range(2):
                    try:
                        response = client.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=config
                        )
                        data = extract_json_from_text(response.text)
                        return data, f"gemini ({m})"
                    except Exception as e:
                        last_err = e
                        err_str = str(e)
                        # If 503 high demand or 429 rate limit, sleep briefly and retry
                        if "503" in err_str or "429" in err_str or "demand" in err_str.lower():
                            if attempt == 0:
                                print(f"Gemini model {m} is busy (503/429). Retrying in 2 seconds...", file=sys.stderr)
                                time.sleep(2)
                                continue
                        # Non-retryable error (e.g. 404) or second attempt failed, break to next model
                        break

            print(f"Gemini API call failed after retries/fallbacks: {last_err}", file=sys.stderr)
            return None, "gemini_error"
        except Exception as e:
            print(f"Gemini API initialization failed: {e}", file=sys.stderr)
            return None, "gemini_error"

    elif prov == "openai":
        try:
            from openai import OpenAI

            client = OpenAI(api_key=key) if key else OpenAI()
            model_name = model or "gpt-4o-mini"

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=temperature
            )
            content = response.choices[0].message.content or ""
            data = extract_json_from_text(content)
            return data, f"openai ({model_name})"
        except Exception as e:
            print(f"OpenAI API call failed: {e}", file=sys.stderr)
            return None, "openai_error"

    return None, "none"


def generate_text(
    prompt: str,
    system_instruction: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2
) -> Tuple[Optional[str], str]:
    """
    Generates text output using either Gemini or OpenAI API.
    Includes automatic retry and fallback handling for 503 high-demand spikes.
    Returns (raw_text, provider_used).
    """
    prov, key = detect_provider(provider, api_key)

    if prov == "gemini":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key) if key else genai.Client()
            primary_model = model or "gemini-3.8-flash"
            candidate_models = [primary_model] + [m for m in DEFAULT_GEMINI_FALLBACKS if m != primary_model]

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )

            last_err = None
            for m in candidate_models:
                for attempt in range(2):
                    try:
                        response = client.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=config
                        )
                        text = (response.text or "").strip()
                        text = re.sub(r'^```(?:lean4?|lean)?', '', text).strip()
                        text = re.sub(r'```$', '', text).strip()
                        return text, f"gemini ({m})"
                    except Exception as e:
                        last_err = e
                        err_str = str(e)
                        if "503" in err_str or "429" in err_str or "demand" in err_str.lower():
                            if attempt == 0:
                                print(f"Gemini model {m} is busy (503/429). Retrying in 2 seconds...", file=sys.stderr)
                                time.sleep(2)
                                continue
                        break

            print(f"Gemini API call failed after retries/fallbacks: {last_err}", file=sys.stderr)
            return None, "gemini_error"
        except Exception as e:
            print(f"Gemini API initialization failed: {e}", file=sys.stderr)
            return None, "gemini_error"

    elif prov == "openai":
        try:
            from openai import OpenAI

            client = OpenAI(api_key=key) if key else OpenAI()
            model_name = model or "gpt-4o-mini"

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature
            )
            text = (response.choices[0].message.content or "").strip()
            text = re.sub(r'^```(?:lean4?|lean)?', '', text).strip()
            text = re.sub(r'```$', '', text).strip()
            return text, f"openai ({model_name})"
        except Exception as e:
            print(f"OpenAI API call failed: {e}", file=sys.stderr)
            return None, "openai_error"

    return None, "none"
