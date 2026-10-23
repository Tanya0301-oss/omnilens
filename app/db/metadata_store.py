"""
app/db/metadata_store.py
------------------------
SQLite-backed metadata store for OmniLens chunk records and source tracking.

Schema (table: ``chunks``)
~~~~~~~~~~~~~~~~~~~~~~~~~~
- id               TEXT PRIMARY KEY  — UUID assigned at insert time
- source_id        TEXT NOT NULL      — UUID that groups all chunks from one upload
- source_filename  TEXT NOT NULL      — original filename as uploaded
- source_type      TEXT NOT NULL      — "pdf" | "image"
- page_number      INTEGER            — 1-based page index (NULL for standalone images)
- bbox             TEXT               — JSON string e.g. '{"x":10,"y":20,"w":50,"h":30}'
- chunk_type       TEXT NOT NULL      — "text" | "image_region"
- content_text     TEXT               — extracted / OCR text (NULL for image-only chunks)
- content_image_path TEXT             — relative path under data/uploads/ (NULL for text-only)
- created_at       TEXT NOT NULL      — ISO-8601 timestamp
- embedded         INTEGER NOT NULL DEFAULT 0 — 1 once the chunk has been embedded into ChromaDB

Schema (table: ``sources``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- source_id         TEXT PRIMARY KEY
- filename          TEXT NOT NULL
- source_type       TEXT NOT NULL        — "pdf" | "image"
- stored_path       TEXT                 — relative path to the uploaded file
- status            TEXT NOT NULL DEFAULT 'queued'  — queued|processing|ready|failed
- stage             TEXT                 — current stage label
- progress          INTEGER DEFAULT 0    — 0-100
- error_message     TEXT                 — friendly user-facing error
- chunk_count       INTEGER DEFAULT 0
- suggested_questions TEXT               — JSON array of 4 strings, or NULL
- file_hash         TEXT
- created_at        TEXT NOT NULL
- updated_at        TEXT NOT NULL
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.utils.logging_config import get_logger
from app.utils.paths import get_db_path, get_uploads_dir

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# DDL — chunks table
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    id                 TEXT    PRIMARY KEY,
    source_id          TEXT    NOT NULL,
    source_filename    TEXT    NOT NULL,
    source_type        TEXT    NOT NULL,
    page_number        INTEGER,
    bbox               TEXT,
    chunk_type         TEXT    NOT NULL,
    content_text       TEXT,
    content_image_path TEXT,
    created_at         TEXT    NOT NULL,
    embedded           INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks (source_id);
"""

_MIGRATE_ADD_EMBEDDED_SQL = "ALTER TABLE chunks ADD COLUMN embedded INTEGER NOT NULL DEFAULT 0;"

# ---------------------------------------------------------------------------
# DDL — sources table
# ---------------------------------------------------------------------------

_CREATE_SOURCES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    source_id           TEXT    PRIMARY KEY,
    filename            TEXT    NOT NULL,
    source_type         TEXT    NOT NULL,
    stored_path         TEXT,
    status              TEXT    NOT NULL DEFAULT 'queued',
    stage               TEXT,
    progress            INTEGER DEFAULT 0,
    error_message       TEXT,
    chunk_count         INTEGER DEFAULT 0,
    suggested_questions TEXT,
    file_hash           TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

_CREATE_SOURCES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources (status);
"""


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    """Open (and lazily create) the SQLite database."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create all tables and indexes; run safe migrations."""
    with _get_connection() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.execute(_CREATE_SOURCES_TABLE_SQL)
        conn.execute(_CREATE_SOURCES_INDEX_SQL)
        # Safe migration: add embedded column if missing
        try:
            conn.execute(_MIGRATE_ADD_EMBEDDED_SQL)
        except Exception:
            pass
        conn.commit()

    # Migration: create sources rows for existing chunk data that has no sources row
    _migrate_chunks_to_sources()

    # On startup, mark interrupted sources as failed
    _mark_interrupted_as_failed()

    logger.info("SQLite metadata store initialised at %s", get_db_path())


