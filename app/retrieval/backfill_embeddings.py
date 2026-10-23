"""
app/retrieval/backfill_embeddings.py
--------------------------------------
Embed all unembedded chunks from SQLite into ChromaDB.

Two use modes
~~~~~~~~~~~~~
1. **Automatic (called by the upload pipeline)**
   :func:`embed_chunks` is imported and called from ``app/api/upload.py``
   immediately after ingestion.  New uploads are embedded in the same
   request, with no manual step.

2. **Standalone backfill (run from the command line)**
   Run against any chunks that were ingested in Step 1 testing before
   embeddings existed::

       python -m app.retrieval.backfill_embeddings

   The script is idempotent: chunks already marked ``embedded=1`` are skipped.

Embedding routing
~~~~~~~~~~~~~~~~~
- ``chunk_type="text"``         → :func:`~app.embeddings.text_embedder.embed_text`
                                   → ChromaDB ``"text_chunks"`` collection (384-dim)
- ``chunk_type="image_region"`` → :func:`~app.embeddings.image_embedder.embed_image`
                                   → ChromaDB ``"image_chunks"`` collection (512-dim)
  If the image file is missing (e.g. corrupt upload), the chunk is skipped
  with a warning and left as ``embedded=0`` for a future retry.

Performance note
~~~~~~~~~~~~~~~~
On CPU, sentence-transformers batching is used when processing multiple text
chunks at once (one :func:`embed_text_batch` call per source instead of N
single calls).  Image embedding cannot be easily batched without assembling
tensors manually, so images are embedded one at a time.
"""

import sys
import time
from pathlib import Path
from typing import Any

