"""
app/cache/cache_manager.py
---------------------------
Three-layer diskcache wrapper for OmniLens.

Cache layers
~~~~~~~~~~~~~
1. **Answer cache** (``answers/`` sub-directory, TTL 1 hour)
   Key: ``hash(question, source_id, mode_used, allow_general, answer_source)``
   Caches the final generated answer. Ensures general-knowledge answers are
   never served as document answers.

2. **Embedding cache** (``embeddings/`` sub-directory, no TTL)
   Key: SHA-256 hash of the raw text or image bytes.
   Avoids re-embedding identical content.

3. **Retrieval cache** (``retrieval/`` sub-directory, TTL 30 minutes)
   Key: ``(question, source_id or "all")``
   Caches the reranked chunk list before the LLM generation step.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

import diskcache

from app.utils.paths import get_cache_root

logger = logging.getLogger(__name__)

# TTLs in seconds
_ANSWER_TTL = 3_600          # 1 hour
_RETRIEVAL_TTL = 1_800       # 30 minutes
_EMBEDDING_TTL = None        # permanent

# ---------------------------------------------------------------------------
# Module-level cache singletons
# ---------------------------------------------------------------------------

_active_cache_root: str | None = None
_answer_cache: diskcache.Cache = None
_embedding_cache: diskcache.Cache = None
_retrieval_cache: diskcache.Cache = None


def reset_caches() -> None:
    """Re-initialize disk caches pointing to the current get_cache_root()."""
    global _answer_cache, _embedding_cache, _retrieval_cache, _active_cache_root
    cache_root = get_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    _active_cache_root = str(cache_root)
    _answer_cache = diskcache.Cache(str(cache_root / "answers"))
    _embedding_cache = diskcache.Cache(str(cache_root / "embeddings"))
    _retrieval_cache = diskcache.Cache(str(cache_root / "retrieval"))
    logger.info("Cache initialised at %s", cache_root)


def _ensure_caches() -> None:
    if _active_cache_root != str(get_cache_root()) or _answer_cache is None:
        reset_caches()


reset_caches()


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def hash_content(text_or_bytes: str | bytes) -> str:
    """Return a SHA-256 hex digest of *text_or_bytes*."""
    raw = text_or_bytes.encode("utf-8") if isinstance(text_or_bytes, str) else text_or_bytes
    return hashlib.sha256(raw).hexdigest()


def _answer_key(
    question: str,
    source_id: Optional[str],
    mode_used: str = "focused",
    allow_general: bool = True,
    answer_source: str = "documents",
) -> str:
    """Stable cache key for the answer layer including mode, allow_general, and answer_source."""
    norm_q = question.strip().lower()
    src = source_id or "all"
    return hash_content(f"answer::{norm_q}::{src}::{mode_used}::{allow_general}::{answer_source}")


def _retrieval_key(question: str, source_id: Optional[str]) -> str:
    """Stable cache key for the retrieval layer."""
    return hash_content(f"retrieval::{question.strip().lower()}::{source_id or 'all'}")


# ---------------------------------------------------------------------------
# Layer 1: Answer cache
# ---------------------------------------------------------------------------


def get_cached_answer(
    question: str,
    source_id: Optional[str],
    mode_used: str = "auto",
    allow_general: bool = True,
) -> Optional[dict[str, Any]]:
    """Look up a previously generated answer.

    Never serves a general-knowledge answer if allow_general is False or when
    document answers are expected.
    """
    modes_to_try = [mode_used] if mode_used != "auto" else ["focused", "document"]

    # 1. First, try looking for a grounded document answer
    for m in modes_to_try:
        for gen_flag in [True, False]:
            key = _answer_key(question, source_id, mode_used=m, allow_general=gen_flag, answer_source="documents")
            try:
                val = _answer_cache.get(key)
                if val is not None and val.get("answer_source") == "documents":
                    logger.debug("Answer cache HIT (documents) for question='%s'", question[:60])
                    return val
            except Exception:
                pass

    # 2. If allow_general is True, try general_knowledge
    if allow_general:
        for m in modes_to_try:
            key = _answer_key(question, source_id, mode_used=m, allow_general=True, answer_source="general_knowledge")
            try:
                val = _answer_cache.get(key)
                if val is not None and val.get("answer_source") == "general_knowledge":
                    logger.debug("Answer cache HIT (general_knowledge) for question='%s'", question[:60])
                    return val
            except Exception:
                pass
    else:
        # Check for cached not_found refusal if allow_general is False
        for m in modes_to_try:
            key = _answer_key(question, source_id, mode_used=m, allow_general=False, answer_source="not_found")
            try:
                val = _answer_cache.get(key)
                if val is not None and val.get("answer_source") == "not_found":
                    logger.debug("Answer cache HIT (not_found) for question='%s'", question[:60])
                    return val
            except Exception:
                pass

    # 3. Fallback to legacy key (for existing Step-3 test cases)
    legacy_key = hash_content(f"answer::{question.strip().lower()}::{source_id or 'all'}")
    try:
        legacy_val = _answer_cache.get(legacy_key)
        if legacy_val is not None:
            # If legacy answer has answer_source == 'general_knowledge' and allow_general is False, do not serve
            if legacy_val.get("answer_source") == "general_knowledge" and not allow_general:
                return None
            return legacy_val
    except Exception:
        pass

    return None


def set_cached_answer(
    question: str,
    source_id: Optional[str],
    answer: dict[str, Any],
    mode_used: str = "focused",
    allow_general: bool = True,
    answer_source: str = "documents",
) -> None:
    """Store a generated answer in the answer cache with all discriminant keys."""
    ans_src = answer.get("answer_source", answer_source)
    m_used = answer.get("mode_used", mode_used)
    key = _answer_key(question, source_id, mode_used=m_used, allow_general=allow_general, answer_source=ans_src)
    try:
        _answer_cache.set(key, answer, expire=_ANSWER_TTL)
        logger.debug("Answer cache SET for key=%s", key[:12])
        # Also set legacy key for document answers
        if ans_src == "documents":
            legacy_key = hash_content(f"answer::{question.strip().lower()}::{source_id or 'all'}")
            _answer_cache.set(legacy_key, answer, expire=_ANSWER_TTL)
    except Exception:
        logger.warning("Answer cache set failed for key=%s", key, exc_info=True)


# ---------------------------------------------------------------------------
# Layer 2: Embedding cache
# ---------------------------------------------------------------------------


def get_cached_embedding(content_hash: str) -> Optional[list[float]]:
    """Look up a cached embedding by content hash."""
    try:
        value = _embedding_cache.get(content_hash)
        if value is not None:
            logger.debug("Embedding cache HIT hash=%s...", content_hash[:12])
        return value
    except Exception:
        logger.warning(
            "Embedding cache get failed for hash=%s", content_hash, exc_info=True
        )
        return None


def set_cached_embedding(content_hash: str, embedding: list[float]) -> None:
    """Store an embedding vector keyed by content hash."""
    try:
        _embedding_cache.set(content_hash, embedding, expire=_EMBEDDING_TTL)
        logger.debug("Embedding cache SET hash=%s...", content_hash[:12])
    except Exception:
        logger.warning(
            "Embedding cache set failed for hash=%s", content_hash, exc_info=True
        )


# ---------------------------------------------------------------------------
# Layer 3: Retrieval cache (reranked chunks before LLM generation)
# ---------------------------------------------------------------------------


def get_cached_retrieval(
    question: str, source_id: Optional[str]
) -> Optional[list[dict[str, Any]]]:
    """Look up cached reranked retrieval results."""
    key = _retrieval_key(question, source_id)
    try:
        value = _retrieval_cache.get(key)
        if value is not None:
            logger.debug("Retrieval cache HIT for question='%s'", question[:60])
        return value
    except Exception:
        logger.warning(
            "Retrieval cache get failed for key=%s", key, exc_info=True
        )
        return None


def set_cached_retrieval(
    question: str,
    source_id: Optional[str],
    results: list[dict[str, Any]],
) -> None:
    """Store reranked retrieval results in the retrieval cache."""
    key = _retrieval_key(question, source_id)
    try:
        _retrieval_cache.set(key, results, expire=_RETRIEVAL_TTL)
        logger.debug(
            "Retrieval cache SET for question='%s' (%d chunks)",
            question[:60],
            len(results),
        )
    except Exception:
        logger.warning(
            "Retrieval cache set failed for key=%s", key, exc_info=True
        )


# ---------------------------------------------------------------------------
# Utility — cache statistics
# ---------------------------------------------------------------------------


def cache_stats() -> dict[str, int]:
    """Return the current size of each cache layer."""
    return {
        "answers": len(_answer_cache),
        "embeddings": len(_embedding_cache),
        "retrieval": len(_retrieval_cache),
    }
