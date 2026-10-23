"""
app/retrieval/vector_store.py
------------------------------
ChromaDB wrapper for OmniLens.

Two persistent collections
~~~~~~~~~~~~~~~~~~~~~~~~~~~
- ``"text_chunks"``  — 384-dim sentence-transformers vectors for PDF text pages.
- ``"image_chunks"`` — 512-dim CLIP image vectors for embedded/standalone images.

They have different dimensionalities, so they MUST be separate collections.
ChromaDB validates embedding dimensions at upsert time and would reject a
512-dim vector inserted into a collection that already holds 384-dim vectors.

Design: persistent client, not in-memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A :class:`chromadb.PersistentClient` is used so vectors survive process
restarts.  The database directory is ``data/chroma_db/`` relative to the
repository root.  No Chroma server process is needed — this is the embedded
file-based mode, which suits the no-Docker constraint.

Collection-level singleton
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Both collection objects are created/retrieved once at module import time via
``get_or_create_collection``.  The call is idempotent — if the collection
already exists, the existing one is returned unchanged.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TypedDict

import chromadb
from chromadb.config import Settings

from app.utils.logging_config import get_logger
from app.utils.paths import get_chroma_dir

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Collection names (used as keys by callers — never hard-code strings outside
# this module)
# ---------------------------------------------------------------------------

TEXT_COLLECTION = "text_chunks"
IMAGE_COLLECTION = "image_chunks"

# ---------------------------------------------------------------------------
# ChromaDB client + collection singletons
# ---------------------------------------------------------------------------

_client: chromadb.PersistentClient | None = None
_client_path: str | None = None
_text_collection: chromadb.Collection | None = None
_image_collection: chromadb.Collection | None = None


def _ensure_client() -> chromadb.PersistentClient:
    global _client, _client_path, _text_collection, _image_collection
    current_path = str(get_chroma_dir())
    if _client is None or _client_path != current_path:
        get_chroma_dir().mkdir(parents=True, exist_ok=True)
        _client_path = current_path
        _client = chromadb.PersistentClient(
            path=current_path,
            settings=Settings(anonymized_telemetry=False),
        )
        _text_collection = _client.get_or_create_collection(
            name=TEXT_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        _image_collection = _client.get_or_create_collection(
            name=IMAGE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB initialised at %s | text_chunks=%d docs | image_chunks=%d docs",
            current_path,
            _text_collection.count(),
            _image_collection.count(),
        )
    return _client


def _get_collection(collection_name: str) -> chromadb.Collection:
    """Return the collection object for *collection_name*."""
    _ensure_client()
    if collection_name == TEXT_COLLECTION:
        return _text_collection
    if collection_name == IMAGE_COLLECTION:
        return _image_collection
    raise ValueError(
        f"Unknown collection '{collection_name}'. "
        f"Use '{TEXT_COLLECTION}' or '{IMAGE_COLLECTION}'."
    )


# Initialize immediately for default paths
_ensure_client()


# ---------------------------------------------------------------------------
# Return type for query results
# ---------------------------------------------------------------------------


class QueryResult(TypedDict):
    """A single result returned from :func:`query`."""

    chunk_id: str
    score: float      # cosine similarity in [0, 1] (higher = more similar)
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_chunk(
    chunk_id: str,
    embedding: list[float],
    metadata: dict[str, Any],
    collection_name: str,
) -> None:
    """Upsert a single chunk vector into the specified ChromaDB collection.

    Uses ``upsert`` (not ``add``) so that re-running the backfill script on
    already-embedded chunks is safe and idempotent — the existing vector is
    simply overwritten with the same data.

    Args:
        chunk_id:        The chunk's UUID (from SQLite ``chunks.id``).  Used
                         as the ChromaDB document ID.
        embedding:       The float vector to store.
        metadata:        Arbitrary key-value pairs stored alongside the vector.
                         Keep values to str/int/float/bool — ChromaDB will
                         reject None values, so callers should filter them.
        collection_name: ``"text_chunks"`` or ``"image_chunks"``.

    Raises:
        ValueError: If *collection_name* is unknown.
    """
    collection = _get_collection(collection_name)
    # ChromaDB rejects None metadata values — sanitise to empty string.
    safe_meta = {k: ("" if v is None else v) for k, v in metadata.items()}
    collection.upsert(
        ids=[chunk_id],
        embeddings=[embedding],
        metadatas=[safe_meta],
    )
    logger.debug(
        "Upserted chunk_id=%s into '%s' (dim=%d)",
        chunk_id,
        collection_name,
        len(embedding),
    )


def query(
    embedding: list[float],
    collection_name: str,
    top_k: int = 10,
    where: dict[str, Any] | None = None,
) -> list[QueryResult]:
    """Query a ChromaDB collection for the *top_k* nearest neighbours.

    Args:
        embedding:       The query vector.
        collection_name: ``"text_chunks"`` or ``"image_chunks"``.
        top_k:           Number of results to return.
        where:           Optional ChromaDB ``where`` filter dict, e.g.
                         ``{"source_id": {"$eq": "<uuid>"}}`` to restrict
                         results to a specific upload.

    Returns:
        A list of up to *top_k* :class:`QueryResult` dicts, sorted by
        descending similarity score (most similar first).
        Returns an empty list if the collection is empty.

    Raises:
        ValueError: If *collection_name* is unknown.
    """
    collection = _get_collection(collection_name)

    if collection.count() == 0:
        logger.debug("Collection '%s' is empty — no results.", collection_name)
        return []

    # Clamp top_k to collection size to avoid ChromaDB errors.
    effective_k = min(top_k, collection.count())

    query_kwargs: dict[str, Any] = {
        "query_embeddings": [embedding],
        "n_results": effective_k,
        "include": ["metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    raw = collection.query(**query_kwargs)

    results: list[QueryResult] = []
    ids = raw["ids"][0]
    distances = raw["distances"][0]
    metadatas = raw["metadatas"][0]

    for chunk_id, dist, meta in zip(ids, distances, metadatas):
        # ChromaDB cosine distance is in [0, 2]; convert to similarity in [0, 1].
        # similarity = 1 - (distance / 2)  →  1.0 = identical, 0.0 = opposite
        similarity = round(1.0 - dist / 2.0, 6)
        results.append(
            QueryResult(chunk_id=chunk_id, score=similarity, metadata=meta)
        )

    # Results come back sorted by distance (ascending) = similarity (descending).
    return results


def collection_count(collection_name: str) -> int:
    """Return the number of vectors stored in *collection_name*.

    Useful for health checks and logging.

    Args:
        collection_name: ``"text_chunks"`` or ``"image_chunks"``.

    Returns:
        Integer count of stored documents.
    """
    return _get_collection(collection_name).count()


def delete_by_source(source_id: str) -> int:
    """Delete all chunks for *source_id* from both ChromaDB collections.

    Looks up chunk IDs for that source from SQLite, deletes those IDs from
    BOTH ChromaDB collections (text_chunks and image_chunks), tolerating
    IDs that are already missing, and returns the number removed.
    """
    from app.db.metadata_store import fetch_chunks_by_source

    chunks = fetch_chunks_by_source(source_id)
    chunk_ids = [c["id"] for c in chunks if isinstance(c, dict) and "id" in c]

    total_removed = 0
    for col_name in [TEXT_COLLECTION, IMAGE_COLLECTION]:
        col = _get_collection(col_name)
        if chunk_ids:
            try:
                existing = col.get(ids=chunk_ids)
                existing_ids = existing.get("ids", []) if existing else []
                if existing_ids:
                    col.delete(ids=existing_ids)
                    total_removed += len(existing_ids)
            except Exception as exc:
                logger.warning("Error deleting chunk IDs from %s: %s", col_name, exc)

        try:
            col.delete(where={"source_id": source_id})
        except Exception:
            pass

    logger.info("Deleted %d vector(s) for source_id=%s", total_removed, source_id)
    return total_removed

