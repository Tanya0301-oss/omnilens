"""
app/utils/paths.py
------------------
Central path resolver for OmniLens.

Respects the ``OMNILENS_DATA_DIR`` environment variable for data directory
isolation (useful for test runs and temporary sandbox copies).
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    """Return the active data directory.

    If ``OMNILENS_DATA_DIR`` is set in the environment, returns that path.
    Otherwise defaults to ``<repo_root>/data``.
    """
    override = os.environ.get("OMNILENS_DATA_DIR")
    if override:
        p = Path(override).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _REPO_ROOT / "data"


def get_db_path() -> Path:
    """Return the path to omnilens.db."""
    return get_data_dir() / "omnilens.db"


def get_uploads_dir() -> Path:
    """Return the path to uploads/ directory, ensuring it exists."""
    p = get_data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_chroma_dir() -> Path:
    """Return the path to chroma_db/ directory, ensuring it exists."""
    p = get_data_dir() / "chroma_db"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_cache_root() -> Path:
    """Return the path to cache/ directory, ensuring it exists."""
    p = get_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p
