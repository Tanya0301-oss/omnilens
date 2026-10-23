#!/usr/bin/env python3
"""
test_llm.py
-----------
Quick smoke-test for the Groq LLM integration in OmniLens.

Usage
~~~~~
  # Default: send a short test prompt and print the reply + latency
  python test_llm.py

  # List all model IDs available on your Groq account
  python test_llm.py --list-models

Environment
~~~~~~~~~~~
Reads GROQ_API_KEY and GROQ_MODEL from .env (via python-dotenv).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure the project root is importable so load_dotenv can find .env
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from groq import Groq, APIStatusError, APIConnectionError, APITimeoutError


_DEFAULT_MODEL = "llama3-70b-8192"
_TEST_PROMPT = (
    "Reply in exactly one sentence: what is the capital of France? "
    "Cite your answer with [CHUNK:test-1]."
)


def get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print(
            "[ERROR] GROQ_API_KEY is not set.\n"
            "        Add it to your .env file: GROQ_API_KEY=<your_key>\n"
            "        Get a free key at https://console.groq.com/keys"
        )
        sys.exit(1)
    return Groq(api_key=api_key, timeout=20)


def list_models(client: Groq) -> None:
    """Print all model IDs available on the configured Groq account."""
    print("Fetching available models from Groq…\n")
    try:
        models = client.models.list()
        ids = sorted(m.id for m in models.data)
        print(f"{'Model ID':<45}  {'Object'}")
        print("-" * 60)
        for mid in ids:
            print(f"  {mid}")
        print(f"\n{len(ids)} model(s) found.")
        print(
            "\nSet GROQ_MODEL=<model_id> in your .env to use a specific model."
        )
    except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
        print(f"[ERROR] Could not list models: {exc}")
        sys.exit(1)


def run_test(client: Groq, model: str) -> None:
    """Send a short test prompt and print the reply + latency."""
    print(f"Testing Groq API…")
    print(f"  Model : {model}")
    print(f"  Prompt: {_TEST_PROMPT}\n")

    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant.",
                },
                {
                    "role": "user",
                    "content": _TEST_PROMPT,
                },
            ],
            temperature=0.1,
            max_tokens=128,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        reply = (response.choices[0].message.content or "").strip()

        print("=" * 60)
        print("SUCCESS")
        print("=" * 60)
        print(f"Reply   : {reply}")
        print(f"Latency : {elapsed_ms} ms")
        print(f"Model   : {response.model}")
        tokens_in = getattr(response.usage, "prompt_tokens", "?")
        tokens_out = getattr(response.usage, "completion_tokens", "?")
        print(f"Tokens  : {tokens_in} in / {tokens_out} out")

    except APIStatusError as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        status = exc.status_code
        print(f"[FAIL] HTTP {status} after {elapsed_ms} ms")
        if status == 401:
            print("  → Groq API key is invalid or missing. Check GROQ_API_KEY in .env.")
        elif status in (400, 404):
            print(
                f"  → Model '{model}' is not available on your Groq account.\n"
                "     Run:  python test_llm.py --list-models"
            )
        elif status == 429:
            print("  → Groq rate limit reached. Try again in a moment.")
        else:
            print(f"  → {exc}")
        sys.exit(1)

    except (APIConnectionError, APITimeoutError) as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        print(f"[FAIL] Connection/timeout error after {elapsed_ms} ms: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Groq API connection used by OmniLens."
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all model IDs available on your Groq account and exit.",
    )
    args = parser.parse_args()

    client = get_client()
    model = os.environ.get("GROQ_MODEL", "").strip() or _DEFAULT_MODEL

    if args.list_models:
        list_models(client)
    else:
        run_test(client, model)


if __name__ == "__main__":
    main()
