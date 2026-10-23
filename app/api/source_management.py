"""
app/api/source_management.py
-----------------------------
Source management endpoints:
  DELETE /source/{source_id}           — remove a source and all its data
  POST   /source/{source_id}/reindex   — re-run ingestion on a ready/failed source
  GET    /sources/{source_id}/status   — get live source status (progress, stage)

Rules
~~~~~
- Refuse delete/reindex while status is queued or processing.
- Delete removes: vectors from both ChromaDB collections, SQLite chunks,
  the sources row, the original uploaded file, and any extracted image
  sub-directory on disk.
- All steps tolerate "already missing" — a partial earlier failure can be
  cleaned up by deleting again (no 500 on second delete).
- Re-index: keep the sources row and the original file; wipe chunks/vectors,
  set status=queued, enqueue through the same background worker.
- Cache invalidation: clear answer + retrieval caches after delete/reindex
  (embedding cache is content-addressed and kept).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.cache.cache_manager import _answer_cache, _retrieval_cache
from app.db.metadata_store import (
    delete_chunks_by_source,
    delete_source,
    fetch_chunks_by_source,
    get_source,
    update_source_status,
)
from app.ingestion.worker import IngestionJob, enqueue_job, start_worker
from app.retrieval.vector_store import delete_by_source
from app.utils.logging_config import get_logger
from app.utils.paths import get_uploads_dir

logger = get_logger(__name__)
router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUSY_STATUSES = {"queued", "processing"}


def _invalidate_query_caches(source_id: str) -> None:
    """Clear the answer and retrieval caches entirely (log that we did)."""
    try:
        ans_count = len(_answer_cache)
        _answer_cache.clear()
        logger.info(
            "Cache invalidation: cleared %d answer cache entries (triggered by source_id=%s)",
            ans_count, source_id,
        )
    except Exception as exc:
        logger.warning("Failed to clear answer cache: %s", exc)

    try:
        ret_count = len(_retrieval_cache)
        _retrieval_cache.clear()
        logger.info(
            "Cache invalidation: cleared %d retrieval cache entries (triggered by source_id=%s)",
            ret_count, source_id,
        )
    except Exception as exc:
        logger.warning("Failed to clear retrieval cache: %s", exc)


def _delete_source_vectors_and_chunks(source_id: str) -> int:
    """Remove vectors from both ChromaDB collections and SQLite chunks.

    Tolerates missing data so it can be called multiple times safely.
    Returns the number of SQLite chunk rows removed.
    """
    # 1. Remove from ChromaDB (tolerates missing)
    try:
        delete_by_source(source_id)
    except Exception as exc:
        logger.warning("delete_by_source partial failure for %s: %s", source_id, exc)

    # 2. Remove from SQLite chunks table
    try:
        removed = delete_chunks_by_source(source_id)
    except Exception as exc:
        logger.warning("delete_chunks_by_source failure for %s: %s", source_id, exc)
        removed = 0

    return removed


def _delete_disk_files(source_id: str, stored_path: str | None) -> None:
    """Delete the original uploaded file and any extracted image sub-directory.

    Tolerates paths that are already missing.
    """
    # Original uploaded file
    if stored_path:
        p = Path(stored_path)
        if not p.is_absolute():
            p = _REPO_ROOT / stored_path
        if p.exists():
            try:
                p.unlink()
                logger.info("Deleted uploaded file: %s", p)
            except Exception as exc:
                logger.warning("Could not delete file %s: %s", p, exc)
        else:
            logger.info("Uploaded file already missing, skipping: %s", p)

    uploads_dir = get_uploads_dir()
    # Also try the canonical naming pattern for uploads directory
    # (stored_path may be None for migrated legacy sources)
    for candidate in uploads_dir.glob(f"{source_id}_*"):
        if candidate.is_file():
            try:
                candidate.unlink()
                logger.info("Deleted upload file by pattern: %s", candidate)
            except Exception as exc:
                logger.warning("Could not delete %s: %s", candidate, exc)

    # Extracted image sub-directory (named after source_id)
    img_dir = uploads_dir / source_id
    if img_dir.exists() and img_dir.is_dir():
        try:
            shutil.rmtree(img_dir)
            logger.info("Deleted extracted image directory: %s", img_dir)
        except Exception as exc:
            logger.warning("Could not delete image dir %s: %s", img_dir, exc)


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/status  — live progress polling
# ---------------------------------------------------------------------------


@router.get(
    "/sources/{source_id}/status",
    summary="Get live status and progress for a source",
)
async def get_source_status(source_id: str) -> JSONResponse:
    """Return current status, stage, progress, and error for *source_id*."""
    row = get_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_id}' not found.",
        )
    return JSONResponse(content={
        "source_id": source_id,
        "status": row.get("status", "unknown"),
        "stage": row.get("stage"),
        "progress": row.get("progress", 0),
        "chunk_count": row.get("chunk_count", 0),
        "error_message": row.get("error_message"),
        "filename": row.get("filename"),
    })


# ---------------------------------------------------------------------------
# DELETE /source/{source_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/source/{source_id}",
    summary="Delete a source and all its indexed content",
)
async def delete_source_endpoint(source_id: str) -> JSONResponse:
    """Delete a source, its chunks, vectors, and uploaded files.

    Returns
    -------
    ``{"deleted": true, "removed_chunks": n}`` on success.
    Friendly error with ``{"error_code": ..., "message": ...}`` on refusal.
    """
    row = get_source(source_id)

    # Not found → "already deleted" — idempotent, not a crash
    if row is None:
        logger.info("Delete requested for already-gone source_id=%s — returning deleted=true", source_id)
        return JSONResponse(content={
            "deleted": True,
            "removed_chunks": 0,
            "message": "Source was already deleted.",
        })

    status = row.get("status", "")
    if status in _BUSY_STATUSES:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "source_busy",
                "message": (
                    "This file is still being processed. "
                    "Try again when it finishes."
                ),
            },
        )

    stored_path = row.get("stored_path")

    # 1. Remove vectors + SQLite chunks
    removed_chunks = _delete_source_vectors_and_chunks(source_id)

    # 2. Remove the sources row
    try:
        delete_source(source_id)
    except Exception as exc:
        logger.warning("delete_source row failed for %s: %s", source_id, exc)

    # 3. Remove disk files
    _delete_disk_files(source_id, stored_path)

    # 4. Invalidate query caches
    _invalidate_query_caches(source_id)

    logger.info(
        "Deleted source_id=%s (filename=%s) — removed %d chunks",
        source_id, row.get("filename"), removed_chunks,
    )

    return JSONResponse(content={"deleted": True, "removed_chunks": removed_chunks})


# ---------------------------------------------------------------------------
# POST /source/{source_id}/reindex
# ---------------------------------------------------------------------------


@router.post(
    "/source/{source_id}/reindex",
    summary="Re-run ingestion on a ready or failed source",
)
async def reindex_source(source_id: str) -> JSONResponse:
    """Re-index an existing source without changing its source_id.

    Allowed only for status ``ready`` or ``failed``.
    The original file must still exist on disk.

    Returns
    -------
    ``{"queued": true, "source_id": "..."}``
    """
    row = get_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_id}' not found.",
        )

    status = row.get("status", "")
    if status in _BUSY_STATUSES:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "source_busy",
                "message": (
                    "This file is still being processed. "
                    "Try again when it finishes."
                ),
            },
        )

    # Locate the stored file
    stored_path = row.get("stored_path")
    abs_file: Path | None = None

    if stored_path:
        p = Path(stored_path)
        if not p.is_absolute():
            p = _REPO_ROOT / stored_path
        if p.exists():
            abs_file = p

    # Fallback: search uploads directory by naming pattern
    if abs_file is None:
        candidates = list(get_uploads_dir().glob(f"{source_id}_*"))
        # Prefer actual files, not directories
        file_candidates = [c for c in candidates if c.is_file()]
        if file_candidates:
            abs_file = file_candidates[0]

    if abs_file is None or not abs_file.exists():
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "file_missing",
                "message": (
                    "The original file is no longer available. "
                    "Delete this source and upload it again."
                ),
            },
        )

    # 1. Remove existing stale chunks and vectors (keep sources row + file)
    _delete_source_vectors_and_chunks(source_id)

    # 2. Reset sources row to queued, clear stale error
    update_source_status(
        source_id,
        status="queued",
        stage="Queued for re-indexing",
        progress=0,
        chunk_count=0,
        clear_error=True,
    )

    # 3. Invalidate caches
    _invalidate_query_caches(source_id)

    # 4. Build the job and enqueue
    filename = row.get("filename", abs_file.name)
    source_type = row.get("source_type", "pdf")

    # Determine relative path for image parser
    try:
        rel_path = str(abs_file.relative_to(_REPO_ROOT))
    except ValueError:
        rel_path = str(abs_file)

    job = IngestionJob(
        source_id=source_id,
        source_filename=filename,
        source_type=source_type,
        stored_path=str(abs_file),
        relative_saved_path=rel_path,
    )

    start_worker()
    enqueue_job(job)

    logger.info(
        "Re-index queued for source_id=%s filename=%s via %s",
        source_id, filename, abs_file,
    )

    return JSONResponse(content={"queued": True, "source_id": source_id})
