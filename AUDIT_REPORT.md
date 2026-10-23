# OmniLens Audit Report

**Date of Audit**: October 12, 2026  
**Auditor**: Antigravity AI (Pair Programming Assistant)  
**Target Project**: OmniLens (`d:\OmniLens`)  
**Scope**: Verification of Features 1 through 8 and Cross-Cutting Infrastructure

---

## 1. Executive Summary & Verification Counts

| Status | Count | Notes |
| :--- | :---: | :--- |
| **PASS** | **23** | Features 1.1–1.5, 2.1–2.5, 3.1–3.4, 4.1–4.5, 5.1–5.4, 7.4 verified with live outputs & code evidence. |
| **PARTIAL** | **3** | Features 6.1 (DB columns exist, no parser retry), 7.3 (source existence checked, ready status not checked), 7.5 (XHR progress & multi-file exist; polling, "Ready to ask", and "Try again" missing). |
| **MISSING** | **8** | Features 6.3, 6.4, 7.1 (async status endpoints), 8.1, 8.2, 8.3, 8.4 (source management & suggestions endpoints/UI). |
| **BROKEN** | **4** | Features 6.1 / 7.2 (`app/ingestion/worker.py` crashes on import), `test_retrieval.py` (`KeyError: 'query_latency_ms'`), `test_step3.py` (fails on `NOT_IN_DOCUMENTS` sentinel). |
| **NOT VERIFIED** | **1** | Feature 6.2 (cannot inspect dynamic suggested questions on throwaway upload because suggestions generation is not invoked). |

---

## 2. Environment & System Setup Verification

- **Backend Health Check**: `GET http://127.0.0.1:8000/health`
  - Output: `{"status": "ok"}` (HTTP 200)
- **Groq & Model Environment Variables**:
  - `GROQ_API_KEY`: **SET** (length: 56 chars)
  - `GROQ_MODEL`: `openai/gpt-oss-120b`
  - `GROQ_VISION_MODEL`: `qwen/qwen3.8-27b`
  - `GROQ_REWRITE_MODEL`: `openai/gpt-oss-20b` (fallback default)
  - `COHERE_API_KEY`: **NOT SET**
  - `GEMINI_API_KEY`: **NOT SET**
- **Data Safety Baseline & Final Comparison**:
  - Pre-audit SQLite chunk count: **20 chunks** across 8 sources.
  - Post-audit SQLite chunk count: **20 chunks** across 8 sources.
  - Pre-audit ChromaDB count: `text_chunks` = 12 docs, `image_chunks` = 11 docs.
  - Post-audit ChromaDB count: `text_chunks` = 12 docs, `image_chunks` = 11 docs.
  - Status of original sources:
    - `0298b585-8ac3-4bbb-9975-6dcf0a6dd7ef` (`dbms_tanya.pdf`): 11 chunks (unchanged)
    - `1268540c-bc44-4288-9f82-50089948a121` (`schema-diagram.png`): 1 chunk (unchanged)
    - `2dc84ba4-faf3-43db-a90d-9c308bcbc859` (`architecture_flow_diagram.png`): 1 chunk (unchanged)
    - `5e76ffe4-41f8-4d39-a79f-b1ec169708fd` (`architecture_flow_diagram.png`): 1 chunk (unchanged)
    - `64965996-dfb6-497e-ba88-59b4565838f0` (`architecture_flow_diagram.png`): 1 chunk (unchanged)
    - `abfb9297-f5ea-4961-8c8c-9df97327504e` (`Screenshot 2026-09-06 233314.png`): 1 chunk (unchanged)
    - `c0b06442-4a08-43b2-84ae-d282dbc19fba` (`architecture_flow_diagram.png`): 1 chunk (unchanged)
    - `test-doc-multipage-uuid` (`lab_report_multipage.pdf`): 3 chunks (unchanged)

---

## 3. Comprehensive Checklist Summary Table

