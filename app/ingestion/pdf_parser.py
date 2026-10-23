"""
app/ingestion/pdf_parser.py
---------------------------
PDF ingestion for OmniLens.

Strategy (Step 1 — keep it simple):
- One *text* chunk per page: the full concatenated text on that page.
- One *image_region* chunk per embedded image on that page.

All chunks are inserted into the SQLite metadata store.
Embedded images are saved to ``data/uploads/`` as PNG files.

Dependencies: PyMuPDF (``fitz``), Pillow (``PIL``).
"""

import io
import time
import uuid
from pathlib import Path
from typing import NamedTuple

import fitz  # PyMuPDF

from app.db.metadata_store import insert_chunk
from app.utils.logging_config import get_logger, log_stage
from app.utils.paths import get_uploads_dir

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class PDFIngestionResult(NamedTuple):
    """Summary returned after ingesting a PDF."""

    source_id: str
    total_pages: int
    text_chunks: int
    image_chunks: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _save_image_bytes(
    image_bytes: bytes,
    source_id: str,
    page_number: int,
    img_index: int,
    ext: str = "png",
) -> str:
    """Persist extracted image bytes to disk and return the relative path.

    Args:
        image_bytes:  Raw image bytes from PyMuPDF.
        source_id:    Source UUID (used as a sub-directory name to keep
                      uploads from different sources separate).
        page_number:  1-based page number.
        img_index:    0-based index of the image on that page.
        ext:          File extension without dot (default ``"png"``).

    Returns:
        Relative path string under ``data/uploads/``, e.g.
        ``"{source_id}/page_1_img_0.png"``.
    """
    source_dir = get_uploads_dir() / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    filename = f"page_{page_number}_img_{img_index}.{ext}"
    full_path = source_dir / filename
    full_path.write_bytes(image_bytes)

    # Return a path relative to the repo root for portability.
    try:
        return str(full_path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(full_path)


def _extract_page_images(
    page: fitz.Page,
    pdf_document: fitz.Document,
    source_id: str,
    page_number: int,
) -> list[str]:
    """Extract all embedded images from *page* and save them to disk.

    Args:
        page:         A :class:`fitz.Page` object.
        pdf_document: The parent :class:`fitz.Document` (needed for xref lookup).
        source_id:    Source UUID used in the save path.
        page_number:  1-based page number.

    Returns:
        A list of relative file paths for each saved image.
    """
    saved_paths: list[str] = []

    image_list = page.get_images(full=True)
    for img_index, img_info in enumerate(image_list):
        xref = img_info[0]
        try:
            base_image = pdf_document.extract_image(xref)
            image_bytes = base_image["image"]
            ext = base_image.get("ext", "png").lower()

            rel_path = _save_image_bytes(
                image_bytes,
                source_id=source_id,
                page_number=page_number,
                img_index=img_index,
                ext=ext,
            )
            saved_paths.append(rel_path)
            logger.debug(
                "Saved embedded image: %s (page %d, img %d)",
                rel_path,
                page_number,
                img_index,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not extract image xref=%d on page %d: %s",
                xref,
                page_number,
                exc,
            )

    return saved_paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_pdf(
    pdf_path: Path,
    source_id: str,
    source_filename: str,
) -> PDFIngestionResult:
    """Parse *pdf_path* and insert chunk rows into the metadata store.

    For each page the function inserts:
    - One ``chunk_type="text"`` row with the page's full text.
    - One ``chunk_type="image_region"`` row per embedded image.

    Args:
        pdf_path:         Absolute path to the PDF file on disk.
        source_id:        UUID that will group all chunks from this upload.
        source_filename:  Original filename (stored for display purposes).

    Returns:
        A :class:`PDFIngestionResult` summarising the ingestion.

    Raises:
        FileNotFoundError: If *pdf_path* does not exist.
        fitz.FileDataError: If the file cannot be opened as a PDF.
    """
    t_start = time.perf_counter()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pdf_document = fitz.open(str(pdf_path))
    total_pages = len(pdf_document)
    text_chunks = 0
    image_chunks = 0

    logger.info(
        "Starting PDF ingestion: %s (%d pages)", source_filename, total_pages
    )

    for page_index in range(total_pages):
        page_number = page_index + 1  # 1-based
        page: fitz.Page = pdf_document[page_index]

        # ---- Text chunk -----------------------------------------------
        text = page.get_text("text").strip()
        # Always store a text chunk, even if the page is empty — makes it
        # easy to know a page was processed.
        insert_chunk(
            source_id=source_id,
            source_filename=source_filename,
            source_type="pdf",
            chunk_type="text",
            page_number=page_number,
            content_text=text if text else "(no text on this page)",
        )
        text_chunks += 1

        # ---- Image chunks ---------------------------------------------
        image_paths = _extract_page_images(
            page, pdf_document, source_id, page_number
        )
        for img_path in image_paths:
            insert_chunk(
                source_id=source_id,
                source_filename=source_filename,
                source_type="pdf",
                chunk_type="image_region",
                page_number=page_number,
                content_image_path=img_path,
            )
            image_chunks += 1

    pdf_document.close()

    elapsed = time.perf_counter() - t_start
    log_stage(
        logger,
        "PDF parsed",
        elapsed=elapsed,
        filename=source_filename,
        pages=total_pages,
        text_chunks=text_chunks,
        image_chunks=image_chunks,
    )

    return PDFIngestionResult(
        source_id=source_id,
        total_pages=total_pages,
        text_chunks=text_chunks,
        image_chunks=image_chunks,
    )
