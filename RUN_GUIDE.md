# OmniLens — Step 4 Complete: Run Guide

## Architecture Summary (all 4 steps)

```
PDF/Image → Ingestion → ChromaDB Embeddings → CrossEncoder Rerank
                                                      ↓
                               Groq grounded answer + citations
                                                      ↓
                                       React dashboard (localhost:5173)
```

---

## 1. Start the backend

```powershell
# From d:\OmniLens
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

```

Runs at **http://127.0.0.1:8000**  
API docs: http://127.0.0.1:8000/docs

---

## 2. Start the frontend

```powershell
# From d:\OmniLens\frontend  (separate terminal)
npm run dev
```

Runs at **http://localhost:5173**

---

## 3. Workflow

1. Open http://localhost:5173
2. Click **Sources** → drag-and-drop a PDF or image → watch progress bar
3. After upload, the source appears in the sources list
4. Click a source row → browse all its chunks (text / image filter)
5. Click **Query** → type a question → get a grounded answer with citation chips
6. The sidebar dot turns green once the backend is reachable

---

## 4. Run the evaluation harness

```powershell
# Backend must be running. From d:\OmniLens:
venv\Scripts\python.exe eval/run_eval.py
```

Optional flags:
```
--url http://127.0.0.1:8000   (default)
--top-k 5                     (chunks per query)
--timeout 120                 (seconds per request)
```

Output: `eval/eval_report.md`

### Adding custom test questions

Edit `eval/test_set.json`:
```json
{
  "id": "q11",
  "query": "Your custom question here?",
  "expected_keywords": [],
  "expect_refusal": false,
  "notes": "What this tests"
}
```

Set `"expect_refusal": true` for questions that should be rejected by the grounding guard
(e.g. general knowledge questions unrelated to uploaded docs).

---

## 5. File structure (Step 4 additions)

```
d:\OmniLens\
├── frontend/                 ← Vite React app
│   ├── src/
│   │   ├── index.css         ← Design system (tokens, all component styles)
│   │   ├── api.js            ← API client (upload, query, sources)
│   │   ├── Icons.jsx         ← Inline SVG icon set
│   │   ├── App.jsx           ← Shell: sidebar + topbar + view routing
│   │   └── views/
│   │       ├── UploadView.jsx      ← Drag-and-drop, progress, sources list
│   │       ├── QueryView.jsx       ← Chat, citations, latency bar
│   │       └── SourceDetailView.jsx ← Chunk browser per source
│   └── package.json
│
├── eval/
│   ├── test_set.json         ← 10 evaluation questions
│   └── run_eval.py           ← Batch eval harness → eval_report.md
│
└── app/
    ├── api/status.py         ← Added GET /sources endpoint
    └── db/metadata_store.py  ← Added list_all_sources()
```

---

## 6. CORS

`app/main.py` already sets `allow_origins=["*"]` — no changes needed for local dev.

---

## 7. Environment variables

```
# d:\OmniLens\.env
GROQ_API_KEY=<your key>
GROQ_MODEL=llama3-70b-8192
GROQ_VISION_MODEL=qwen/qwen3.8-27b
GROQ_REWRITE_MODEL=openai/gpt-oss-20b

# d:\OmniLens\frontend\.env  (optional — defaults to localhost:8000)
VITE_API_URL=http://127.0.0.1:8000
```

---

## 8. Five New Features

1. **Whole-Document Mode**:
   - Aggregate/overview questions ("how many", "count", "summarize", "list all", etc.) on a selected document automatically load all text chunks in page order from SQLite, bypassing vector search and reranking.
   - Mode parameter: `"auto"` (default), `"focused"`, or `"document"`.
   - Returns `mode_used` in responses.

2. **Labeled General-Knowledge Fallback**:
   - If document chunks do not contain the answer, the model responds with `NOT_IN_DOCUMENTS`.
   - If `allow_general=true`, OmniLens queries general knowledge with no citations, labeling the answer with `"answer_source": "general_knowledge"` and a notice.
   - If `allow_general=false`, returns a strict refusal with `"answer_source": "not_found"`.

3. **Friendly Structured Errors**:
   - All backend errors are mapped to friendly user-facing errors (`rate_limited`, `model_unavailable`, `auth_error`, `timeout`, `no_sources`, `empty_question`, `internal_error`).
   - Technical stack traces and provider JSON are logged server-side only.

4. **SSE Streaming Endpoint (`POST /query/stream`)**:
   - Server-Sent Events stream `stage` (`rewriting`, `searching`, `reranking`, `generating`), `token`, `meta`, `error`, and `done` events.
   - First ~25 characters are buffered to prevent leaking sentinels.
   - Citation tags are stripped from streamed text and aggregated into metadata citations.

5. **Follow-Up Handling**:
   - Accepts conversation `history` (last 3 turns).
   - Automatically rewrites ambiguous follow-up questions using `GROQ_REWRITE_MODEL` (`openai/gpt-oss-20b`) into standalone search queries.

---

## 9. Image Understanding & Reindexing

OmniLens supports vision-based image understanding for uploaded images (diagrams, photos, screenshots):
- Groq's Vision API (`GROQ_VISION_MODEL=qwen/qwen3.8-27b`) captions images, detects text, labels, entities, and relationships.
- Chunks are dual-embedded into `image_chunks` (CLIP) and `text_chunks` (sentence-transformers), making images searchable by description and filename.
- Questions mentioning a source filename automatically filter retrieval to that document.
- To re-caption and re-embed all existing image sources:
  ```powershell
  venv\Scripts\python.exe -m app.retrieval.reindex_images
  ```