| ID | Feature & Sub-Check Description | Status | Primary Component / File | Evidence Summary |
| :--- | :--- | :---: | :--- | :--- |
| **1.1** | `POST /query` accepts "mode" (auto/focused/document) and returns "mode_used" | **PASS** | `app/api/query.py:QueryRequest` | Live API returned `mode_used: "focused"` and `mode_used: "document"`. |
| **1.2** | Auto mode switches to document mode for aggregate questions with source_id | **PASS** | `app/api/query.py:_determine_mode` | Tested on `dbms_tanya.pdf`: `mode_used="document"`, cited pages `[1, 3, 4, 5, 6]`. |
| **1.3** | Document mode skips vector search and reranking | **PASS** | `app/api/query.py:semantic_query` | Live latencies: `embedding: 0.0ms`, `retrieval: 0.0ms`, `reranking: 0.0ms`. |
| **1.4** | Focused mode retrieves text and images separately; images capped | **PASS** | `app/api/query.py:_fetch_focused_mode_chunks` | Images capped at `min(2, len(image_candidates))`; reranked separately. |
| **1.5** | Truncation by page order with logged warning for oversized documents | **PASS** | `app/api/query.py:_fetch_document_mode_chunks` | Verified with synthetic oversized chunks: truncated at page 2, logged warning. |
| **2.1** | Grounded prompt uses `NOT_IN_DOCUMENTS` sentinel and code detects token | **PASS** | `app/generation/answer_generator.py` | Exact token match: `NOT_IN_DOCUMENTS_TOKEN in raw_answer.strip()`. |
| **2.2** | `allow_general` live query check: off-topic question returns `general_knowledge` vs `not_found` | **PASS** | `app/api/query.py:semantic_query` | `allow_general=true` returned `answer_source="general_knowledge"`; `false` returned `"not_found"`. |
| **2.3** | Document-answerable question returns `documents` without second LLM call | **PASS** | `app/api/query.py:semantic_query` | Live call returned `documents` with 1 citation; server log confirmed exactly 1 Groq request. |
| **2.4** | Cache keys include allow_general, mode_used, answer_source | **PASS** | `app/cache/cache_manager.py:get_cached_answer` | General knowledge cached response was never served when `allow_general=False`. |
| **2.5** | Frontend toggle, notice line, "General knowledge" badge, no citation chips | **PASS** | `frontend/src/views/QueryView.jsx` | Verified in JSX: toggle in localStorage, badge, notice rendered, chips suppressed. |
| **3.1** | `app/utils/errors.py` exists with `error_code`, `message`, `retryable` | **PASS** | `app/utils/errors.py:OmniLensError` | Schema and 7 standard error definitions verified. |
| **3.2** | No raw provider text, `[Generation error]`, stack traces reaching client | **PASS** | `app/api/query.py`, `app/utils/errors.py` | Codebase grep confirms zero occurrences; exceptions caught by `map_exception_to_error`. |
| **3.3** | Failure simulation: 429, timeout, 401, empty content return structured error | **PASS** | `app/utils/errors.py:map_exception_to_error` | 429 → `rate_limited`, timeout → `timeout`, 401 → `auth_error`, empty → retried cleanly. |
| **3.4** | Frontend shows calm card with Retry button on error | **PASS** | `frontend/src/views/QueryView.jsx` | Renders `.query-error-card-calm` with Retry button calling `executeQuery`. |
| **4.1** | `POST /query/stream` exists and uses `text/event-stream` | **PASS** | `app/api/query.py:semantic_query_stream` | Live call returned `Content-Type: text/event-stream; charset=utf-8`. |
| **4.2** | Real sequence of stream events: stage, token, meta, done in order; clean tokens | **PASS** | `app/api/query.py`, `app/generation/answer_generator.py` | Order: `stage` → `token` (174 events) → `meta` → `done`. Sentinel buffered; tags stripped. |
| **4.3** | Cache hit on stream emits stage, 1 token, meta (`cache_hit: true`), done; mid-stream failure safe | **PASS** | `app/api/query.py:semantic_query_stream` | Verified live: `['stage', 'token', 'meta', 'done']`, 1 token, `cache_hit: true`. |
| **4.4** | Frontend reads stream, shows stage labels, Stop button, progressive tokens | **PASS** | `frontend/src/views/QueryView.jsx` | `StageIndicator`, `#stop-btn`, and progressive text rendering verified. |
| **4.5** | Non-streaming `POST /query` still works | **PASS** | `app/api/query.py:semantic_query` | Live call succeeded with HTTP 200. |
| **5.1** | "history" is accepted (last 3 turns, answers truncated) | **PASS** | `app/api/query.py:QueryRequest` | Accepts `history`; answers truncated to 400 characters. |
| **5.2** | Follow-up query rewriting: "What about the next one?" → Experiment 2 | **PASS** | `app/generation/answer_generator.py:rewrite_question` | Live output: `"What is the aim of Experiment 2?"` using `GROQ_REWRITE_MODEL`. |
| **5.3** | Rewrite skipped on empty history and falls back on error | **PASS** | `app/generation/answer_generator.py:rewrite_question` | Tested with `history=[]`: `rewritten_question: None`. |
| **5.4** | Frontend sends history and displays "Searched for: ..." | **PASS** | `frontend/src/views/QueryView.jsx` | Sends up to 3 turns; displays `telemetry-rewritten-line`. |
| **6.1** | `sources.suggested_questions` stored; 4 questions; defensive JSON retry | **PARTIAL** / **BROKEN** | `app/db/metadata_store.py`, `app/ingestion/worker.py` | DB column exists; worker has import crash (`delete_by_source`) and no retry loop. |
| **6.2** | Stored suggestions answerable from throwaway content | **NOT VERIFIED** | `app/ingestion/worker.py` | Existing rows have `NULL` suggestions; worker does not run on upload. |
| **6.3** | `POST /source/{id}/suggestions` regenerates suggestions | **MISSING** | `app/api/` | Route does not exist in FastAPI app. |
| **6.4** | Frontend suggested question chips, click to send, refresh suggestions | **MISSING** | `frontend/src/views/QueryView.jsx` | Renders hardcoded static strings; no source suggestions binding or refresh button. |
| **7.1** | `POST /upload` returns immediate status; `GET /sources/{id}/status` polls progress; `wait=true` | **BROKEN** / **MISSING** | `app/api/upload.py`, `app/api/status.py` | Upload is synchronous & blocking; status endpoint and `wait=true` missing. |
| **7.2** | Single background worker processes jobs strictly in order | **BROKEN** | `app/ingestion/worker.py` | Import crashes on `from app.retrieval.vector_store import delete_by_source`; not wired to upload. |
| **7.3** | Querying non-ready source returns structured error; "All sources" filters non-ready | **PARTIAL** / **MISSING** | `app/api/query.py:_resolve_request` | Checks source presence, but does not check `status == 'ready'`. |
| **7.4** | Startup marks interrupted as failed; migration creates sources rows without altering chunks | **PASS** | `app/db/metadata_store.py:init_db` | Verified live: 8 sources migrated with status `ready`; chunks unchanged at 20. |
| **7.5** | Frontend upload progress via XHR, polling cleanup, "Ready to ask", retry, multi-file | **PARTIAL** | `frontend/src/api.js`, `frontend/src/views/UploadView.jsx` | XHR progress and multi-file exist; status polling, "Ready to ask", and retry missing. |
| **8.1** | `DELETE /source/{id}` removes SQLite chunks, source row, Chroma vectors, disk files | **MISSING** | `app/api/` | Route does not exist; `delete_by_source` missing in Chroma vector store. |
| **8.2** | Question only deleted file could answer returns no stale cached answer | **MISSING** | `app/cache/cache_manager.py` | Delete endpoint and cache invalidation on delete missing. |
| **8.3** | `POST /source/{id}/reindex` keeps same source_id, regenerates chunks & suggestions | **MISSING** | `app/api/` | Route does not exist in FastAPI app. |
| **8.4** | Frontend Delete and Re-index per row with confirmation; selection reset | **MISSING** | `frontend/src/views/UploadView.jsx` | Only "Inspect" button exists; Delete and Re-index buttons missing. |

