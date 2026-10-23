"""
app/embeddings/text_embedder.py
--------------------------------
Text embedding for OmniLens using ``sentence-transformers``.

Model: ``all-MiniLM-L6-v2``
  - Output dimension: **384**
  - Fully CPU-friendly — no GPU required.
  - ~22 MB on disk; loads in ~1-2 s cold start on a typical laptop.

Design decision — module-level singleton
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The ``SentenceTransformer`` is instantiated ONCE when this module is first
imported.  Every subsequent call reuses the cached model object.  This is
critical on CPU: loading the model per-request would add ~1-2 s to every
embedding call, which is unacceptable.

Embedding space note
~~~~~~~~~~~~~~~~~~~~~
These embeddings are used exclusively for **text chunks** (``chunk_type="text"``
rows from PDFs).  Image chunks are embedded separately via CLIP's image encoder
(see ``app/embeddings/image_embedder.py``).  At query time the user's question
is embedded with this model to search text chunks, and *also* embedded with
CLIP's text encoder to search image chunks — two separate lookups against two
separate ChromaDB collections.  We do NOT attempt to force a single joint
embedding space, which is simpler and more reliable on CPU.
"""

import time
from pathlib import Path

from sentence_transformers import SentenceTransformer

from app.cache.cache_manager import get_cached_embedding, hash_content, set_cached_embedding
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

MODEL_NAME = "all-MiniLM-L6-v2"

#: Output embedding dimension for all-MiniLM-L6-v2.
EMBEDDING_DIM = 384

# ---------------------------------------------------------------------------
# Module-level singleton — loaded exactly once
# ---------------------------------------------------------------------------

_t_load_start = time.perf_counter()
logger.info("Loading sentence-transformers model '%s'…", MODEL_NAME)

_model = SentenceTransformer(MODEL_NAME)

_load_elapsed = time.perf_counter() - _t_load_start
logger.info(
    "sentence-transformers model '%s' loaded in %.2fs (dim=%d)",
    MODEL_NAME,
    _load_elapsed,
    EMBEDDING_DIM,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(text: str) -> list[float]:
    """Embed a single text string and return a 384-dim float vector.

    Results are cached on disk by a SHA-256 hash of the input text so that
    identical content is never re-embedded across requests or restarts.

    Args:
        text: The text to embed.  Empty strings are allowed — the model will
              return a valid (though uninformative) vector.

    Returns:
        A list of 384 floats representing the sentence embedding.
    """
    content_hash = hash_content(text)
    cached = get_cached_embedding(content_hash)
    if cached is not None:
        return cached

    vector = _model.encode(text, convert_to_numpy=True)
    result = vector.tolist()
    set_cached_embedding(content_hash, result)
    return result


def embed_text_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of text strings efficiently, with per-item cache lookups.

    Checks the embedding cache for each text first.  Only the cache-missed
    texts are sent to the model in a single batched forward pass.  Cached
    results are merged back in the original order.

    Args:
        texts: A list of text strings to embed.

    Returns:
        A list of 384-dim float vectors, one per input string, in the same
        order as *texts*.

    Raises:
        ValueError: If *texts* is empty.
    """
    if not texts:
        raise ValueError("texts must not be empty")

    hashes = [hash_content(t) for t in texts]
    results: list[list[float] | None] = [get_cached_embedding(h) for h in hashes]

    # Collect indices and texts that had cache misses
    miss_indices = [i for i, r in enumerate(results) if r is None]
    if miss_indices:
        miss_texts = [texts[i] for i in miss_indices]
        new_vectors = _model.encode(
            miss_texts, convert_to_numpy=True, show_progress_bar=False
        )
        for i, vec in zip(miss_indices, new_vectors):
            embedding = vec.tolist()
            results[i] = embedding
            set_cached_embedding(hashes[i], embedding)

    return results  # type: ignore[return-value]  # all None slots filled above
