# Tech Stack — OmniLens

> Constraint: NO Docker, NO paid tools. Everything must run as native Python/local processes on a resource-constrained laptop. Offload heavy GPU inference to Google Colab free tier if needed.

## Backend Framework
- **FastAPI** — API layer (async-friendly, auto docs via Swagger)
- **Uvicorn** — ASGI server to run FastAPI

## Databases
- **ChromaDB** — vector database, embedded/file-based, no server process needed
- **SQLite** — metadata storage (source_id, page/timestamp, modality type, upload info) — single file, zero setup

## Caching
- **Python `diskcache`** or **`functools.lru_cache`** — in-process/disk caching instead of Redis
  - Cache layers: (1) query-result cache, (2) embedding cache (avoid recomputation for duplicate content), (3) retrieval cache (before reranking)

## Document / Image Processing
- **PyMuPDF (fitz)** or **unstructured** — PDF text + layout parsing, extracting embedded images
- **Tesseract OCR** (via `pytesseract`) — text extraction from images/scanned pages
- **YOLOv8 (Ultralytics)** — object detection on images (free, open-source)

## Audio / Video (stretch goal)
- **OpenAI Whisper** (open-source, runs locally) — speech-to-text transcription
- **OpenCV** or **ffmpeg-python** — frame extraction/sampling from video

## Embeddings
- **sentence-transformers** (e.g. `all-MiniLM-L6-v2`) — text embeddings, runs locally, no API cost
- **CLIP** (via Hugging Face `transformers` or `open_clip`) — image/cross-modal embeddings, runs locally

## Reranking
- **sentence-transformers cross-encoder** (e.g. `ms-marco-MiniLM`) — reranks top-k retrieved chunks before generation

## Generation (LLM / VLM)
- **Groq API (free tier)** — final grounded answer generation via `llama3-70b-8192` or another model from your account
- Optional local fallback: **Ollama** running **LLaVA** (vision) / **Llama 3** (text) if you want a fully offline option

## Async / Background Jobs
- **FastAPI `BackgroundTasks`** for simple cases, or **Python `multiprocessing`/`concurrent.futures`** for parallel processing of heavy jobs (no Kafka/RabbitMQ needed at this scale — note this as a "future scaling" design decision, not a missing feature)

## Frontend
- **Streamlit** (fastest to build, good for demo) OR **React + Vite** (if you want a more "professional product" look for resume screenshots)
- Must visually show: uploaded source (PDF page / image / video frame) with the matched region/timestamp highlighted when answering

## Observability (lightweight, no paid tools)
- **Python `logging`** module with structured logs (stage name + latency) per pipeline step
- Optional: simple **Streamlit/Matplotlib dashboard** showing per-stage latency instead of full Prometheus+Grafana (mention Prometheus+Grafana in your README as the "production scaling plan")

## Deployment (optional, for a live demo link)
- **Render or Railway free tier** for hosting the FastAPI app
- Heavy local-only models (Whisper/CLIP/YOLO) may need to stay local-only or run via Colab if free-tier hosting can't handle the compute — document this limitation honestly in the README

## Environment / Dependency Management
- **Python 3.10+**
- **venv** (built into Python, no extra tool needed) or **pip + requirements.txt**