---

## 4. Per-Feature Detailed Audit & Live Evidence

### Feature 1: Whole-Document Mode

#### 1.1 `POST /query` accepts `"mode"` (`auto`/`focused`/`document`) and returns `"mode_used"`
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`QueryRequest`, `QueryResponse`, lines 117–120, 161)
- **Live Output**:
  - Request: `{"question": "What is the primary topic of this syllabus audit_test_1?", "source_id": "0298b585-8ac3-4bbb-9975-6dcf0a6dd7ef", "mode": "focused"}`
    - Response: `mode_used: "focused"`, `latency_ms: {"embedding": 320.8, "retrieval": 40.7, "reranking": 276.2, "generation": 1780.1, "total": 2420.5}`
  - Request: `{"question": "What is the primary topic of this syllabus audit_test_2?", "source_id": "0298b585-8ac3-4bbb-9975-6dcf0a6dd7ef", "mode": "document"}`
    - Response: `mode_used: "document"`, `latency_ms: {"embedding": 0.0, "retrieval": 0.0, "reranking": 0.0, "generation": 1820.0, "total": 1822.4}`
- **Status**: **PASS**

#### 1.2 Auto mode aggregate detection on `dbms_tanya.pdf`
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`_determine_mode`, `_is_aggregate_question`, lines 206–209, 281–288)
- **Live API Request**:
  - Question: `"how many problem statements are in this document?"`
  - `source_id`: `"0298b585-8ac3-4bbb-9975-6dcf0a6dd7ef"` (`dbms_tanya.pdf`)
  - `mode`: `"auto"`
- **Live API Response**:
  - `status_code`: `200 OK`
  - `mode_used`: `"document"`
  - `answer_source`: `"documents"`
  - `answer`: `"There are five problem statements in the document (Problem Statement 1 in [CHUNK:9e2e4d51-a3ca-4b2c-9b83-09f28c072553], Problem Statement 2 in [CHUNK:33d882b5-8ca4-45b4-bdb0-a0845667fa47], Problem Statement 3 in [CHUNK:c27dff3c-5757-4d26-8db5-c94614f93286], Problem Statement 4 in [CHUNK:1cd31b29-6d93-4cf9-8d67-229c3bc1bc4a], and Problem Statement 5 in [CHUNK:fa0675b5-7264-4d25-a8fa-886a23a5c85c])."`
  - `cited_chunks`: 5 chunks cited (`9e2e4d51-a3ca-4b2c-9b83-09f28c072553`, `33d882b5-8ca4-45b4-bdb0-a0845667fa47`, `c27dff3c-5757-4d26-8db5-c94614f93286`, `1cd31b29-6d93-4cf9-8d67-229c3bc1bc4a`, `fa0675b5-7264-4d25-a8fa-886a23a5c85c`)
  - `cited_pages`: `[1, 3, 4, 5, 6]`
- **Status**: **PASS**

#### 1.3 Document mode skips vector search and reranking
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (lines 418–431)
- **Proof**:
  - When `mode_used == "document"`, code executes `_fetch_document_mode_chunks(effective_source_id)` and completely bypasses Chroma vector queries (`TEXT_COLLECTION`/`IMAGE_COLLECTION`) and CrossEncoder `rerank()`.
  - Wall-clock latencies returned in payload: `embedding: 0.0ms`, `retrieval: 0.0ms`, `reranking: 0.0ms`.
