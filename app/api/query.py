"""
app/api/query.py
-----------------
POST /query and POST /query/stream — Grounded Q&A with:
1. Whole-document mode
2. Labeled general-knowledge fallback
3. Friendly error mapping
4. Server-Sent Events (SSE) streaming with stage progression
5. Follow-up conversational rewriting

Pipeline
~~~~~~~~
1. Validate inputs (empty question guard, sources presence check).
2. Rewrite follow-up question if history is provided.
3. Check answer cache → instant return on hit.
4. Resolve mode: "document" vs "focused".
   - Document mode: fetch all text chunks of source in page order, skip vector search.
   - Focused mode: retrieve top_k text chunks and up to 2 image chunks separately.
5. Generate grounded answer (or stream tokens).
6. Fallback to general knowledge if NOT_IN_DOCUMENTS sentinel is detected.
7. Return clean answer, citations, and metadata.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.cache.cache_manager import (
    get_cached_answer,
    get_cached_retrieval,
    set_cached_answer,
    set_cached_retrieval,
)
from app.db.metadata_store import fetch_chunks_by_source, list_all_sources
from app.embeddings.image_embedder import embed_clip_text
from app.embeddings.text_embedder import embed_text
from app.generation.answer_generator import (
    NOT_IN_DOCUMENTS_TOKEN,
    generate_answer,
    generate_general_knowledge_answer,
    rewrite_question,
    stream_general_knowledge_answer,
    stream_grounded_answer,
)
from app.retrieval.reranker import rerank
from app.retrieval.vector_store import (
    IMAGE_COLLECTION,
    TEXT_COLLECTION,
    query,
)
from app.utils.errors import OmniLensError, map_exception_to_error
from app.utils.logging_config import get_logger, log_stage

logger = get_logger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RETRIEVAL_CANDIDATES = 20
_SAFE_CONTEXT_CHAR_LIMIT = 60_000  # Safe context limit for document mode

_OVERVIEW_KEYWORDS = [
    "how many",
    "count",
    "total",
    "number of",
    "list all",
    "summarize",
    "overview",
    "each",
    "every",
    "all the",
    "explain this document",
]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatTurn(BaseModel):
    """Previous conversational turn."""
    question: str
    answer: str


class QueryRequest(BaseModel):
    """Request body for POST /query and POST /query/stream."""

    question: str = Field(
        ...,
        description="Natural language question or search phrase.",
        examples=["What is the revenue for Q3?"],
    )
    source_id: Optional[str] = Field(
        default=None,
        description="Optional UUID to restrict results to a single uploaded document.",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of reranked chunks to pass to the answer generator.",
    )
    mode: Optional[str] = Field(
        default="auto",
        description="Retrieval mode: 'auto' (default), 'focused', or 'document'.",
    )
    allow_general: bool = Field(
        default=True,
        description="Whether to fall back to general knowledge if documents lack the answer.",
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Previous conversational turns (up to 3 turns) as [{'question', 'answer'}].",
    )


class CitedChunk(BaseModel):
    """Metadata for a single chunk cited in the answer."""

    chunk_id: str
    source_filename: str
    page_number: Optional[int] = None
    chunk_type: str
    vector_score: float = 0.0
    rerank_score: float = 0.0
    rerank_note: str = ""


class LatencyBreakdown(BaseModel):
    """Per-stage wall-clock latency in milliseconds."""

    embedding: float = 0.0
    retrieval: float = 0.0
    reranking: float = 0.0
    generation: float = 0.0
    total: float = 0.0


class QueryResponse(BaseModel):
    """Response body for POST /query."""

    answer: str
    cited_chunks: list[CitedChunk]
    cache_hit: bool
    model_used: Optional[str] = None
    latency_ms: LatencyBreakdown
    mode_used: str = "focused"
    answer_source: str = "documents"  # "documents" | "general_knowledge" | "not_found"
    notice: Optional[str] = None
    rewritten_question: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[_\-\.]+", " ", name.lower())
    cleaned = re.sub(r"[^a-z0-9 ]+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _match_source_by_filename(question: str) -> tuple[Optional[str], Optional[str]]:
    sources = list_all_sources()
    if not sources:
        return None, None

    norm_q = _normalize_name(question)
    norm_q_tokens = f" {norm_q} "

    for src in sorted(sources, key=lambda s: len(s.get("source_filename", "")), reverse=True):
        raw_name = src.get("source_filename", "")
        if not raw_name:
            continue

        candidates = [raw_name]
        stem = Path(raw_name).stem
        if stem != raw_name:
            candidates.append(stem)

        for cand in candidates:
            norm_cand = _normalize_name(cand)
            if not norm_cand or len(norm_cand) < 2:
                continue
            if f" {norm_cand} " in norm_q_tokens or norm_cand in norm_q:
                return src["source_id"], raw_name

    return None, None


def _is_aggregate_question(question: str) -> bool:
    q_lower = question.lower()
    return any(kw in q_lower for kw in _OVERVIEW_KEYWORDS)


def _build_where_filter(source_id: Optional[str]) -> dict[str, Any] | None:
    if not source_id:
        return None
    return {"source_id": {"$eq": source_id}}


def _raw_to_candidate(raw: dict[str, Any], collection_name: str) -> dict[str, Any]:
    meta = raw["metadata"]
    enriched = dict(raw)
    enriched["content_text"] = meta.get("content_text") or None
    enriched["content_image_path"] = meta.get("content_image_path") or None
    enriched["collection"] = collection_name
    return enriched


def _chunk_to_cited(chunk: dict[str, Any]) -> CitedChunk:
    meta = chunk.get("metadata", {})
    page_num = meta.get("page_number")
    return CitedChunk(
        chunk_id=chunk.get("chunk_id", ""),
        source_filename=meta.get("source_filename", ""),
        page_number=int(page_num) if page_num not in (None, "", -1) else None,
        chunk_type=meta.get("chunk_type", "text"),
        vector_score=round(float(chunk.get("vector_score", 0.0)), 6),
        rerank_score=round(float(chunk.get("rerank_score", 0.0)), 4),
        rerank_note=chunk.get("rerank_note", ""),
    )


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


# ---------------------------------------------------------------------------
# Pipeline Extraction (Shared by POST /query and POST /query/stream)
# ---------------------------------------------------------------------------


def _resolve_request(req: QueryRequest) -> tuple[str, str, Optional[str], Optional[str]]:
    """Validate input, rewrite query if history is present, and resolve source_id.

    Returns:
        (effective_question, original_question, effective_source_id, rewritten_question)
    """
    if not req.question or not req.question.strip():
        raise OmniLensError("empty_question")

    all_sources = list_all_sources()
    if not all_sources:
        raise OmniLensError("no_sources")

    effective_question = req.question.strip()
    rewritten_question: Optional[str] = None

    if req.history:
        rewritten = rewrite_question(effective_question, req.history)
        if rewritten and rewritten != effective_question:
            rewritten_question = rewritten
            effective_question = rewritten

    effective_source_id = req.source_id
    if not effective_source_id:
        matched_id, matched_name = _match_source_by_filename(effective_question)
        if matched_id:
            effective_source_id = matched_id
            logger.info("Matched source by filename: %s (id=%s)", matched_name, matched_id)

    return effective_question, req.question.strip(), effective_source_id, rewritten_question


def _determine_mode(req_mode: str, effective_source_id: Optional[str], question: str) -> str:
    """Determine whether to use 'document' or 'focused' mode."""
    if req_mode == "document":
        return "document"
    if req_mode == "auto" and effective_source_id and _is_aggregate_question(question):
        return "document"
    return "focused"


def _fetch_document_mode_chunks(source_id: str) -> list[dict[str, Any]]:
    """Fetch all text chunks of that source from SQLite in page order, truncating if exceeding safe limit."""
    all_chunks = fetch_chunks_by_source(source_id)
    text_chunks = [c for c in all_chunks if c.get("chunk_type") == "text"]

    if not text_chunks:
        # Fallback to any chunks if no text-only chunks exist
        text_chunks = all_chunks

    total_chars = 0
    selected_chunks: list[dict[str, Any]] = []

    for c in text_chunks:
        text = c.get("content_text") or ""
        if total_chars + len(text) > _SAFE_CONTEXT_CHAR_LIMIT and selected_chunks:
            logger.warning(
                "Document mode context limit reached (%d chars). Truncating at page %s.",
                total_chars,
                c.get("page_number"),
            )
            break
        total_chars += len(text)
        selected_chunks.append({
            "chunk_id": c["id"],
            "content_text": text,
            "rerank_score": 1.0,
            "vector_score": 1.0,
            "rerank_note": "document_mode",
            "metadata": {
                "chunk_type": c.get("chunk_type", "text"),
                "source_filename": c.get("source_filename", ""),
                "page_number": c.get("page_number"),
                "content_text": text,
            },
        })

    logger.info("Document mode prepared %d chunks (%d chars) for source=%s", len(selected_chunks), total_chars, source_id)
    return selected_chunks


def _fetch_focused_mode_chunks(
    question: str,
    source_id: Optional[str],
    top_k: int,
    latency: dict[str, float],
) -> list[dict[str, Any]]:
    """Retrieve top_k text chunks and up to 2 image chunks separately."""
    where = _build_where_filter(source_id)

    # 1. Embedding
    t_embed = time.perf_counter()
    text_embedding = embed_text(question)
    clip_embedding = embed_clip_text(question)
    latency["embedding"] = _ms(time.perf_counter() - t_embed)

    # 2. Vector search (both collections)
    t_retrieval = time.perf_counter()
    text_raw = query(
        embedding=text_embedding,
        collection_name=TEXT_COLLECTION,
        top_k=_RETRIEVAL_CANDIDATES,
        where=where,
    )
    image_raw = query(
        embedding=clip_embedding,
        collection_name=IMAGE_COLLECTION,
        top_k=_RETRIEVAL_CANDIDATES,
        where=where,
    )
    latency["retrieval"] = _ms(time.perf_counter() - t_retrieval)

    text_candidates = [_raw_to_candidate(r, TEXT_COLLECTION) for r in text_raw]
    image_candidates = [_raw_to_candidate(r, IMAGE_COLLECTION) for r in image_raw]

    # 3. Rerank text candidates and image candidates separately so images don't crowd out text pages
    t_rerank = time.perf_counter()
    reranked_text = rerank(question=question, candidates=text_candidates, top_k=top_k) if text_candidates else []
    reranked_images = rerank(question=question, candidates=image_candidates, top_k=min(2, len(image_candidates))) if image_candidates else []

    latency["reranking"] = _ms(time.perf_counter() - t_rerank)

    # Combined candidate pool for the generator
    return reranked_text + reranked_images


# ---------------------------------------------------------------------------
# POST /query (Non-Streaming)
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Grounded Q&A with reranking, caching, and cited sources",
)
async def semantic_query(req: QueryRequest) -> JSONResponse:
    """Run the non-streaming Q&A pipeline."""
    t_total_start = time.perf_counter()
    latency: dict[str, float] = {
        "embedding": 0.0,
        "retrieval": 0.0,
        "reranking": 0.0,
        "generation": 0.0,
    }

    try:
        effective_question, orig_question, effective_source_id, rewritten_question = _resolve_request(req)
        mode_used = _determine_mode(req.mode or "auto", effective_source_id, effective_question)

        # -------------------------------------------------------------------
        # Cache Check
        # -------------------------------------------------------------------
        cached_answer = get_cached_answer(
            effective_question,
            effective_source_id,
            mode_used=mode_used,
            allow_general=req.allow_general,
        )
        if cached_answer is not None:
            latency["total"] = _ms(time.perf_counter() - t_total_start)
            cached_answer["latency_ms"]["total"] = latency["total"]
            cached_answer["cache_hit"] = True
            logger.info("Answer cache HIT — returning in %.1f ms", latency["total"])
            return JSONResponse(content=cached_answer)

        # -------------------------------------------------------------------
        # Candidate Acquisition
        # -------------------------------------------------------------------
        if mode_used == "document" and effective_source_id:
            chunks = _fetch_document_mode_chunks(effective_source_id)
            retrieval_cache_hit = False
        else:
            cached_retrieval = get_cached_retrieval(effective_question, effective_source_id)
            if cached_retrieval is not None:
                chunks = cached_retrieval[: req.top_k + 2]
                retrieval_cache_hit = True
                logger.info("Retrieval cache HIT — skipping embed + search + rerank.")
            else:
                chunks = _fetch_focused_mode_chunks(effective_question, effective_source_id, req.top_k, latency)
                set_cached_retrieval(effective_question, effective_source_id, chunks)
                retrieval_cache_hit = False

        # -------------------------------------------------------------------
        # Generation & General Knowledge Fallback
        # -------------------------------------------------------------------
        t_gen = time.perf_counter()
        gen_result = generate_answer(question=effective_question, reranked_chunks=chunks)
        raw_answer = gen_result["answer"]
        model_used = gen_result.get("model_used")

        # Sentinel Detection
        if NOT_IN_DOCUMENTS_TOKEN in raw_answer.strip():
            logger.info("NOT_IN_DOCUMENTS detected. allow_general=%s", req.allow_general)
            if req.allow_general:
                gk_result = generate_general_knowledge_answer(effective_question)
                answer_text = gk_result["answer"]
                model_used = gk_result.get("model_used")
                answer_source = "general_knowledge"
                notice = "This isn't in the selected document." if effective_source_id else "Not found in your documents"
                cited_chunks_meta = []
            else:
                answer_text = "I don't have enough information in the provided sources to answer this question."
                answer_source = "not_found"
                notice = "This isn't in the selected document." if effective_source_id else "Not found in your documents"
                cited_chunks_meta = []
        else:
            answer_text = raw_answer
            answer_source = "documents"
            notice = None
            cited_chunk_ids = set(gen_result.get("cited_chunks", []))
            cited_chunks_meta = [
                _chunk_to_cited(c) for c in chunks if c.get("chunk_id", "") in cited_chunk_ids
            ]
            if not cited_chunks_meta and chunks:
                cited_chunks_meta = [_chunk_to_cited(c) for c in chunks[:req.top_k]]

        latency["generation"] = _ms(time.perf_counter() - t_gen)
        latency["total"] = _ms(time.perf_counter() - t_total_start)

        response_payload = {
            "answer": answer_text,
            "cited_chunks": [c.model_dump() for c in cited_chunks_meta],
            "cache_hit": retrieval_cache_hit,
            "model_used": model_used,
            "latency_ms": latency,
            "mode_used": mode_used,
            "answer_source": answer_source,
            "notice": notice,
            "rewritten_question": rewritten_question,
        }

        # Cache on successful generation
        set_cached_answer(
            effective_question,
            effective_source_id,
            response_payload,
            mode_used=mode_used,
            allow_general=req.allow_general,
            answer_source=answer_source,
        )

        return JSONResponse(content=response_payload)

    except Exception as exc:
        err = map_exception_to_error(exc)
        return err.to_response()


# ---------------------------------------------------------------------------
# POST /query/stream (Server-Sent Events)
# ---------------------------------------------------------------------------


@router.post(
    "/query/stream",
    summary="Grounded Q&A stream with real-time stage events",
)
async def semantic_query_stream(req: QueryRequest) -> StreamingResponse:
    """Stream grounded answer generation with SSE."""

    async def event_generator() -> AsyncGenerator[str, None]:
        t_total_start = time.perf_counter()
        latency: dict[str, float] = {
            "embedding": 0.0,
            "retrieval": 0.0,
            "reranking": 0.0,
            "generation": 0.0,
        }

        def _sse(event_data: dict[str, Any]) -> str:
            return f"data: {json.dumps(event_data)}\n\n"

        try:
            # 1. Validation & Question Rewrite
            if req.history:
                yield _sse({"type": "stage", "stage": "rewriting"})

            effective_question, orig_question, effective_source_id, rewritten_question = _resolve_request(req)
            mode_used = _determine_mode(req.mode or "auto", effective_source_id, effective_question)

            # 2. Cache Check
            cached = get_cached_answer(
                effective_question,
                effective_source_id,
                mode_used=mode_used,
                allow_general=req.allow_general,
            )
            if cached is not None:
                yield _sse({"type": "stage", "stage": "generating"})
                yield _sse({"type": "token", "text": cached["answer"]})
                cached["cache_hit"] = True
                cached["latency_ms"]["total"] = _ms(time.perf_counter() - t_total_start)
                yield _sse({
                    "type": "meta",
                    "cited_chunks": cached.get("cited_chunks", []),
                    "answer_source": cached.get("answer_source", "documents"),
                    "notice": cached.get("notice"),
                    "mode_used": cached.get("mode_used", mode_used),
                    "model_used": cached.get("model_used"),
                    "latency_ms": cached.get("latency_ms", latency),
                    "rewritten_question": rewritten_question,
                    "cache_hit": True,
                })
                yield _sse({"type": "done"})
                return

            # 3. Retrieval Stages
            yield _sse({"type": "stage", "stage": "searching"})
            if mode_used == "document" and effective_source_id:
                chunks = _fetch_document_mode_chunks(effective_source_id)
            else:
                yield _sse({"type": "stage", "stage": "reranking"})
                chunks = _fetch_focused_mode_chunks(effective_question, effective_source_id, req.top_k, latency)

            # 4. Generating Stage
            yield _sse({"type": "stage", "stage": "generating"})
            t_gen = time.perf_counter()

            # Stream grounded answer
            grounded_gen = stream_grounded_answer(effective_question, chunks)
            sentinel_encountered = False
            model_used: Optional[str] = None
            accumulated_text = ""
            cited_chunk_ids: list[str] = []

            for event in grounded_gen:
                if event.get("type") == "sentinel":
                    sentinel_encountered = True
                    model_used = event.get("model_used")
                    break
                elif event.get("type") == "token":
                    accumulated_text += event["text"]
                    yield _sse({"type": "token", "text": event["text"]})
                elif event.get("type") == "complete":
                    accumulated_text = event.get("answer", accumulated_text)
                    cited_chunk_ids = event.get("cited_chunks", [])
                    model_used = event.get("model_used")

            # Fallback Handling if Sentinel Encountered
            if sentinel_encountered:
                if req.allow_general:
                    answer_source = "general_knowledge"
                    notice = "This isn't in the selected document." if effective_source_id else "Not found in your documents"
                    cited_chunks_meta = []
                    gk_accumulated = ""
                    for gk_event in stream_general_knowledge_answer(effective_question):
                        if gk_event.get("type") == "token":
                            gk_accumulated += gk_event["text"]
                            yield _sse({"type": "token", "text": gk_event["text"]})
                        elif gk_event.get("type") == "complete":
                            accumulated_text = gk_event.get("answer", gk_accumulated)
                            model_used = gk_event.get("model_used")
                else:
                    answer_source = "not_found"
                    notice = "This isn't in the selected document." if effective_source_id else "Not found in your documents"
                    refusal = "I don't have enough information in the provided sources to answer this question."
                    yield _sse({"type": "token", "text": refusal})
                    accumulated_text = refusal
                    cited_chunks_meta = []
            else:
                answer_source = "documents"
                notice = None
                cited_chunks_meta = [
                    _chunk_to_cited(c) for c in chunks if c.get("chunk_id", "") in set(cited_chunk_ids)
                ]
                if not cited_chunks_meta and chunks:
                    cited_chunks_meta = [_chunk_to_cited(c) for c in chunks[:req.top_k]]

            latency["generation"] = _ms(time.perf_counter() - t_gen)
            latency["total"] = _ms(time.perf_counter() - t_total_start)

            # Metadata Event
            meta_payload = {
                "cited_chunks": [c.model_dump() for c in cited_chunks_meta],
                "answer_source": answer_source,
                "notice": notice,
                "mode_used": mode_used,
                "model_used": model_used,
                "latency_ms": latency,
                "rewritten_question": rewritten_question,
                "cache_hit": False,
            }
            yield _sse({"type": "meta", **meta_payload})

            # Done Event
            yield _sse({"type": "done"})

            # Cache completed answer
            full_payload = {
                "answer": accumulated_text,
                **meta_payload,
            }
            set_cached_answer(
                effective_question,
                effective_source_id,
                full_payload,
                mode_used=mode_used,
                allow_general=req.allow_general,
                answer_source=answer_source,
            )

        except Exception as exc:
            err = map_exception_to_error(exc)
            yield _sse({
                "type": "error",
                "error_code": err.error_code,
                "message": err.message,
                "retryable": True,
            })
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
