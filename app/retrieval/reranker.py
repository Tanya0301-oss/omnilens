"""
app/retrieval/reranker.py
--------------------------
Cross-encoder reranker for OmniLens — Step 3.

How it works
~~~~~~~~~~~~~
After the first-stage vector search returns the top-k candidates from
ChromaDB, this module re-scores every (question, chunk_text) pair using
a cross-encoder model.  Cross-encoders are significantly more accurate than
bi-encoders (like sentence-transformers) because they jointly attend to both
the question and the document in a single forward pass — they just cannot be
used for the first-stage search because they don't produce stand-alone
embeddings.

Model: ``cross-encoder/ms-marco-MiniLM-L-6-v2``
  - Trained on MS MARCO passage retrieval pairs.
  - ~22 MB; fast enough for CPU reranking of a small top-k set (<=50).
  - Returns a raw logit score (higher = more relevant) — NOT a probability.

Image chunk limitation
~~~~~~~~~~~~~~~~~~~~~~~
The cross-encoder is a **text-only** model — it cannot directly process
pixel data.  For image chunks, we therefore use the OCR-extracted text
and/or the object-detection labels that were stored in the chunk's metadata
during ingestion (Step 1, ``image_parser.py``).  This is an approximation:
if an image chunk has very little OCR text and no detected objects, the
cross-encoder score will be uninformative.  We add a ``rerank_note`` field
to those results so callers can surface the limitation in the UI.

Design — module-level singleton
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The CrossEncoder is loaded ONCE at import time to avoid the ~1-2 s cold-start
penalty on every request.  All calls share the same model object, which is
thread-safe for inference.
"""

from __future__ import annotations

import time
from typing import Any

from sentence_transformers.cross_encoder import CrossEncoder

from app.utils.logging_config import get_logger, log_stage

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ---------------------------------------------------------------------------
# Module-level singleton — loaded exactly once
# ---------------------------------------------------------------------------

_t_load_start = time.perf_counter()
logger.info("Loading cross-encoder model '%s'...", _CROSS_ENCODER_MODEL)

_cross_encoder: CrossEncoder = CrossEncoder(_CROSS_ENCODER_MODEL)

_load_elapsed = time.perf_counter() - _t_load_start
logger.info(
    "Cross-encoder '%s' loaded in %.2fs",
    _CROSS_ENCODER_MODEL,
    _load_elapsed,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _candidate_text(candidate: dict[str, Any]) -> tuple[str, str]:
    """Extract the text proxy for a candidate chunk and a rerank note.

    For *text* chunks: return the stored ``content_text`` directly.
    For *image* chunks: concatenate OCR text and object-detection labels from
    metadata — these are stored by the image ingestion pipeline (Step 1).

    Args:
        candidate: A result dict with ``metadata`` and optionally
                   ``content_text`` / ``content_image_path`` fields.

    Returns:
        A ``(text_for_scoring, rerank_note)`` tuple.  ``rerank_note`` is empty
        for text chunks and explains the image approximation for image chunks.
    """
    meta: dict[str, Any] = candidate.get("metadata", {})
    chunk_type: str = meta.get("chunk_type", "text")

    # -- Text chunk: use the stored content directly -----------------------
    if chunk_type == "text":
        text = (
            candidate.get("content_text")        # preferred (from query.py)
            or meta.get("content_text", "")       # fallback from metadata
        )
        return text.strip() or "[empty text chunk]", ""

    # -- Image chunk: use OCR + object labels as the text proxy -----------
    # NOTE: The cross-encoder is a text-only model and cannot process pixel
    # data.  We use the best available textual description of the image that
    # was computed during ingestion:
    #   1. ``ocr_text``         — Tesseract output for scanned/embedded images.
    #   2. ``detected_objects`` — YOLOv8 class labels joined as a phrase.
    #   3. ``caption``          — any image caption stored by the parser.
    # If none are available, we fall back to the source filename, which gives
    # the cross-encoder minimal signal.  The ``rerank_note`` field is set so
    # callers can display a caveat in the UI or API response.

    parts: list[str] = []
    ocr = meta.get("ocr_text", "").strip()
    objects = meta.get("detected_objects", "").strip()
    caption = meta.get("caption", "").strip()

    if ocr:
        parts.append(ocr)
    if objects:
        parts.append(f"Objects detected: {objects}")
    if caption:
        parts.append(f"Caption: {caption}")

    proxy_text = " ".join(parts).strip()
    if not proxy_text:
        proxy_text = meta.get("source_filename", "[unknown image]")
        note = (
            "Image chunk with no OCR text or object labels — "
            "cross-encoder score is based on filename only and is unreliable."
        )
    else:
        note = (
            "Image chunk — cross-encoder scored OCR text / object labels as "
            "a text proxy; pixel content was not directly evaluated."
        )

    return proxy_text, note


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rerank(
    question: str,
    candidates: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Rerank *candidates* against *question* using the ms-marco cross-encoder.

    Each candidate is a result dict as produced by
    :func:`app.retrieval.vector_store.query` (keys: ``chunk_id``, ``score``,
    ``metadata``) — optionally enriched with ``content_text`` or
    ``content_image_path`` as done in ``app/api/query.py``.

    For text chunks the cross-encoder receives the stored passage text.
    For image chunks it receives OCR text + object labels as a text proxy
    (see module docstring for the known limitation).

    The function:
      1. Builds ``(question, chunk_text)`` pairs for all candidates.
      2. Runs a single batched forward pass through the cross-encoder.
      3. Attaches ``rerank_score`` (raw logit, higher = better) and
         ``rerank_note`` to every candidate dict.
      4. Returns the top-*k* results sorted by ``rerank_score`` descending.

    Args:
        question:   The user's natural-language question.
        candidates: List of candidate chunk dicts from the vector search stage.
                    The original ``score`` (vector similarity) is preserved
                    as ``vector_score``; ``rerank_score`` becomes the
                    primary sort key.
        top_k:      Maximum number of results to return after reranking.

    Returns:
        A list of up to *top_k* candidate dicts, sorted by ``rerank_score``
        descending.  Each dict gains two new keys:
          - ``rerank_score`` (float): raw cross-encoder logit.
          - ``rerank_note``  (str):  empty for text chunks; explanation for
                                     image chunks where a text proxy was used.

    Raises:
        ValueError: If *candidates* is empty.
    """
    if not candidates:
        logger.debug("rerank() called with 0 candidates — returning empty list.")
        return []

    t0 = time.perf_counter()

    # Build text pairs for the cross-encoder
    pairs: list[list[str]] = []
    notes: list[str] = []
    for cand in candidates:
        text, note = _candidate_text(cand)
        pairs.append([question, text])
        notes.append(note)

    # Single batched inference pass — much faster than one-by-one on CPU
    scores: list[float] = _cross_encoder.predict(
        pairs, show_progress_bar=False
    ).tolist()

    # Annotate each candidate dict (mutate a copy, not the original)
    annotated: list[dict[str, Any]] = []
    for cand, ce_score, note in zip(candidates, scores, notes):
        enriched = dict(cand)  # shallow copy
        enriched["vector_score"] = enriched.pop("score", 0.0)
        enriched["rerank_score"] = ce_score
        enriched["rerank_note"] = note
        annotated.append(enriched)

    # Sort by cross-encoder score, best first
    annotated.sort(key=lambda x: x["rerank_score"], reverse=True)
    result = annotated[:top_k]

    log_stage(
        logger,
        "Reranking",
        elapsed=time.perf_counter() - t0,
        candidates_in=len(candidates),
        top_k_out=len(result),
    )

    return result