def _migrate_chunks_to_sources() -> None:
    """For each distinct source_id in chunks with no sources row, create one with status='ready'."""
    uploads_dir = get_uploads_dir()
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT
                c.source_id,
                c.source_filename,
                c.source_type,
                COUNT(*) AS chunk_count,
                MIN(c.created_at) AS created_at
            FROM chunks c
            LEFT JOIN sources s ON c.source_id = s.source_id
            WHERE s.source_id IS NULL
            GROUP BY c.source_id
        """).fetchall()

        for row in rows:
            now = _now()
            sid = row["source_id"]
            sfname = row["source_filename"]
            stored_path = None
            c1 = uploads_dir / f"{sid}_{sfname}"
            c2 = uploads_dir / sid
            if c1.exists():
                stored_path = str(c1.relative_to(_REPO_ROOT)) if c1.is_relative_to(_REPO_ROOT) else str(c1)
            elif c2.exists():
                stored_path = str(c2.relative_to(_REPO_ROOT)) if c2.is_relative_to(_REPO_ROOT) else str(c2)

            conn.execute("""
                INSERT INTO sources
                    (source_id, filename, source_type, stored_path, status, stage, progress,
                     chunk_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'ready', 'Ready', 100, ?, ?, ?)
            """, (
                sid,
                sfname,
                row["source_type"],
                stored_path,
                row["chunk_count"],
                row["created_at"],
                now,
            ))
        if rows:
            conn.commit()
            logger.info("Migrated %d existing sources to sources table with status=ready", len(rows))


def _mark_interrupted_as_failed() -> None:
    """Mark any source left in queued/processing as failed on startup."""
    msg = "Processing was interrupted. Use Re-index to try again."
    with _get_connection() as conn:
        result = conn.execute("""
            UPDATE sources
            SET status='failed', error_message=?, updated_at=?
            WHERE status IN ('queued', 'processing')
        """, (msg, _now()))
        if result.rowcount:
            conn.commit()
            logger.warning("Marked %d interrupted source(s) as failed on startup", result.rowcount)


# ---------------------------------------------------------------------------
# Sources CRUD
# ---------------------------------------------------------------------------


def upsert_source(
    *,
    source_id: str,
    filename: str,
    source_type: str,
    stored_path: Optional[str] = None,
    status: str = "queued",
    stage: Optional[str] = None,
    progress: int = 0,
    error_message: Optional[str] = None,
    chunk_count: int = 0,
    suggested_questions: Optional[list] = None,
    file_hash: Optional[str] = None,
) -> None:
    """Insert or replace a source row."""
    now = _now()
    sq_json = json.dumps(suggested_questions) if suggested_questions is not None else None
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO sources
                (source_id, filename, source_type, stored_path, status, stage, progress,
                 error_message, chunk_count, suggested_questions, file_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                filename=excluded.filename,
                source_type=excluded.source_type,
                stored_path=COALESCE(excluded.stored_path, stored_path),
                status=excluded.status,
                stage=excluded.stage,
                progress=excluded.progress,
                error_message=excluded.error_message,
                chunk_count=excluded.chunk_count,
                suggested_questions=excluded.suggested_questions,
                file_hash=excluded.file_hash,
                updated_at=excluded.updated_at
        """, (
            source_id, filename, source_type, stored_path, status, stage, progress,
            error_message, chunk_count, sq_json, file_hash, now, now,
        ))
        conn.commit()


def update_source_status(
    source_id: str,
    *,
    status: str,
    stage: Optional[str] = None,
    progress: Optional[int] = None,
    error_message: Optional[str] = None,
    chunk_count: Optional[int] = None,
    suggested_questions: Optional[list] = None,
    clear_error: bool = False,
) -> None:
    """Patch source status fields without touching other columns.

    Pass ``clear_error=True`` to explicitly set error_message to NULL
    (e.g. when re-queuing a previously failed source).
    """
    now = _now()
    sets = ["status=?", "updated_at=?"]
    params: list = [status, now]

    if stage is not None:
        sets.append("stage=?")
        params.append(stage)
    if progress is not None:
        sets.append("progress=?")
        params.append(progress)
    if clear_error:
        sets.append("error_message=?")
        params.append(None)
    elif error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    if chunk_count is not None:
        sets.append("chunk_count=?")
        params.append(chunk_count)
    if suggested_questions is not None:
        sets.append("suggested_questions=?")
        params.append(json.dumps(suggested_questions))

    params.append(source_id)
    sql = f"UPDATE sources SET {', '.join(sets)} WHERE source_id=?"
    with _get_connection() as conn:
        conn.execute(sql, params)
        conn.commit()


def update_source_suggestions(source_id: str, suggestions: Optional[list]) -> None:
    """Update only the suggested_questions field."""
    sq_json = json.dumps(suggestions) if suggestions is not None else None
    with _get_connection() as conn:
        conn.execute(
            "UPDATE sources SET suggested_questions=?, updated_at=? WHERE source_id=?",
            (sq_json, _now(), source_id),
        )
        conn.commit()


