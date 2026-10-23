"""
app/ingestion/worker.py
-----------------------
Background ingestion worker for OmniLens.

A single daemon thread reads from an in-process queue and runs the full
ingestion pipeline for each uploaded file:
  1. PDF parsing or image analysis
  2. Auto-embedding (text + image vectors → ChromaDB)
  3. Suggested-questions generation via Groq

Progress is reported at each stage by patching the ``sources`` table so the
front-end can poll ``GET /sources/{source_id}/status``.

Only ONE file is processed at a time to keep memory usage predictable on
CPU-only deployments (model loading, ChromaDB writes).

Shutdown:  call :func:`stop_worker` or send ``None`` to the queue.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.db.metadata_store import (
    delete_chunks_by_source,
    fetch_chunks_by_source,
    get_source,
    update_source_status,
    update_source_suggestions,
)
from app.ingestion.image_parser import ingest_image
from app.ingestion.pdf_parser import ingest_pdf
from app.retrieval.backfill_embeddings import embed_chunks
from app.retrieval.vector_store import delete_by_source
from app.utils.logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Work item
# ---------------------------------------------------------------------------


@dataclass
class IngestionJob:
    """Everything the worker needs to process one upload."""
    source_id: str
    source_filename: str
    source_type: str       # "pdf" | "image"
    stored_path: str       # absolute path to the saved file
    relative_saved_path: str  # relative from repo root (for image_parser)


# ---------------------------------------------------------------------------
# Suggested questions generator
# ---------------------------------------------------------------------------


def _generate_suggested_questions(
    source_id: str,
    source_filename: str,
    sample_text: str,
) -> list[str]:
    """Ask Groq to generate 4 suggested questions about the document.

    Returns a list of question strings (may be shorter if Groq fails).
    Failure is non-fatal: we simply return an empty list.
    """
    try:
        from groq import Groq  # local import to keep startup fast

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return []

        model = os.getenv("GROQ_REWRITE_MODEL", "llama-3.1-8b-instant")
        client = Groq(api_key=api_key)

        prompt = (
            "You are an intelligent assistant. Based on the document excerpt below, "
            "generate exactly 4 concise, specific questions a user might ask about this document. "
            "Return a JSON array of 4 strings ONLY, no other text.\n\n"
            f"Document: {source_filename}\n\n"
            f"Excerpt:\n{sample_text[:3000]}"
        )

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.6,
        )
        raw = response.choices[0].message.content.strip()

        # Try to parse JSON array
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            questions = json.loads(raw[start:end])
            if isinstance(questions, list):
                return [str(q).strip() for q in questions[:4] if q]

        return []

    except Exception as exc:
        logger.warning(
            "Suggested questions generation failed for %s: %s", source_id, exc
        )
        return []


# ---------------------------------------------------------------------------
# Core pipeline (runs inside worker thread)
# ---------------------------------------------------------------------------


def _run_pipeline(job: IngestionJob) -> None:
    """Execute the full ingestion pipeline for one job with progress updates."""
    sid = job.source_id
    fname = job.source_filename
    abs_path = Path(job.stored_path)

    def _progress(stage: str, pct: int, status: str = "processing") -> None:
        update_source_status(
            sid,
            status=status,
            stage=stage,
            progress=pct,
        )

    try:
        # Stage 1 — parse file -------------------------------------------------
        _progress("Parsing document", 10)

        if job.source_type == "pdf":
            result = ingest_pdf(
                pdf_path=abs_path,
                source_id=sid,
                source_filename=fname,
            )
            chunks_created = result.text_chunks + result.image_chunks
        else:
            result = ingest_image(
                image_path=abs_path,
                source_id=sid,
                source_filename=fname,
                saved_relative_path=job.relative_saved_path,
            )
            chunks_created = 1

        update_source_status(
            sid,
            status="processing",
            stage="Embedding chunks",
            progress=40,
            chunk_count=chunks_created,
        )

        # Stage 2 — auto-embed --------------------------------------------------
        new_chunks = fetch_chunks_by_source(sid)
        embed_chunks(new_chunks)

        update_source_status(
            sid,
            status="processing",
            stage="Generating suggestions",
            progress=85,
        )

        # Stage 3 — suggested questions -----------------------------------------
        sample_text = ""
        for ch in new_chunks:
            ct = ch.get("content_text") or ""
            sample_text += ct + "\n"
            if len(sample_text) > 4000:
                break

        questions = _generate_suggested_questions(sid, fname, sample_text)

        # Stage 4 — done --------------------------------------------------------
        update_source_status(
            sid,
            status="ready",
            stage="Ready",
            progress=100,
            chunk_count=chunks_created,
            suggested_questions=questions if questions else None,
        )

        logger.info(
            "Ingestion pipeline complete for source_id=%s (%d chunks, %d suggestions)",
            sid,
            chunks_created,
            len(questions),
        )

    except Exception as exc:
        logger.exception("Ingestion pipeline failed for source_id=%s: %s", sid, exc)
        friendly = _friendly_error(exc)
        update_source_status(
            sid,
            status="failed",
            stage="Failed",
            progress=0,
            error_message=friendly,
        )


def _friendly_error(exc: Exception) -> str:
    """Convert a raw exception to a user-friendly message."""
    msg = str(exc)
    if "password" in msg.lower() or "encrypted" in msg.lower():
        return "This PDF is password-protected or encrypted. Please upload an unlocked copy."
    if "not found" in msg.lower() or "no such file" in msg.lower():
        return "The file could not be found after upload. Please try uploading again."
    if "quota" in msg.lower() or "rate" in msg.lower():
        return "AI service is temporarily unavailable (rate limit). The document was indexed but suggestions may be missing."
    if "memory" in msg.lower() or "oom" in msg.lower():
        return "The document is too large to process in memory. Try splitting it into smaller files."
    return "Processing failed unexpectedly. Please try uploading again."


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

_job_queue: queue.Queue[Optional[IngestionJob]] = queue.Queue()
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    """Drain the job queue; exit when None sentinel received."""
    logger.info("Ingestion worker thread started.")
    while True:
        job = _job_queue.get()
        if job is None:
            logger.info("Ingestion worker thread stopping.")
            _job_queue.task_done()
            return
        try:
            _run_pipeline(job)
        finally:
            _job_queue.task_done()


def start_worker() -> None:
    """Ensure the background worker thread is running (idempotent)."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        t = threading.Thread(target=_worker_loop, daemon=True, name="ingestion-worker")
        t.start()
        _worker_thread = t
    logger.info("Ingestion worker thread started.")


def stop_worker() -> None:
    """Signal the worker to stop after finishing any current job."""
    _job_queue.put(None)


def enqueue_job(job: IngestionJob) -> None:
    """Add an ingestion job to the processing queue."""
    _job_queue.put(job)
    logger.info(
        "Enqueued ingestion job: source_id=%s filename=%s",
        job.source_id,
        job.source_filename,
    )


def wait_for_source(source_id: str, timeout: float = 300.0) -> dict:
    """Block until source_id reaches a terminal state (ready|failed) or timeout.

    Used by ``wait=true`` callers (tests, eval) so the old synchronous
    semantics are preserved.

    Returns the source dict.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = get_source(source_id)
        if row and row.get("status") in ("ready", "failed"):
            return row
        time.sleep(0.5)

    # Timeout — return whatever we have
    return get_source(source_id) or {}
