"""
app/api/upload.py
-----------------
POST /upload — accept a PDF or image file, route to the correct parser,
and return a summary of what was ingested.

Detection logic:
- Files with ``.pdf`` extension (case-insensitive) → :mod:`app.ingestion.pdf_parser`
- Files with ``.jpg``, ``.jpeg``, or ``.png`` extension → :mod:`app.ingestion.image_parser`

The raw file is saved to ``data/uploads/{source_id}_{original_filename}``
before processing so the ingestion functions always work with a local path.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.db.metadata_store import fetch_chunks_by_source, list_all_sources, upsert_source
from app.ingestion.image_parser import ingest_image
from app.ingestion.pdf_parser import ingest_pdf
from app.retrieval.backfill_embeddings import embed_chunks
from app.utils.logging_config import get_logger, timed_stage
from app.utils.paths import get_uploads_dir

logger = get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PDF_EXTENSIONS = {".pdf"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_type(filename: str) -> str | None:
    """Infer content type from the file extension.

    Args:
        filename: Original filename string (e.g. ``"report.PDF"``).

    Returns:
        ``"pdf"``, ``"image"``, or ``None`` if the extension is unsupported.
    """
    ext = Path(filename).suffix.lower()
    if ext in _PDF_EXTENSIONS:
        return "pdf"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    return None


async def _save_upload(file: UploadFile, dest: Path) -> None:
    """Stream *file* contents to *dest*, creating parent directories if needed.

    Args:
        file: The incoming :class:`fastapi.UploadFile`.
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Saved upload to %s (%d bytes)", dest, len(content))


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/upload", summary="Upload a PDF or image for ingestion")
async def upload_file(file: UploadFile) -> JSONResponse:
    """Accept a PDF or image upload, ingest it, and return a chunk summary.

    The endpoint:
    1. Generates a ``source_id`` UUID for this upload.
    2. Saves the raw file to ``data/uploads/{source_id}_{filename}``.
    3. Routes to :func:`~app.ingestion.pdf_parser.ingest_pdf` or
       :func:`~app.ingestion.image_parser.ingest_image`.
    4. Returns JSON with ``source_id`` and ingestion statistics.

    Args:
        file: The multipart/form-data file upload.

    Returns:
        JSON body::

            {
                "source_id": "<uuid>",
                "source_filename": "report.pdf",
                "source_type": "pdf",
                "chunks_created": 7,
                "chunk_types": {"text": 5, "image_region": 2}
            }

    Raises:
        422: If the file extension is not supported.
        500: If ingestion fails unexpectedly.
    """
    original_filename = file.filename or "unknown"
    source_type = _detect_type(original_filename)

    if source_type is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type: '{Path(original_filename).suffix}'. "
                "Accepted: .pdf, .jpg, .jpeg, .png"
            ),
        )

    source_id = str(uuid.uuid4())
    save_filename = f"{source_id}_{original_filename}"
    uploads_dir = get_uploads_dir()
    save_path = uploads_dir / save_filename

    # Read and compute hash
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    logger.info("Saved upload to %s (%d bytes, sha256=%s)", save_path, len(content), file_hash[:12])

    # Check for existing duplicate ready source
    duplicate_source = None
    try:
        ready_sources = list_all_sources()
        for s in ready_sources:
            if s.get("file_hash") == file_hash and s.get("status") == "ready":
                duplicate_source = s
                break
    except Exception:
        pass

    # Relative path from repo root (used as content_image_path for images)
    try:
        relative_save_path = str(save_path.relative_to(_REPO_ROOT))
    except ValueError:
        relative_save_path = str(save_path)

    try:
        if source_type == "pdf":
            result = ingest_pdf(
                pdf_path=save_path,
                source_id=source_id,
                source_filename=original_filename,
            )
            chunks_created = result.text_chunks + result.image_chunks
            chunk_types = {
                "text": result.text_chunks,
                "image_region": result.image_chunks,
            }

        else:  # image
            result = ingest_image(
                image_path=save_path,
                source_id=source_id,
                source_filename=original_filename,
                saved_relative_path=relative_save_path,
            )
            chunks_created = 1
            chunk_types = {"image_region": 1}

    except Exception as exc:
        logger.exception("Ingestion failed for %s: %s", original_filename, exc)
        try:
            upsert_source(
                source_id=source_id,
                filename=original_filename,
                source_type=source_type,
                stored_path=relative_save_path,
                status="failed",
                stage="Failed",
                progress=0,
                error_message=str(exc),
                file_hash=file_hash,
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    # ----------------------------------------------------------------
    # Auto-embed: immediately embed all chunks from this upload so they
    # are searchable without requiring a manual backfill run.
    # We fetch only the new source's chunks to avoid re-processing old data.
    # ----------------------------------------------------------------
    embedding_summary: dict = {}
    try:
        with timed_stage(logger, "Auto-embed after upload",
                         source_id=source_id, chunks=chunks_created):
            new_chunks = fetch_chunks_by_source(source_id)
            embedding_summary = embed_chunks(new_chunks)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Auto-embed failed for source_id=%s (backfill later): %s",
            source_id,
            exc,
        )
        embedding_summary = {"error": str(exc)}

    # Record source row as ready in metadata store
    upsert_source(
        source_id=source_id,
        filename=original_filename,
        source_type=source_type,
        stored_path=relative_save_path,
        status="ready",
        stage="Ready",
        progress=100,
        chunk_count=chunks_created,
        file_hash=file_hash,
    )

    resp = {
        "source_id": source_id,
        "source_filename": original_filename,
        "source_type": source_type,
        "chunks_created": chunks_created,
        "chunk_types": chunk_types,
        "embedding_summary": embedding_summary,
        "file_hash": file_hash,
    }
    if duplicate_source:
        dup_fname = duplicate_source.get("filename") or duplicate_source.get("source_filename")
        resp["duplicate_notice"] = f"This file is already uploaded as '{dup_fname}'"

    return JSONResponse(content=resp)
