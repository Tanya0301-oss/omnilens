"""
app/main.py
-----------
OmniLens FastAPI application entrypoint.

Starts the application, initialises the SQLite metadata store, and mounts
all API routers.  Run locally with::

    uvicorn app.main:app --reload

or via the helper at the bottom::

    python -m app.main
"""

from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env file before anything else runs
load_dotenv()

from app.api import query, source_management, status, upload
from app.db.metadata_store import init_db
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OmniLens",
    description=(
        "Multimodal AI RAG platform — upload PDFs and images, query across "
        "all content with grounded, cited answers."
    ),
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow all origins in development; tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup hook — initialise storage
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_event() -> None:
    """Initialise resources when the application starts."""
    logger.info("OmniLens starting up (v0.2.0)...")
    init_db()
    logger.info(
        "OmniLens ready. "
        "Docs: http://127.0.0.1:8000/docs | "
        "Upload: POST /upload | Query: POST /query | Status: GET /source/{id}"
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(upload.router, tags=["Ingestion"])
app.include_router(status.router, tags=["Status"])
app.include_router(source_management.router, tags=["Source Management"])
app.include_router(query.router, tags=["Retrieval"])


@app.get("/", tags=["Meta"], summary="Root endpoint")
async def root() -> dict[str, Any]:
    """OmniLens API root overview and navigation."""
    return {
        "app": "OmniLens",
        "version": "0.3.0",
        "status": "online",
        "docs": "/docs",
        "endpoints": {
            "upload": "POST /upload",
            "query": "POST /query",
            "source_status": "GET /source/{source_id}",
            "health": "GET /health",
        },
    }


@app.get("/health", tags=["Meta"], summary="Health check")
async def health() -> dict[str, str]:
    """Return a simple liveness signal.

    Returns:
        ``{"status": "ok"}``
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
