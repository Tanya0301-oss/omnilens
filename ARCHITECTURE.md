# Architecture — OmniLens

## High-Level Pipeline
```
Upload (PDF/Image/Video)
    → Ingestion Service (detect type, route)
    → Processing (OCR / layout parse / frame extract / ASR / object detection)
    → Chunking (page/section for PDF, region for image, timestamp segment for video)
    → Embedding (text via sentence-transformers, visual via CLIP — shared comparable space)
    → Store (ChromaDB for vectors, SQLite for metadata)

Query
    → Embed query
    → Retrieve top-k candidates from ChromaDB (hybrid: vector + metadata filter)
    → Rerank top-k with cross-encoder
    → Generate answer (Groq API, grounded in reranked chunks)
    → Return answer + cited source (page number / bbox / timestamp)
```

## Folder Structure
```
omnilens/
├── app/
│   ├── main.py                  # FastAPI entrypoint
│   ├── api/
│   │   ├── upload.py             # upload endpoints
│   │   ├── query.py               # query/ask endpoints
│   │   └── status.py              # job status endpoints
│   ├── ingestion/
│   │   ├── pdf_parser.py
│   │   ├── image_parser.py
│   │   └── video_parser.py        # stretch goal
│   ├── embeddings/
│   │   ├── text_embedder.py
│   │   └── image_embedder.py
│   ├── retrieval/
│   │   ├── vector_store.py         # ChromaDB wrapper
│   │   ├── reranker.py
│   │   └── hybrid_search.py
│   ├── generation/
│   │   └── answer_generator.py     # Groq API calls
│   ├── cache/
│   │   └── cache_manager.py        # diskcache wrapper, 3 cache layers
│   ├── db/
│   │   └── metadata_store.py       # SQLite wrapper
│   └── utils/
│       └── logging_config.py
├── frontend/                        # Streamlit or React app
├── eval/
│   ├── test_set.json                # ~20 Q&A pairs for evaluation
│   └── run_eval.py
├── data/
│   ├── uploads/                      # raw uploaded files
│   └── chroma_db/                    # ChromaDB storage directory
├── requirements.txt
├── .env.example                      # API keys (GROQ_API_KEY, etc.) — never commit real keys
└── README.md
```

## Key Design Decisions (and why — for interview talking points)
1. **ChromaDB over Qdrant/Pinecone** — embedded/file-based, no server process, fits a no-Docker constraint while still being a real production-used vector DB.
2. **Two-stage retrieve → rerank → generate** — cheap vector search narrows to top-50, cross-encoder reranks to top-5-10 before the expensive LLM call. Controls cost and improves answer relevance.
3. **Three-layer caching** — query-result cache, embedding cache (dedup identical content), retrieval cache (before reranking) — avoids recomputation at each expensive stage.
4. **Shared embedding space (CLIP + text embeddings aligned)** — enables true cross-modal search: a text query can retrieve an image, not just other text.
5. **Evidence grounding by design** — metadata (page number, bbox, timestamp) is stored alongside every chunk from the start, not bolted on later, so every answer can cite its exact source.
6. **No message queue (Kafka/RabbitMQ) in MVP** — intentional scope decision for a no-Docker/local setup. Document this as the "next step for production scale" in the README rather than pretending it's not needed.

## Scaling Notes (document in README, don't necessarily build)
- Replace `multiprocessing` background jobs with a real queue (Redis Streams/Kafka) when moving beyond single-machine.
- Swap ChromaDB for Qdrant (self-hosted via Docker) when data volume grows beyond what an embedded DB handles well.
- Move caching to Redis when scaling beyond a single process.
- Add Prometheus + Grafana for real observability at scale.

This "I know what I'd change for production, and why I didn't do it for this scope" framing is good for interviews — it shows you understand the end state and made intentional MVP trade-offs rather than being unaware of the growth path.
