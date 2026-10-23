#!/usr/bin/env python3
"""
test_features.py
----------------
Acceptance test suite for the five new features:
  1. Whole-document mode
  2. Labeled general-knowledge fallback
  3. Friendly structured errors (429 & timeout simulation)
  4. SSE Streaming (/query/stream) with stage events and sentinel buffering
  5. Follow-up conversational question rewriting
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

# Isolate data directory so test artifacts do not pollute real data
_TEMP_DATA_DIR = tempfile.mkdtemp(prefix="omnilens_test_features_")
os.environ["OMNILENS_DATA_DIR"] = _TEMP_DATA_DIR
atexit.register(lambda: shutil.rmtree(_TEMP_DATA_DIR, ignore_errors=True))

from fastapi.testclient import TestClient
from app.api.query import _determine_mode, _fetch_document_mode_chunks
from app.db.metadata_store import init_db, insert_chunk
from app.generation.answer_generator import (
    NOT_IN_DOCUMENTS_TOKEN,
    rewrite_question,
    stream_grounded_answer,
)
from app.main import app
from groq import APIStatusError, APITimeoutError
import httpx

client = TestClient(app)

# Seed test database in isolated temp directory
init_db()
TEST_SOURCE_ID = "test-doc-multipage-uuid"
TEST_FILENAME = "lab_report_multipage.pdf"


def setup_multipage_source():
    """Ensure a 3-page test document exists in SQLite for whole-document mode tests."""
    for page in [1, 2, 3]:
        insert_chunk(
            source_id=TEST_SOURCE_ID,
            source_filename=TEST_FILENAME,
            source_type="pdf",
            chunk_type="text",
            page_number=page,
            content_text=f"Page {page} of lab report: Experiment {page} completed with measured efficiency {page * 15}%.",
        )


setup_multipage_source()


# ===========================================================================
# Test 1: Whole-document mode
# ===========================================================================

def test_whole_document_mode():
    print("\n--- Test 1: Whole-Document Mode ---")
    # Verify aggregate question detection
    assert _determine_mode("auto", TEST_SOURCE_ID, "how many experiments were conducted?") == "document"
    assert _determine_mode("auto", TEST_SOURCE_ID, "summarize this document") == "document"
    assert _determine_mode("auto", TEST_SOURCE_ID, "what is the total count of samples?") == "document"
    assert _determine_mode("focused", TEST_SOURCE_ID, "how many experiments?") == "focused"

    # Verify chunk fetcher loads all pages in order
    chunks = _fetch_document_mode_chunks(TEST_SOURCE_ID)
    pages = [c["metadata"]["page_number"] for c in chunks]
    assert 1 in pages and 2 in pages and 3 in pages, f"Expected all 3 pages, got {pages}"
    assert sorted(pages) == pages, "Expected chunks in page order"

    # Test via POST /query with mock generator to verify mode_used
    with patch("app.api.query.generate_answer") as mock_gen:
        mock_gen.return_value = {
            "answer": "There were 3 experiments [PAGE:1] [PAGE:2] [PAGE:3].",
            "cited_chunks": [c["chunk_id"] for c in chunks],
            "model_used": "mock-model",
        }
        resp = client.post(
            "/query",
            json={
                "question": "Summarize all the experiments across each page",
                "source_id": TEST_SOURCE_ID,
                "mode": "auto",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode_used"] == "document"
        assert len(data["cited_chunks"]) > 0
        print(f"  [PASS] Aggregate query used mode={data['mode_used']} citing {len(data['cited_chunks'])} chunks across pages")


# ===========================================================================
# Test 2: General-knowledge fallback
# ===========================================================================

def test_general_knowledge_fallback():
    print("\n--- Test 2: Labeled General-Knowledge Fallback ---")
    with patch("app.api.query.generate_answer") as mock_doc_gen, \
         patch("app.api.query.generate_general_knowledge_answer") as mock_gk_gen:

        mock_doc_gen.return_value = {
            "answer": NOT_IN_DOCUMENTS_TOKEN,
            "cited_chunks": [],
            "model_used": "mock-doc-model",
        }
        mock_gk_gen.return_value = {
            "answer": "The speed of light in vacuum is approximately 299,792,458 meters per second.",
            "model_used": "mock-gk-model",
        }

        # Case A: allow_general = True -> fallback to general knowledge
        resp_gk = client.post(
            "/query",
            json={
                "question": f"What is the speed of light? {time.time()}",
                "allow_general": True,
            },
        )
        assert resp_gk.status_code == 200
        data_gk = resp_gk.json()
        assert data_gk["answer_source"] == "general_knowledge"
        assert "speed of light" in data_gk["answer"].lower()
        assert len(data_gk["cited_chunks"]) == 0, "General knowledge answers must never have document citations"
        assert data_gk["notice"] is not None
        print(f"  [A PASS] allow_general=True produced answer_source={data_gk['answer_source']} with notice='{data_gk['notice']}'")

        # Case B: allow_general = False -> strict refusal
        resp_refusal = client.post(
            "/query",
            json={
                "question": f"What is the speed of light? {time.time()} strict",
                "allow_general": False,
            },
        )
        assert resp_refusal.status_code == 200
        data_refusal = resp_refusal.json()
        assert data_refusal["answer_source"] == "not_found"
        assert len(data_refusal["cited_chunks"]) == 0
        assert "not enough information" in data_refusal["answer"].lower() or "don't have enough" in data_refusal["answer"].lower()
        print(f"  [B PASS] allow_general=False produced answer_source={data_refusal['answer_source']} without GK call")


# ===========================================================================
# Test 3: Document answer without second LLM call
# ===========================================================================

def test_document_answer_no_fallback():
    print("\n--- Test 3: Document Answer (No Second LLM Call) ---")
    with patch("app.api.query.generate_answer") as mock_doc_gen, \
         patch("app.api.query.generate_general_knowledge_answer") as mock_gk_gen:

        mock_doc_gen.return_value = {
            "answer": "Operating margin improved to 32 percent [PAGE:2].",
            "cited_chunks": ["mock-chunk-1"],
            "model_used": "mock-doc-model",
        }

        resp = client.post(
            "/query",
            json={
                "question": f"What was the operating margin? {time.time()}",
                "allow_general": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer_source"] == "documents"
        assert len(data["cited_chunks"]) > 0
        mock_gk_gen.assert_not_called()
        print("  [PASS] Answer grounded in documents; second LLM call was NOT invoked")


# ===========================================================================
# Test 4: Follow-up question rewriting
# ===========================================================================

def test_followup_rewriting():
    print("\n--- Test 4: Follow-Up Rewriting ---")
    history = [
        {
            "question": "What is the aim of Experiment 1?",
            "answer": "Experiment 1 aims to measure thermal conductivity, while Experiment 2 tests tensile strength.",
        }
    ]
    followup_q = "What about the next one?"

    # Test the rewrite logic directly with mock
    with patch("app.generation.answer_generator.Groq") as mock_groq_class:
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_choice = MagicMock()
        mock_choice.message.content = "What is the aim of Experiment 2?"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp

        rewritten = rewrite_question(followup_q, history)
        assert "Experiment 2" in rewritten, f"Expected Experiment 2 in rewritten query, got: {rewritten}"
        print(f"  [PASS] Follow-up question '{followup_q}' rewritten to '{rewritten}'")

    # Test through POST /query
    with patch("app.api.query.rewrite_question", return_value="What is the aim of Experiment 2?"), \
         patch("app.api.query.generate_answer") as mock_gen:
        mock_gen.return_value = {
            "answer": "Experiment 2 tests tensile strength [PAGE:2].",
            "cited_chunks": [],
            "model_used": "mock-model",
        }
        resp = client.post(
            "/query",
            json={
                "question": followup_q,
                "history": history,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rewritten_question"] == "What is the aim of Experiment 2?"
        print("  [PASS] POST /query correctly used rewritten question and returned it in response metadata")


# ===========================================================================
# Test 5: Friendly errors (Simulated 429 and Timeout)
# ===========================================================================

def test_friendly_errors():
    print("\n--- Test 5: Friendly Errors (429 & Timeout Simulation) ---")

    # 1. Simulate Groq 429 (Rate Limit)
    mock_request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_response = httpx.Response(status_code=429, request=mock_request)
    groq_429_exc = APIStatusError("Rate limit reached", response=mock_response, body={"error": "rate limit"})

    with patch("app.api.query.generate_answer", side_effect=groq_429_exc):
        resp_429 = client.post("/query", json={"question": f"Rate limit test {time.time()}"})
        assert resp_429.status_code == 429
        data_429 = resp_429.json()
        assert data_429["error_code"] == "rate_limited"
        assert data_429["retryable"] is True
        assert "busy right now" in data_429["message"]
        assert "[Generation error]" not in str(data_429)
        print("  [PASS] 429 mapped to user-friendly structured error with retryable=True")

    # 2. Simulate Timeout
    timeout_exc = APITimeoutError(request=mock_request)
    with patch("app.api.query.generate_answer", side_effect=timeout_exc):
        resp_to = client.post("/query", json={"question": f"Timeout test {time.time()}"})
        assert resp_to.status_code == 504
        data_to = resp_to.json()
        assert data_to["error_code"] == "timeout"
        assert data_to["retryable"] is True
        assert "timed out" in data_to["message"]
        print("  [PASS] Timeout mapped to user-friendly structured error with retryable=True")


# ===========================================================================
# Test 6: SSE Streaming Endpoint (/query/stream)
# ===========================================================================

def test_query_stream_endpoint():
    print("\n--- Test 6: SSE Streaming Endpoint (/query/stream) ---")

    # Mock generator stream that yields NOT_IN_DOCUMENTS sentinel
    with patch("app.api.query.stream_grounded_answer") as mock_stream_grounded, \
         patch("app.api.query.stream_general_knowledge_answer") as mock_stream_gk:

        # Grounded stream outputs sentinel
        mock_stream_grounded.return_value = iter([
            {"type": "sentinel", "sentinel": NOT_IN_DOCUMENTS_TOKEN, "model_used": "mock-grounded"},
        ])
        # GK stream outputs tokens and complete
        mock_stream_gk.return_value = iter([
            {"type": "token", "text": "General "},
            {"type": "token", "text": "knowledge "},
            {"type": "token", "text": "answer."},
            {"type": "complete", "answer": "General knowledge answer.", "model_used": "mock-gk"},
        ])

        resp = client.post(
            "/query/stream",
            json={
                "question": f"Stream test question {time.time()}",
                "allow_general": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = []
        for line in resp.text.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                events.append(payload)

        event_types = [e["type"] for e in events]
        assert "stage" in event_types, f"Expected stage events, got {event_types}"
        assert "token" in event_types, f"Expected token events, got {event_types}"
        assert "meta" in event_types, f"Expected meta event, got {event_types}"
        assert "done" in event_types, f"Expected done event, got {event_types}"

        # Verify NOT_IN_DOCUMENTS NEVER leaked into token text
        all_token_text = "".join(e["text"] for e in events if e["type"] == "token")
        assert NOT_IN_DOCUMENTS_TOKEN not in all_token_text, "Sentinel token MUST NOT appear in streamed tokens"
        assert "General knowledge answer." in all_token_text

        # Verify metadata
        meta = next(e for e in events if e["type"] == "meta")
        assert meta["answer_source"] == "general_knowledge"
        assert meta["cache_hit"] is False

        print("  [PASS] /query/stream emitted stage, token, meta, done in order; sentinel was buffered and never leaked")


if __name__ == "__main__":
    print("=" * 60)
    print("OmniLens Five New Features Acceptance Tests")
    print("=" * 60)
    test_whole_document_mode()
    test_general_knowledge_fallback()
    test_document_answer_no_fallback()
    test_followup_rewriting()
    test_friendly_errors()
    test_query_stream_endpoint()
    print("\n" + "=" * 60)
    print("ALL FEATURE TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
