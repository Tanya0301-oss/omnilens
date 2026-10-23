"""
app/utils/logging_config.py
---------------------------
Structured logging for OmniLens.

Each pipeline stage logs a message that includes the stage name and elapsed
time so it is easy to spot bottlenecks without a heavyweight observability
stack.  All modules should obtain their logger via `get_logger(__name__)`.

Usage example::

    from app.utils.logging_config import get_logger, log_stage
    import time

    logger = get_logger(__name__)

    t0 = time.perf_counter()
    # ... do work ...
    log_stage(logger, "PDF parsed", elapsed=time.perf_counter() - t0,
              pages=5, images=3)
"""

import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Generator

# ---------------------------------------------------------------------------
# Module-level setup — runs once when this module is first imported.
# ---------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _configure_root_logger() -> None:
    """Configure the root logger with a human-readable format to stdout."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g., by a previous import).
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_root_logger()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped to *name* (typically ``__name__``).

    Args:
        name: Logger namespace, usually the calling module's ``__name__``.

    Returns:
        A :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)


def log_stage(
    logger: logging.Logger,
    stage: str,
    elapsed: float,
    level: int = logging.INFO,
    **kwargs: Any,
) -> None:
    """Emit a structured log line for a completed pipeline stage.

    Args:
        logger:  The logger to write to.
        stage:   Human-readable stage name, e.g. ``"PDF parsed"``.
        elapsed: Wall-clock seconds consumed by the stage.
        level:   Python logging level (default ``INFO``).
        **kwargs: Additional key=value pairs appended to the message
                  (e.g. ``pages=5``, ``images=3``).

    Example output::

        2026-10-02T14:00:01 | INFO     | app.ingestion.pdf_parser |
        [STAGE] PDF parsed | elapsed=1.23s | pages=5 | images=3
    """
    extra_parts = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"[STAGE] {stage} | elapsed={elapsed:.3f}s"
    if extra_parts:
        msg += f" | {extra_parts}"
    logger.log(level, msg)


@contextmanager
def timed_stage(
    logger: logging.Logger,
    stage: str,
    level: int = logging.INFO,
    **kwargs: Any,
) -> Generator[None, None, None]:
    """Context manager that automatically times a block and calls :func:`log_stage`.

    Args:
        logger: Logger instance.
        stage:  Stage name to log.
        level:  Logging level.
        **kwargs: Extra key-value pairs forwarded to :func:`log_stage`.

    Example::

        with timed_stage(logger, "PDF parsed", pages=5):
            parse_pdf(path)
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log_stage(logger, stage, elapsed=time.perf_counter() - t0,
                  level=level, **kwargs)
