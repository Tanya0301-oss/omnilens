"""
app/api/status.py
-----------------
GET /source/{source_id} — retrieve all stored chunks for a given upload.
GET /sources            — list all ingested sources.

This endpoint is the primary debug/verification surface for Step 1:
after uploading a file you can immediately call this to confirm that
the correct number of chunks were created with the right metadata.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.metadata_store import fetch_chunks_by_source, list_all_sources
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/source/{source_id}",
    summary="Retrieve all chunks for a given source upload",
)
async def get_source_chunks(source_id: str) -> JSONResponse:
    """Return all ingested chunks for *source_id* as a JSON response.

    Args:
        source_id: UUID returned by the ``POST /upload`` endpoint.

    Returns:
        JSON body::

            {
                "source_id": "<uuid>",
                "chunk_count": 7,
                "chunks": [
                    {
                        "id": "...",
                        "source_id": "...",
                        "source_filename": "report.pdf",
                        "source_type": "pdf",
                        "page_number": 1,
                        "bbox": null,
                        "chunk_type": "text",
                        "content_text": "Lorem ipsum …",
                        "content_image_path": null,
                        "created_at": "2026-10-02T08:00:00+00:00"
                    },
                    ...
                ]
            }

    Raises:
        404: If no chunks are found for *source_id*.
    """
    logger.info("Fetching chunks for source_id=%s", source_id)
    chunks = fetch_chunks_by_source(source_id)

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for source_id='{source_id}'. "
            "Ensure the file was uploaded and ingested successfully.",
        )

    return JSONResponse(
        content={
            "source_id": source_id,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
    )


@router.get(
    "/sources",
    summary="List all ingested sources",
)
async def get_all_sources() -> JSONResponse:
    """Return a summary list of every uploaded source.

    Each entry includes the source_id, filename, type, chunk count, and
    the timestamp of the first chunk (≈ upload time).

    Returns:
        JSON body::

            {
                "sources": [
                    {
                        "source_id": "...",
                        "source_filename": "report.pdf",
                        "source_type": "pdf",
                        "chunk_count": 7,
                        "created_at": "2026-10-02T08:00:00+00:00"
                    },
                    ...
                ]
            }
    """
    logger.info("Listing all sources")
    sources = list_all_sources()
    return JSONResponse(content={"sources": sources})