def get_source(source_id: str) -> Optional[dict[str, Any]]:
    """Return a source row dict, or None if not found."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE source_id=?", (source_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("suggested_questions"):
        try:
            d["suggested_questions"] = json.loads(d["suggested_questions"])
        except Exception:
            d["suggested_questions"] = None
    return d


def delete_source(source_id: str) -> None:
    """Delete the sources row for source_id."""
    with _get_connection() as conn:
        conn.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
        conn.commit()


def list_all_sources() -> list[dict[str, Any]]:
    """Return all sources from the sources table, ordered by created_at DESC.

    Automatically migrates any chunks with missing sources rows first.
    Falls back to aggregating from chunks if the sources table is empty.
    """
    _migrate_chunks_to_sources()

    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY created_at DESC"
        ).fetchall()

    if rows:
        results = []
        for row in rows:
            d = dict(row)
            if d.get("suggested_questions"):
                try:
                    d["suggested_questions"] = json.loads(d["suggested_questions"])
                except Exception:
                    d["suggested_questions"] = None
            # Compatibility alias
            d["source_id"] = d["source_id"]
            d["source_filename"] = d["filename"]
            d["source_type"] = d["source_type"]
            results.append(d)
        logger.debug("list_all_sources returned %d sources from sources table", len(results))
        return results

    # Fallback: aggregate from chunks
    with _get_connection() as conn:
        chunk_rows = conn.execute("""
            SELECT
                source_id,
                source_filename,
                source_type,
                COUNT(*)        AS chunk_count,
                MIN(created_at) AS created_at
            FROM chunks
            GROUP BY source_id
            ORDER BY created_at DESC
        """).fetchall()

    result = [dict(r) for r in chunk_rows]
    logger.debug("list_all_sources returned %d sources from chunks table (fallback)", len(result))
    return result


def list_ready_sources() -> list[dict[str, Any]]:
    """Return only sources with status='ready'."""
    all_sources = list_all_sources()
    return [s for s in all_sources if s.get("status", "ready") == "ready"]


# ---------------------------------------------------------------------------
# Write — chunks
# ---------------------------------------------------------------------------


def insert_chunk(
    *,
    source_id: str,
    source_filename: str,
    source_type: str,
    chunk_type: str,
    page_number: Optional[int] = None,
    bbox: Optional[dict[str, Any]] = None,
    content_text: Optional[str] = None,
    content_image_path: Optional[str] = None,
) -> str:
    """Insert a single chunk row and return its generated id."""
    if content_text is None and content_image_path is None:
        raise ValueError(
            "At least one of content_text or content_image_path must be provided."
        )

    chunk_id = str(uuid.uuid4())
    created_at = _now()
    bbox_json = json.dumps(bbox) if bbox is not None else None

    sql = """
    INSERT INTO chunks
        (id, source_id, source_filename, source_type, page_number,
         bbox, chunk_type, content_text, content_image_path, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_connection() as conn:
        conn.execute(
            sql,
            (
                chunk_id,
                source_id,
                source_filename,
                source_type,
                page_number,
                bbox_json,
                chunk_type,
                content_text,
                content_image_path,
                created_at,
            ),
        )
        conn.commit()

    logger.debug(
        "Inserted chunk id=%s source_id=%s chunk_type=%s page=%s",
        chunk_id,
        source_id,
        chunk_type,
        page_number,
    )
    return chunk_id


def delete_chunks_by_source(source_id: str) -> int:
    """Delete all chunk rows for source_id. Returns number of rows deleted."""
    with _get_connection() as conn:
        result = conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.commit()
    logger.info("Deleted %d chunks for source_id=%s", result.rowcount, source_id)
    return result.rowcount


# ---------------------------------------------------------------------------
# Read — chunks
# ---------------------------------------------------------------------------


def _deserialise_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, deserialising bbox."""
    d = dict(row)
    if d.get("bbox"):
        try:
            d["bbox"] = json.loads(d["bbox"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def fetch_chunks_by_source(source_id: str) -> list[dict[str, Any]]:
    """Return all chunks belonging to source_id, ordered by page then time."""
    sql = """
    SELECT * FROM chunks
    WHERE source_id = ?
    ORDER BY page_number ASC, created_at ASC
    """
    with _get_connection() as conn:
        rows = conn.execute(sql, (source_id,)).fetchall()

    result = [_deserialise_row(r) for r in rows]
    logger.debug("Fetched %d chunks for source_id=%s", len(result), source_id)
    return result


def fetch_unembedded_chunks() -> list[dict[str, Any]]:
    """Return all chunks with embedded=0, ordered by created_at."""
    sql = """
    SELECT * FROM chunks
    WHERE embedded = 0
    ORDER BY created_at ASC
    """
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()

    result = [_deserialise_row(r) for r in rows]
    logger.debug("Found %d unembedded chunks", len(result))
    return result


def mark_chunk_embedded(chunk_id: str) -> None:
    """Set embedded=1 for the chunk with the given chunk_id."""
    sql = "UPDATE chunks SET embedded = 1 WHERE id = ?"
    with _get_connection() as conn:
        conn.execute(sql, (chunk_id,))
        conn.commit()
    logger.debug("Marked chunk %s as embedded", chunk_id)


def update_chunk_content_text(
    chunk_id: str, content_text: str, bbox: Optional[dict[str, Any]] = None
) -> None:
    """Update content_text and optionally bbox of a chunk."""
    if bbox is not None:
        sql = "UPDATE chunks SET content_text = ?, bbox = ?, embedded = 0 WHERE id = ?"
        params = (content_text, json.dumps(bbox), chunk_id)
    else:
        sql = "UPDATE chunks SET content_text = ?, embedded = 0 WHERE id = ?"
        params = (content_text, chunk_id)

    with _get_connection() as conn:
        conn.execute(sql, params)
        conn.commit()
    logger.debug("Updated chunk %s content_text (reset embedded=0)", chunk_id)