from app.db.metadata_store import (
    fetch_unembedded_chunks,
    init_db,
    mark_chunk_embedded,
)
from app.embeddings.image_embedder import embed_image
from app.embeddings.text_embedder import embed_text_batch
from app.retrieval.vector_store import (
    IMAGE_COLLECTION,
    TEXT_COLLECTION,
    add_chunk,
)
from app.utils.logging_config import get_logger, log_stage

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """Extract the subset of chunk fields to store as ChromaDB metadata.

    ChromaDB metadata must contain only str/int/float/bool values; None is
    not allowed.  This function serialises nullable fields to empty strings
    so callers don't have to worry about it.

    Args:
        chunk: A chunk dict from :func:`~app.db.metadata_store.fetch_unembedded_chunks`.

    Returns:
        A flat dict safe to pass to :func:`~app.retrieval.vector_store.add_chunk`.
    """
    bbox_data = chunk.get("bbox") or {}
    caption = ""
    detected_objects = ""
    if isinstance(bbox_data, dict):
        caption = str(bbox_data.get("caption") or "")
        detected_objects = str(bbox_data.get("detected_objects") or "")

    return {
        "source_id": chunk["source_id"] or "",
        "source_filename": chunk["source_filename"] or "",
        "source_type": chunk["source_type"] or "",
        "chunk_type": chunk["chunk_type"] or "",
        "page_number": chunk["page_number"] if chunk["page_number"] is not None else -1,
        "content_text": (chunk["content_text"] or "")[:1000],  # keep metadata small
        "content_image_path": chunk["content_image_path"] or "",
        "caption": caption[:500],
        "detected_objects": detected_objects[:200],
    }



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_chunks(chunks: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Embed and store a list of chunks, or all unembedded chunks if None.

    Args:
        chunks: Explicit list of chunk dicts to embed.  If ``None``, all
                chunks with ``embedded=0`` are fetched from SQLite.

    Returns:
        A summary dict::

            {
                "text_embedded": 5,
                "image_embedded": 2,
                "image_skipped": 1,   # missing image file
                "total_elapsed_s": 3.2
            }
    """
    t_total = time.perf_counter()

    if chunks is None:
        chunks = fetch_unembedded_chunks()

    if not chunks:
        logger.info("No unembedded chunks found — nothing to do.")
        return {"text_embedded": 0, "image_embedded": 0,
                "image_skipped": 0, "total_elapsed_s": 0.0}

    # Partition by type
    text_chunks = [c for c in chunks if c["chunk_type"] == "text"]
    image_chunks = [c for c in chunks if c["chunk_type"] == "image_region"]

    logger.info(
        "Embedding %d text chunk(s) and %d image chunk(s)…",
        len(text_chunks),
        len(image_chunks),
    )

    # ------------------------------------------------------------------ TEXT
    text_embedded = 0
    if text_chunks:
        t_text = time.perf_counter()
        texts = [c["content_text"] or "" for c in text_chunks]

        # Batch embed all text chunks in one forward pass.
        vectors = embed_text_batch(texts)

        for chunk, vector in zip(text_chunks, vectors):
            add_chunk(
                chunk_id=chunk["id"],
                embedding=vector,
                metadata=_build_metadata(chunk),
                collection_name=TEXT_COLLECTION,
            )
            mark_chunk_embedded(chunk["id"])
            text_embedded += 1

        log_stage(
            logger,
            "Text chunks embedded",
            elapsed=time.perf_counter() - t_text,
            count=text_embedded,
        )

    # ---------------------------------------------------------------- IMAGES
    image_embedded = 0
    image_skipped = 0
    if image_chunks:
        t_img = time.perf_counter()
        for chunk in image_chunks:
            rel_path = chunk.get("content_image_path")
            if not rel_path:
                logger.warning(
                    "Skipping image chunk %s — no content_image_path", chunk["id"]
                )
                image_skipped += 1
                continue

            abs_path = _REPO_ROOT / rel_path
            if not abs_path.exists():
                logger.warning(
                    "Skipping image chunk %s — file not found: %s",
                    chunk["id"],
                    abs_path,
                )
                image_skipped += 1
                continue

            try:
                vector = embed_image(abs_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping image chunk %s — embed_image failed: %s",
                    chunk["id"],
                    exc,
                )
                image_skipped += 1
                continue

            metadata_payload = _build_metadata(chunk)

            # 1. CLIP visual embedding into IMAGE_COLLECTION
            add_chunk(
                chunk_id=chunk["id"],
                embedding=vector,
                metadata=metadata_payload,
                collection_name=IMAGE_COLLECTION,
            )

            # 2. Text embedding of content_text into TEXT_COLLECTION
            # This allows text questions to retrieve images by description/OCR/filename
            content_text = chunk.get("content_text") or ""
            if content_text.strip():
                try:
                    text_vec = embed_text_batch([content_text])[0]
                    add_chunk(
                        chunk_id=f"{chunk['id']}_text",
                        embedding=text_vec,
                        metadata=metadata_payload,
                        collection_name=TEXT_COLLECTION,
                    )
                except Exception as text_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to embed image content_text into text_chunks for %s: %s",
                        chunk["id"],
                        text_exc,
                    )

            mark_chunk_embedded(chunk["id"])
            image_embedded += 1

        log_stage(
            logger,
            "Image chunks embedded",
            elapsed=time.perf_counter() - t_img,
            count=image_embedded,
            skipped=image_skipped,
        )

    total_elapsed = time.perf_counter() - t_total
    log_stage(
        logger,
        "Backfill complete",
        elapsed=total_elapsed,
        text_embedded=text_embedded,
        image_embedded=image_embedded,
        image_skipped=image_skipped,
    )

    return {
        "text_embedded": text_embedded,
        "image_embedded": image_embedded,
        "image_skipped": image_skipped,
        "total_elapsed_s": round(total_elapsed, 3),
    }


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entrypoint: embed all unembedded chunks and print a summary."""
    # Ensure the DB schema (including the embedded column) exists.
    init_db()

    logger.info("OmniLens backfill — embedding all unembedded chunks…")
    summary = embed_chunks()

    print("\n--- Backfill Summary ---")
    for key, val in summary.items():
        print(f"  {key}: {val}")
    print("------------------------\n")

    if summary["text_embedded"] + summary["image_embedded"] == 0:
        print("Nothing to embed. Either the DB is empty or all chunks are already embedded.")
        print("Upload a file first:  POST http://127.0.0.1:8000/upload")


if __name__ == "__main__":
    main()