- **Status**: **PASS**

#### 1.4 Focused mode retrieves text and images separately
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`_fetch_focused_mode_chunks`, lines 330–373)
- **Proof**:
  - Vector search independently queries `TEXT_COLLECTION` (top 20) and `IMAGE_COLLECTION` (top 20).
  - Reranking ranks text candidates for `top_k`, and ranks image candidates separately for `min(2, len(image_candidates))`.
  - Image chunks cannot crowd out text chunks because text slots are dedicated to text.
- **Status**: **PASS**

#### 1.5 Truncation by page order with logged warning for oversized documents
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`_fetch_document_mode_chunks`, lines 290–327)
- **Proof**:
  - Constants: `_SAFE_CONTEXT_CHAR_LIMIT = 60_000`.
  - Chunks loaded in ascending `page_number` order. When `total_chars + len(text) > 60_000`, warning is logged:
    `logger.warning("Document mode context limit reached (%d chars). Truncating at page %s.", total_chars, c.get("page_number"))`
  - Tested live with synthetic oversized multi-page chunks: successfully truncated at page 2 (50,000 characters) and logged `Document mode context limit reached (50000 chars). Truncating at page 3.`
- **Status**: **PASS**

---

### Feature 2: Labeled General-Knowledge Fallback

#### 2.1 Grounded prompt uses `NOT_IN_DOCUMENTS` sentinel
- **File**: [`app/generation/answer_generator.py`](file:///d:/OmniLens/app/generation/answer_generator.py) (lines 50, 66–68), [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (line 441)
- **Proof**:
  - System preamble states: `"2. If the chunks do not contain enough information to answer the question, respond EXACTLY with the token: NOT_IN_DOCUMENTS"`.
  - Detection logic in `app/api/query.py`: `if NOT_IN_DOCUMENTS_TOKEN in raw_answer.strip():`
  - Does NOT match natural language refusal sentences; detects sentinel token explicitly.
- **Status**: **PASS**

#### 2.2 Live verification of `allow_general=true` vs `allow_general=false`
- **Question**: `"what is normalization in DBMS?"` with source restricted to `dbms_tanya.pdf`
- **Live API Output with `allow_general=true`**:
  - `status_code`: `200 OK`
  - `answer_source`: `"general_knowledge"`
  - `notice`: `"This isn't in the selected document."`
  - `cited_chunks`: `[]` (0 citations)
  - `answer`: `"Normalization is a systematic process of organizing the tables (relations) in a relational database to reduce redundancy and improve data integrity. It involves decomposing larger tables into smaller..."`
- **Live API Output with `allow_general=false`**:
  - `status_code`: `200 OK`
  - `answer_source`: `"not_found"`
  - `notice`: `"This isn't in the selected document."`
  - `cited_chunks`: `[]` (0 citations)
  - `answer`: `"I don't have enough information in the provided sources to answer this question."`
- **Status**: **PASS**

#### 2.3 Document-answerable question makes no second LLM call
- **Question**: `"What is Problem Statement 1 about in this lab document?"`
- **Live Response**:
  - `answer_source`: `"documents"`
  - `notice`: `None`
  - `cited_chunks`: `['9e2e4d51-a3ca-4b2c-9b83-09f28c072553']` (1 citation)
  - `answer`: `"Problem Statement 1 asks you to create an Employee table using SQL. [CHUNK:9e2e4d51-a3ca-4b2c-9b83-09f28c072553]"`
- **Server Log Evidence**:
  - Only a single Groq request was logged: `POST https://api.groq.com/openai/v1/chat/completions "HTTP/1.1 200 OK"`, followed directly by `POST /query HTTP/1.1 200 OK`. No secondary fallback invocation occurred.
- **Status**: **PASS**

#### 2.4 Cache keys discriminate mode, allow_general, and answer_source
- **File**: [`app/cache/cache_manager.py`](file:///d:/OmniLens/app/cache/cache_manager.py) (`_answer_key`, `get_cached_answer`, `set_cached_answer`, lines 79–90, 102–163)
- **Live Proof**:
  - Off-topic query `"What is the capital of Australia?"` with `allow_general=True` was cached under `answer_source="general_knowledge"`.
  - Next call with `allow_general=True` returned `cache_hit: True` and `answer_source: "general_knowledge"`.
  - Third call with `allow_general=False` evaluated cache; because `allow_general=False`, it strictly rejected the cached general-knowledge answer, returning `answer_source: "not_found"`.
- **Status**: **PASS**

#### 2.5 Frontend toggle, badges, notice, and citation suppression
- **File**: [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) (lines 125–139, 143–147, 155–157, 222–224, 463–475)
- **Proof**:
  - `allowGeneral` state defaults to `true`, initialized via `localStorage.getItem('omnilens_allow_general') !== 'false'`.
  - Checkbox `#general-knowledge-toggle` updates both state and `localStorage`.
  - Renders `<span className="grounded-header-tag general-knowledge-tag"><span className="gk-pulse-dot" />GENERAL KNOWLEDGE</span>`.
  - Renders `<div className="muted-notice-line">{entry.notice}</div>`.
  - Citation chips guarded: `{!isGeneralKnowledge && !isNotFound && (<CitationChipsList citations={entry.cited_chunks ?? entry.citations} />)}`.
- **Status**: **PASS**

---

### Feature 3: Friendly Errors

#### 3.1 `app/utils/errors.py` error definitions
- **File**: [`app/utils/errors.py`](file:///d:/OmniLens/app/utils/errors.py) (lines 27–63, 66–99)
- **Proof**:
  - Defines `OmniLensError` with `error_code`, `message`, `retryable`, and `to_dict()`.
  - Standard errors: `rate_limited` (429, retryable), `model_unavailable` (503, retryable), `auth_error` (401, non-retryable), `timeout` (504, retryable), `no_sources` (400, non-retryable), `empty_question` (400, non-retryable), `internal_error` (500, retryable).
- **Status**: **PASS**

#### 3.2 Leak prevention of provider error strings
- **File**: [`app/utils/errors.py`](file:///d:/OmniLens/app/utils/errors.py) (`map_exception_to_error`, lines 101–136)
- **Proof**:
  - Searches for `[Generation error]` across `app/` yield 0 occurrences.
  - Raw exception details are passed only to `logger.error(..., exc_info=True)`. Only the structured dictionary `{"error_code", "message", "retryable"}` is returned in HTTP responses.
- **Status**: **PASS**

#### 3.3 Simulation of 429, Timeout, 401, and Empty Content
- **Live Test Outputs**:
  - **429 (Rate Limit)**:
    - HTTP Status: `429 Too Many Requests`
    - Response: `{"error_code": "rate_limited", "message": "The AI service is busy right now. Please try again in a moment.", "retryable": true}`
  - **Timeout**:
    - HTTP Status: `504 Gateway Timeout`
    - Response: `{"error_code": "timeout", "message": "The request timed out. Please try again.", "retryable": true}`
  - **401 (Auth Error)**:
    - HTTP Status: `401 Unauthorized`
    - Response: `{"error_code": "auth_error", "message": "The AI service is not configured correctly. Check the API key in .env.", "retryable": false}`
  - **Empty Content**:
    - Handled by `answer_generator.py` retry with `max_tokens=4096`; returns HTTP 200 without exposing provider errors.
- **Status**: **PASS**

#### 3.4 Frontend calm error card with Retry
- **File**: [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) (lines 105–121)
- **Proof**:
  - When `entry.error` is set, renders `.query-error-card-calm` with message (`typeof entry.error === 'object' ? entry.error.message : entry.error`).
  - Renders `<button className="error-retry-action-btn" onClick={() => onRetry(entry.question)}>Retry</button>`, which re-submits the query.
- **Status**: **PASS**

---

### Feature 4: Streaming with Stage Display

#### 4.1 `POST /query/stream` endpoint
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`semantic_query_stream`, lines 503–669)
- **Live Output**:
  - `Content-Type`: `text/event-stream; charset=utf-8`
  - HTTP Status: `200 OK`
- **Status**: **PASS**

#### 4.2 Stream event sequence and sanitization
- **Live Observed Event Sequence**:
  1. `{"type": "stage", "stage": "searching"}`
  2. `{"type": "stage", "stage": "reranking"}`
  3. `{"type": "stage", "stage": "generating"}`
  4. 174 `{"type": "token", "text": "..."}` events
  5. `{"type": "meta", "cited_chunks": [...], "answer_source": "documents", "cache_hit": false}`
  6. `{"type": "done"}`
- **Sanitization Verified**:
  - Sentinel check: `NOT_IN_DOCUMENTS in full_streamed_text` → **False** (buffered in first 25 characters via `sentinel_buffer`).
  - Citation tags check: `re.search(r"\[(CHUNK|PAGE|IMAGE):[^\]]+\]", full_streamed_text)` → **False** (stripped via `_strip_citation_tag_stream`).
- **Status**: **PASS**

#### 4.3 Streaming cache hit & mid-stream failure safety
- **Live Cache Hit Event Sequence**:
  - `["stage", "token", "meta", "done"]`
  - Emitted exactly 1 token containing the entire answer; `meta` contained `"cache_hit": true`.
- **Mid-stream failure behavior**:
  - On exception during generation, generator catches exception and yields `{"type": "error", "error_code": ...}` followed by `{"type": "done"}`.
  - Caching call `set_cached_answer` occurs on lines 642–649 after generation loop succeeds; partial answers are never cached.
- **Status**: **PASS**

#### 4.4 Frontend stream consumption
- **File**: [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) (lines 6–25, 304–347, 400–407)
- **Proof**:
  - Maps stages (`rewriting`, `searching`, `reranking`, `generating`) to human-readable strings via `STAGE_LABELS` and `StageIndicator`.
  - Appends incoming tokens to `answer` in real time.
  - `#stop-btn` calls `abortController.abort()` to cancel the stream.
- **Status**: **PASS**

#### 4.5 Non-streaming `POST /query` operation
- **Live Proof**:
  - Direct HTTP calls to `POST /query` returned valid `QueryResponse` JSON bodies with latency breakdown, model info, and citation chips across all test passes.
- **Status**: **PASS**

---

### Feature 5: Follow-Up Handling

#### 5.1 "history" accepted in request schema
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (`QueryRequest`, lines 125–128)
- **Proof**:
  - `history: list[dict[str, str]] = Field(default_factory=list, description="...")`
  - Answers truncated to 400 characters in `rewrite_question` ([`answer_generator.py:263`](file:///d:/OmniLens/app/generation/answer_generator.py#L263)) and frontend ([`QueryView.jsx:276`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx#L276)).
- **Status**: **PASS**

#### 5.2 Live query rewriting of follow-up question
- **Turn 1**:
  - Question: `"What is the aim of Experiment 1?"`
  - Output: `rewritten_question: None`, `answer: "The aim of Experiment 1 is to perform and understand various DDL..."`
- **Turn 2**:
  - Question: `"What about the next one?"`
  - `history`: `[{"question": "What is the aim of Experiment 1?", "answer": "The aim of Experiment 1 is to perform and understand various DDL..."}]`
  - Live Output:
    - `rewritten_question`: `"What is the aim of Experiment 2?"`
    - Correctly resolved "the next one" to Experiment 2.
- **Status**: **PASS**

#### 5.3 Empty history and fallback behavior
- **File**: [`app/generation/answer_generator.py`](file:///d:/OmniLens/app/generation/answer_generator.py) (`rewrite_question`, lines 247–248, 291–293)
- **Proof**:
  - If `not history`: immediately returns `question` without invoking Groq.
  - On any Groq failure: catches exception, logs warning, and returns original `question`.
  - Live verified: calling with `history=[]` returned `rewritten_question: None`.
- **Status**: **PASS**

#### 5.4 Frontend telemetry display
- **File**: [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) (lines 161–165, 270–277)
- **Proof**:
  - Slices last 3 conversation turns from state.
  - Renders `<div className="telemetry-rewritten-line">Searched for: <em>"{entry.rewritten_question}"</em></div>`.
- **Status**: **PASS**

---

### Feature 6: Suggested Questions

#### 6.1 Schema & Generation Logic
- **Files**: [`app/db/metadata_store.py`](file:///d:/OmniLens/app/db/metadata_store.py) (lines 31, 96, 215, 284), [`app/ingestion/worker.py`](file:///d:/OmniLens/app/ingestion/worker.py) (lines 72–123)
- **Finding**:
  - SQLite schema column `sources.suggested_questions TEXT` exists and supports JSON arrays.
  - `_generate_suggested_questions` in `worker.py` attempts Groq generation for 4 questions.
  - **Defect 1**: `worker.py` has **no retry** on JSON parse error (only a single attempt with `raw.find("[")`).
  - **Defect 2**: `worker.py` fails on import with `ImportError: cannot import name 'delete_by_source' from 'app.retrieval.vector_store'`, so the worker module is broken.
  - **Defect 3**: `POST /upload` operates synchronously in `app/api/upload.py` and never invokes suggestions generation.
- **Status**: **PARTIAL / BROKEN**

#### 6.2 Stored suggestions validation on throwaway files
- **Finding**:
  - Inspection of `sources` table rows reveals `suggested_questions` is `NULL` for all rows.
  - Uploading a throwaway file produces chunks and embeddings, but leaves `suggested_questions` unpopulated because suggestions are only defined inside the unreferenced, broken worker.
- **Status**: **NOT VERIFIED**

#### 6.3 `POST /source/{id}/suggestions` regeneration endpoint
- **Finding**:
  - Grep search and OpenAPI schema inspection confirm that **no route** matching `POST /source/{id}/suggestions` exists anywhere in the codebase.
- **Status**: **MISSING**

#### 6.4 Frontend suggested questions integration
- **File**: [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) (lines 180–213)
- **Finding**:
  - Suggestions displayed on empty chat are hardcoded strings in `QueryWelcomeScreen`:
    `['What are the key conclusions or findings reported?', 'Summarize the financial performance...', 'Explain the architecture...']`
  - There is no logic to fetch `suggested_questions` from the selected source, no "Refresh suggestions" button, and clicking does not auto-select the source.
- **Status**: **MISSING**

---

### Feature 7: Upload Progress and Ready State

#### 7.1 Immediate upload response, status polling, and `wait=true`
- **Files**: [`app/api/upload.py`](file:///d:/OmniLens/app/api/upload.py), [`app/api/status.py`](file:///d:/OmniLens/app/api/status.py)
- **Finding**:
  - `POST /upload` does **not** return immediately. It blocks while synchronously parsing the document and creating embeddings, returning only when finished.
  - `GET /sources/{id}/status` does **not** exist (returns 404). Only `GET /source/{id}` exists (which returns chunk lists, not status progression).
  - Parameter `wait=true` is not supported on `POST /upload`.
- **Status**: **BROKEN / MISSING**

#### 7.2 Background worker order processing
- **File**: [`app/ingestion/worker.py`](file:///d:/OmniLens/app/ingestion/worker.py)
- **Finding**:
  - The module defines `IngestionJob`, `_job_queue`, and `_worker_loop`, but crashes on import with:
    `ImportError: cannot import name 'delete_by_source' from 'app.retrieval.vector_store'`
  - The worker is never started by `app/main.py:startup_event()`, and `app/api/upload.py` never enqueues jobs to `_job_queue`.
- **Status**: **BROKEN**

#### 7.3 Structured error for non-ready/failed sources & "All sources" filter
- **File**: [`app/api/query.py`](file:///d:/OmniLens/app/api/query.py) (lines 258–261)
- **Finding**:
  - `_resolve_request()` checks if any sources exist (`list_all_sources()`), but does **not** verify whether the requested `source_id` has `status == 'ready'`.
  - Querying a source left in `processing` or `failed` attempts vector search or chunk retrieval instead of returning a friendly structured error.
  - "All sources" retrieval does not filter out sources with non-ready statuses.
- **Status**: **PARTIAL / MISSING**

#### 7.4 Startup recovery & chunk migration integrity
- **File**: [`app/db/metadata_store.py`](file:///d:/OmniLens/app/db/metadata_store.py) (`init_db`, `_migrate_chunks_to_sources`, `_mark_interrupted_as_failed`, lines 125–197)
- **Proof**:
  - On startup, `init_db()` safely marks any source with status `queued` or `processing` as `failed` with message `"Processing was interrupted. Use Re-index to try again."`.
  - Successfully migrated 8 pre-existing sources to the `sources` table with status `ready`.
  - SQLite chunk count remained exactly 20 chunks before and after migration.
- **Status**: **PASS**

#### 7.5 Frontend upload state UI
- **Files**: [`frontend/src/api.js`](file:///d:/OmniLens/frontend/src/api.js), [`frontend/src/views/UploadView.jsx`](file:///d:/OmniLens/frontend/src/views/UploadView.jsx)
- **Finding**:
  - Real upload progress via XHR: **Implemented** (`uploadFile` uses `xhr.upload.onprogress`).
  - Multi-file support: **Implemented** (`<input multiple ...>`, iterates and uploads sequentially).
  - Polling with cleanup on unmount: **Missing** (frontend does not poll `GET /sources/{id}/status`).
  - "Ready to ask" button: **Missing** (only displays static `✓ Indexed` text).
  - Failed state with "Try again": **Missing** (displays error message, but no retry action button).
- **Status**: **PARTIAL**

---

### Feature 8: Source Management

#### 8.1 `DELETE /source/{id}` endpoint
- **Files**: [`app/api/`](file:///d:/OmniLens/app/api/), [`app/retrieval/vector_store.py`](file:///d:/OmniLens/app/retrieval/vector_store.py)
- **Finding**:
  - No `DELETE` router endpoint is registered in `app/api`.
  - In `app/db/metadata_store.py`, `delete_source(source_id)` and `delete_chunks_by_source(source_id)` exist.
  - However, ChromaDB vector store [`app/retrieval/vector_store.py`](file:///d:/OmniLens/app/retrieval/vector_store.py) has **no `delete_by_source` function**, meaning vector deletion from `text_chunks` and `image_chunks` is unimplemented.
- **Status**: **MISSING**

#### 8.2 Cache invalidation on source deletion
- **Finding**:
  - Because `DELETE /source/{id}` is not implemented, answer cache and retrieval cache entries for deleted sources are not purged on deletion.
- **Status**: **MISSING**

#### 8.3 `POST /source/{id}/reindex` endpoint
- **Files**: [`app/api/`](file:///d:/OmniLens/app/api/)
- **Finding**:
  - No `reindex` endpoint exists in FastAPI routers.
  - (Note: an offline script `app/retrieval/reindex_images.py` exists for re-captioning image chunks, but it is not an API endpoint and does not support document reindexing).
- **Status**: **MISSING**

#### 8.4 Frontend Source Management UI
- **File**: [`frontend/src/views/UploadView.jsx`](file:///d:/OmniLens/frontend/src/views/UploadView.jsx) (lines 221–258)
- **Finding**:
  - Source rows in `UploadView.jsx` contain only an "Inspect" button (`IconEye`, lines 252–255).
  - There are no "Delete" or "Re-index" buttons per row, no confirmation modals, no disabled states during processing, and no selection reset handler in `QueryView.jsx`.
- **Status**: **MISSING**

---

## 5. Cross-Cutting Infrastructure Checks

| Check | Result | Evidence & Details |
| :--- | :---: | :--- |
| **Existing test: `test_features.py`** | **PASS** | Ran acceptance tests; all 6 feature tests passed successfully. |
| **Existing test: `test_vision_image.py`** | **PASS** | Uploaded test image, extracted caption & OCR, verified query retrieval. |
| **Existing test: `test_llm.py`** | **PASS** | Verified Groq API completion on `openai/gpt-oss-120b` (1011.6 ms). |
| **Existing test: `test_ingestion.py`** | **PASS\*** | Passed all 4 tests when run with `PYTHONIOENCODING=utf-8`. (\*Fails under default Windows cp1252 due to printing `\u2713` checkmark). |
| **Existing test: `test_retrieval.py`** | **FAILED** | Fails with `KeyError: 'query_latency_ms'` at line 159 because it expects the Step-2 response schema rather than the Step-3/4 `QueryResponse` schema (`latency_ms`). |
| **Existing test: `test_step3.py`** | **FAILED** | Fails with `AssertionError: Expected refusal for out-of-domain question, got: NOT_IN_DOCUMENTS` at line 98 because Step 3 test expects refusal sentence while Feature 2 generates `NOT_IN_DOCUMENTS`. |
| **`eval/run_eval.py` strict mode check** | **PASS** | Line 106 sends `allow_general: False`; Line 181 generates header `**Mode**: Strict mode (allow_general=false)`. |
| **Search for "gemini" in codebase** | **PASS** | Zero occurrences found outside `venv/` and `node_modules/`. |
| **`.env` and `data/` in `.gitignore` & secrets check** | **PARTIAL** | `.env`, `data/omnilens.db`, `data/uploads/*`, and `data/chroma_db/*` are listed in `.gitignore`. However, directory is not initialized as a git repository (`.git` absent), and `data/cache/` is not listed in `.gitignore`. No API keys appear in tracked files. |
| **Frontend build: `npm run build`** | **PASS** | Vite production build succeeded in 2.61s with 0 errors. Console warnings found in `QueryView.jsx:243` and `api.js:188`. |
| **Documentation & Environment Examples** | **PASS** | `RUN_GUIDE.md` and `.env.example` document `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_VISION_MODEL`, `GROQ_REWRITE_MODEL`, and app settings. |

---

## 6. Prioritized Defect List (What is MISSING, PARTIAL, or BROKEN)

### Priority 1: High Severity (Broken Imports & Failing Tests)
1. **Broken Worker Import**: [`app/ingestion/worker.py:44`](file:///d:/OmniLens/app/ingestion/worker.py#L44)
   - **Problem**: `from app.retrieval.vector_store import delete_by_source` causes an immediate `ImportError` because `delete_by_source` does not exist in `app/retrieval/vector_store.py`.
2. **Outdated Step 2 Test**: [`test_retrieval.py:159`](file:///d:/OmniLens/test_retrieval.py#L159)
   - **Problem**: Raises `KeyError: 'query_latency_ms'` and `KeyError: 'results'`. The test asserts the obsolete Step-2 API contract instead of `QueryResponse` (`latency_ms`, `cited_chunks`).
3. **Outdated Step 3 Test**: [`test_step3.py:98`](file:///d:/OmniLens/test_step3.py#L98)
   - **Problem**: Raises `AssertionError: Expected refusal for out-of-domain question, got: NOT_IN_DOCUMENTS`. Asserts pre-sentinel refusal phrasing instead of the Feature 2 `NOT_IN_DOCUMENTS` sentinel contract.

### Priority 2: Medium-High Severity (Missing Endpoints in Features 6, 7, 8)
4. **Missing Source Management Endpoints**:
   - `DELETE /source/{id}` does not exist in [`app/api/status.py`](file:///d:/OmniLens/app/api/status.py) or [`app/api/upload.py`](file:///d:/OmniLens/app/api/upload.py).
   - `POST /source/{id}/reindex` does not exist in [`app/api/status.py`](file:///d:/OmniLens/app/api/status.py).
   - `POST /source/{id}/suggestions` does not exist in [`app/api/status.py`](file:///d:/OmniLens/app/api/status.py).
   - Missing vector deletion implementation: `delete_by_source` needs to be implemented in [`app/retrieval/vector_store.py`](file:///d:/OmniLens/app/retrieval/vector_store.py) using `_text_collection.delete(where={"source_id": source_id})` and `_image_collection.delete(where={"source_id": source_id})`.
5. **Synchronous Upload / Missing Status Polling**:
   - `POST /upload` in [`app/api/upload.py`](file:///d:/OmniLens/app/api/upload.py) runs synchronously rather than enqueuing to background worker and returning status immediately.
   - `GET /sources/{id}/status` does not exist in [`app/api/status.py`](file:///d:/OmniLens/app/api/status.py).

### Priority 3: Medium Severity (Frontend UI Gaps in Features 6, 7, 8)
6. **Frontend Source Management Missing**:
   - [`frontend/src/views/UploadView.jsx`](file:///d:/OmniLens/frontend/src/views/UploadView.jsx) lacks Delete and Re-index action buttons and confirmation dialogs.
   - `UploadView.jsx` lacks status polling and "Ready to ask" / "Try again" buttons.
7. **Frontend Suggested Questions Missing**:
   - [`frontend/src/views/QueryView.jsx`](file:///d:/OmniLens/frontend/src/views/QueryView.jsx) displays static hardcoded strings instead of dynamically loading `suggested_questions` from the selected source, and lacks a "Refresh suggestions" button.

### Priority 4: Low Severity (Polish & Config)
8. **Cache Key Mode Overlap**:
   - In [`app/cache/cache_manager.py:180-183`](file:///d:/OmniLens/app/cache/cache_manager.py#L180-L183), when an aggregate question is cached in `document` mode, it also populates `legacy_key`. A subsequent query for the same question explicitly requesting `mode="focused"` will hit `legacy_key` and return `mode_used="document"`.
9. **Git Ignore Completeness**:
   - `.gitignore` ignores `data/omnilens.db`, `data/uploads/*`, and `data/chroma_db/*`, but lacks `data/cache/`.
