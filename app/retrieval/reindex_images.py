"""
app/retrieval/reindex_images.py
---------------------------------
Regenerate captions and embeddings for all existing image sources.

This script:
1. Iterates over all image sources recorded in SQLite metadata store.
2. For each image chunk, finds its local file in data/uploads/.
3. Re-runs OCR, Groq vision captioning, and YOLO detection.
4. Updates chunk's content_text and bbox in SQLite metadata store.
5. Re-embeds the chunk into ChromaDB collections:
   - image_chunks (CLIP vector)
   - text_chunks (sentence-transformer vector of the new content_text)
6. Prints a clear human-readable summary.
"""

import sys
import time
from pathlib import Path

from app.db.metadata_store import (
    fetch_chunks_by_source,
    init_db,
    list_all_sources,
    mark_chunk_embedded,
    update_chunk_content_text,
)
from app.embeddings.image_embedder import embed_image
from app.embeddings.text_embedder import embed_text_batch
from app.ingestion.image_parser import generate_image_chunk_content, _run_ocr, _run_yolo
from app.retrieval.backfill_embeddings import _build_metadata
from app.retrieval.vector_store import IMAGE_COLLECTION, TEXT_COLLECTION, add_chunk
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def reindex_images() -> dict[str, int]:
    """Re-process and re-embed all image chunks in OmniLens."""
    init_db()

    sources = list_all_sources()
    image_sources = [s for s in sources if s.get("source_type") == "image"]

    print(f"\nFound {len(image_sources)} image source(s) to reindex.")
    if not image_sources:
        print("No image sources found in database.")
        return {"processed": 0, "failed": 0, "skipped": 0}

    stats = {"processed": 0, "failed": 0, "skipped": 0}

    for idx, src in enumerate(image_sources, 1):
        source_id = src["source_id"]
        filename = src.get("source_filename", "unknown")
        print(f"\n[{idx}/{len(image_sources)}] Processing {filename} (source_id={source_id})...")

        chunks = fetch_chunks_by_source(source_id)
        if not chunks:
            print(f"  Warning: No chunks found for source_id={source_id}")
            stats["skipped"] += 1
            continue

        for chunk in chunks:
            chunk_id = chunk["id"]
            rel_path = chunk.get("content_image_path")
            if not rel_path:
                print(f"  Chunk {chunk_id}: No content_image_path found, skipping.")
                stats["skipped"] += 1
                continue

            abs_path = _REPO_ROOT / rel_path
            if not abs_path.exists():
                print(f"  Chunk {chunk_id}: File not found at {abs_path}, skipping.")
                stats["skipped"] += 1
                continue

            try:
                # 1. OCR + YOLO + Groq Vision
                ocr_text = _run_ocr(abs_path)
                detections = _run_yolo(abs_path)
                content_text, caption, caption_pending = generate_image_chunk_content(
                    image_path=abs_path,
                    source_filename=filename,
                    ocr_text=ocr_text,
                    detections=detections,
                )

                detected_obj_str = ", ".join(d["label"] for d in detections) if detections else ""
                bbox_payload = {
                    "detections": detections,
                    "detected_objects": detected_obj_str,
                    "caption": caption,
                    "ocr_text": ocr_text,
                    "caption_pending": caption_pending,
                }

                # 2. Update SQLite
                update_chunk_content_text(
                    chunk_id=chunk_id,
                    content_text=content_text,
                    bbox=bbox_payload,
                )

                # Update the chunk in-memory dict for embedding
                chunk["content_text"] = content_text
                chunk["bbox"] = bbox_payload
                meta_payload = _build_metadata(chunk)

                # 3. Embed visual with CLIP -> IMAGE_COLLECTION
                img_vector = embed_image(abs_path)
                add_chunk(
                    chunk_id=chunk_id,
                    embedding=img_vector,
                    metadata=meta_payload,
                    collection_name=IMAGE_COLLECTION,
                )

                # 4. Embed content_text with sentence-transformers -> TEXT_COLLECTION
                if content_text.strip():
                    txt_vector = embed_text_batch([content_text])[0]
                    add_chunk(
                        chunk_id=f"{chunk_id}_text",
                        embedding=txt_vector,
                        metadata=meta_payload,
                        collection_name=TEXT_COLLECTION,
                    )

                mark_chunk_embedded(chunk_id)
                stats["processed"] += 1
                print(f"  Successfully reindexed chunk {chunk_id} (caption_pending={caption_pending})")

            except Exception as exc:
                print(f"  Failed to reindex chunk {chunk_id}: {exc}")
                logger.exception("Failed to reindex chunk %s: %s", chunk_id, exc)
                stats["failed"] += 1

    return stats


def main() -> None:
    t0 = time.perf_counter()
    print("=" * 60)
    print(" OmniLens Image Reindexing & Dual-Embedding Tool")
    print("=" * 60)

    summary = reindex_images()

    elapsed = round(time.perf_counter() - t0, 2)
    print("\n" + "=" * 60)
    print(" Summary:")
    print(f"  Processed chunks: {summary['processed']}")
    print(f"  Skipped chunks:   {summary['skipped']}")
    print(f"  Failed chunks:    {summary['failed']}")
    print(f"  Total time:       {elapsed}s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
