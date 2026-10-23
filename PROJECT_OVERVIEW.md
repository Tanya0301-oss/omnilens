# OmniLens — Multimodal AI Intelligence & Visual RAG Platform

## One-line pitch
Upload a PDF, image, or video → OmniLens understands it, indexes its visual/text/audio content, and lets you ask natural-language questions and get evidence-grounded answers (with page numbers, bounding boxes, or timestamps).

## Problem Statement
Most RAG (Retrieval-Augmented Generation) systems only handle plain text. Real-world knowledge lives across mixed media — PDFs with diagrams, scanned documents, images, and videos with spoken content. There is no simple, self-hosted, free system that lets a user upload any of these and query across all of them in one place, with answers traceable back to an exact source location (not just "trust me, the AI read it").

OmniLens solves this by building a unified multimodal knowledge index and a retrieval + generation pipeline that treats text, images, and video/audio as first-class, cross-searchable content.

## Core Features (MVP scope, in priority order)
1. **PDF ingestion** — parse text + layout + embedded images, chunk by page/section.
2. **Image ingestion** — OCR + visual captioning/object detection, embed for search.
3. **Cross-modal semantic search** — one query can retrieve a text chunk or an image region.
4. **Grounded Q&A** — answers cite exact source (page number / bounding box).
5. **Video ingestion (stretch goal)** — frame sampling + ASR transcript, timestamp-synced search and Q&A.

## What makes this project non-trivial (not "just an API wrapper")
- Custom chunking strategy across different content types (text vs layout vs visual vs temporal).
- A shared embedding space so a query matches across modalities, not separate silos.
- Two-stage retrieve → rerank → generate pipeline (not naive top-k-to-LLM).
- Evidence grounding: every answer must cite its exact source location.
- Caching and async processing designed for realistic scale, not just a demo script.

## Success Criteria / Evaluation
- Build a custom test set of ~20 question–answer pairs across uploaded documents/images (and video, if built).
- Report retrieval accuracy (did the right chunk get retrieved in top-k?) and answer correctness.
- Demo: live query against a real PDF + image, showing cited source location in the UI.

## Target Users (for framing, not for real deployment)
Students, researchers, or analysts who need to search and ask questions across a pile of mixed-format documents instead of manually skimming each one.

## Out of Scope (for now)
- Multi-user auth / accounts (single-user local demo is fine).
- Production-grade deployment at scale.
- Fine-tuning any models from scratch — this project uses pretrained models + strong system design around them.
