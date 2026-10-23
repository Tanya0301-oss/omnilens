#!/usr/bin/env python3
"""
eval/run_eval.py
----------------
OmniLens Evaluation Harness

Runs every question in test_set.json against the live /query endpoint and
writes a structured report to eval/eval_report.md.

Usage::

    # From the repo root with the backend running:
    venv\\Scripts\\python.exe eval/run_eval.py

    # Optional flags:
    venv\\Scripts\\python.exe eval/run_eval.py --url http://127.0.0.1:8000 --top-k 5

Environment:
    Backend must be running at the configured BASE_URL.

Output:
    eval/eval_report.md — human-readable Markdown report.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print(
        "ERROR: 'requests' is not installed.\n"
        "Run: venv\\Scripts\\pip install requests",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_SET_PATH = REPO_ROOT / "eval" / "test_set.json"
REPORT_PATH = REPO_ROOT / "eval" / "eval_report.md"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OmniLens evaluation harness")
    p.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="Base URL of the OmniLens API (default: http://127.0.0.1:8000)",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve per query (default: 5)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP request timeout in seconds (default: 120)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keywords that typically signal the model refused to answer (grounding guard).
_REFUSAL_PHRASES = [
    "not found in",
    "cannot answer",
    "no relevant",
    "do not have",
    "not provided",
    "unable to answer",
    "not mentioned",
    "not available",
    "outside the scope",
    "not covered",
    "no information",
    "cannot find",
    "don't have",
]


def _looks_like_refusal(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in _REFUSAL_PHRASES)


def _query(base_url: str, question: str, top_k: int, timeout: int) -> dict:
    """POST /query with allow_general=false (strict mode) and return the JSON response dict."""
    payload = {"question": question, "top_k": top_k, "allow_general": False}
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            f"{base_url}/query",
            json=payload,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        data["_wall_time_s"] = round(elapsed, 3)
        data["_http_status"] = resp.status_code
        data["_error"] = None
    except requests.exceptions.ConnectionError:
        data = {
            "_error": "CONNECTION_ERROR — is the backend running?",
            "_wall_time_s": None,
            "_http_status": None,
        }
    except requests.exceptions.Timeout:
        data = {
            "_error": f"TIMEOUT after {timeout}s",
            "_wall_time_s": timeout,
            "_http_status": None,
        }
    except requests.exceptions.HTTPError as exc:
        data = {
            "_error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            "_wall_time_s": round(time.perf_counter() - t0, 3),
            "_http_status": exc.response.status_code,
        }
    return data


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _verdict(case: dict, response: dict) -> tuple[str, str]:
    """Return (emoji, description) verdict for a single test case."""
    if response.get("_error"):
        return "❌", f"ERROR — {response['_error']}"

    answer: str = response.get("answer", "")
    citations: list = response.get("cited_chunks") or response.get("citations", [])
    actually_refused = _looks_like_refusal(answer) or response.get("answer_source") == "not_found"
    expected_refusal: bool = case.get("expect_refusal", False)

    if expected_refusal:
        if actually_refused:
            return "✅", "Correctly refused out-of-scope query"
        else:
            return "⚠️", "Expected refusal but model answered — check grounding"
    else:
        if actually_refused:
            return "⚠️", "Model refused but an answer was expected — may lack ingested docs"
        if not answer:
            return "❌", "Empty answer returned"
        if not citations:
            return "⚠️", "Answer present but no citations returned"
        return "✅", f"Answered with {len(citations)} citation(s)"


def generate_report(args: argparse.Namespace, cases: list[dict], results: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    # Header
    lines += [
        "# OmniLens Evaluation Report",
        "",
        f"**Generated**: {now}  ",
        f"**Endpoint**: `{args.url}/query`  ",
        f"**Mode**: Strict mode (`allow_general=false`)  ",
        f"**Top-K**: {args.top_k}  ",
        f"**Questions**: {len(cases)}",
        "",
        "---",
        "",
    ]

    # Summary table
    total = len(cases)
    passed = sum(1 for r in results if r.get("_verdict_emoji") == "✅")
    warned = sum(1 for r in results if r.get("_verdict_emoji") == "⚠️")
    failed = sum(1 for r in results if r.get("_verdict_emoji") == "❌")

    lines += [
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| ✅ Passed | {passed} / {total} |",
        f"| ⚠️ Warnings | {warned} / {total} |",
        f"| ❌ Failed | {failed} / {total} |",
        f"| Pass Rate | {100 * passed / total:.0f}% |",
        "",
        "---",
        "",
        "## Individual Results",
        "",
    ]

    # Individual results
    for case, result in zip(cases, results):
        emoji = result.get("_verdict_emoji", "❓")
        verdict_text = result.get("_verdict_text", "")
        qid = case["id"]
        query = case["query"]
        wall = result.get("_wall_time_s")
        latency_str = f"{wall:.2f}s" if wall is not None else "N/A"
        answer = result.get("answer", "*(no answer)*")
        citations = result.get("citations", [])
        error = result.get("_error")

        lines += [
            f"### {emoji} `{qid}` — {query}",
            "",
            f"**Verdict**: {verdict_text}  ",
            f"**Latency**: {latency_str}  ",
            f"**Expect refusal**: {case.get('expect_refusal', False)}  ",
            f"**Notes**: {case.get('notes', '')}",
            "",
        ]

        if error:
            lines += [f"> ❌ **Error**: `{error}`", ""]
        else:
            # Answer (trimmed for readability)
            trimmed_answer = (answer[:600] + "…") if len(answer) > 600 else answer
            lines += [
                "**Answer**:",
                "",
                f"> {trimmed_answer}",
                "",
            ]
            if citations:
                lines.append("**Citations**:")
                lines.append("")
                for c in citations[:5]:  # cap to 5 per question
                    src = c.get("source_filename", "unknown")
                    page = c.get("page_number", "")
                    page_str = f" p.{page}" if page else ""
                    score = c.get("score", "")
                    score_str = f" (score: {score:.3f})" if isinstance(score, (int, float)) else ""
                    lines.append(f"- `{src}`{page_str}{score_str}")
                lines.append("")

        # Latency breakdown if available
        latency = result.get("latency_ms", {})
        if latency:
            lines.append("**Latency breakdown**:")
            lines.append("")
            lines.append("| Stage | ms |")
            lines.append("|-------|----|")
            for stage, ms in latency.items():
                lines.append(f"| {stage} | {ms} |")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    # Load test set
    if not TEST_SET_PATH.exists():
        print(f"ERROR: test_set.json not found at {TEST_SET_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(TEST_SET_PATH, encoding="utf-8") as fh:
        cases: list[dict] = json.load(fh)

    if not cases:
        print("ERROR: test_set.json is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"OmniLens Eval — {len(cases)} questions → {args.url}/query")
    print("-" * 60)

    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        qid = case["id"]
        query = case["query"]
        print(f"[{i:02d}/{len(cases)}] {qid}: {query[:60]}...", end="", flush=True)
        response = _query(args.url, query, args.top_k, args.timeout)
        emoji, verdict_text = _verdict(case, response)
        response["_verdict_emoji"] = emoji
        response["_verdict_text"] = verdict_text
        results.append(response)
        wall = response.get("_wall_time_s")
        latency_str = f" ({wall:.1f}s)" if wall is not None else ""
        print(f" {emoji}{latency_str}")

    # Write report
    report_md = generate_report(args, cases, results)
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print("-" * 60)
    print(f"Report written to: {REPORT_PATH}")

    passed = sum(1 for r in results if r.get("_verdict_emoji") == "✅")
    print(f"Result: {passed}/{len(cases)} passed")


if __name__ == "__main__":
    main()
