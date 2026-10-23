"""
app/utils/errors.py
-------------------
Friendly error definitions and mappings for OmniLens.

Maps internal and provider errors to a small set of structured, user-facing errors:
- rate_limited
- model_unavailable
- auth_error
- timeout
- no_sources
- empty_question
- internal_error

Never exposes raw provider error strings, stack traces, or technical JSON blobs to clients.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Standard friendly error dictionary
ERROR_DEFINITIONS: dict[str, dict[str, Any]] = {
    "rate_limited": {
        "message": "The AI service is busy right now. Please try again in a moment.",
        "retryable": True,
        "status_code": 429,
    },
    "model_unavailable": {
        "message": "The requested AI model is currently unavailable.",
        "retryable": True,
        "status_code": 503,
    },
    "auth_error": {
        "message": "The AI service is not configured correctly. Check the API key in .env.",
        "retryable": False,
        "status_code": 401,
    },
    "timeout": {
        "message": "The request timed out. Please try again.",
        "retryable": True,
        "status_code": 504,
    },
    "no_sources": {
        "message": "Upload a document first.",
        "retryable": False,
        "status_code": 400,
    },
    "empty_question": {
        "message": "Please enter a question.",
        "retryable": False,
        "status_code": 400,
    },
    "internal_error": {
        "message": "An unexpected error occurred. Please try again.",
        "retryable": True,
        "status_code": 500,
    },
}


class OmniLensError(Exception):
    """Structured, user-facing error."""

    def __init__(
        self,
        error_code: str,
        message: Optional[str] = None,
        retryable: Optional[bool] = None,
        status_code: Optional[int] = None,
        original_exc: Optional[Exception] = None,
    ):
        info = ERROR_DEFINITIONS.get(error_code, ERROR_DEFINITIONS["internal_error"])
        self.error_code = error_code
        self.message = message if message is not None else info["message"]
        self.retryable = retryable if retryable is not None else info["retryable"]
        self.status_code = status_code if status_code is not None else info["status_code"]
        self.original_exc = original_exc
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """User-safe dictionary shape."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
        }

    def to_response(self) -> JSONResponse:
        """Create a JSONResponse with the appropriate HTTP status code."""
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
        )


def map_exception_to_error(exc: Exception) -> OmniLensError:
    """Map any technical exception to an OmniLensError.

    Logs technical error details strictly server-side.
    """
    if isinstance(exc, OmniLensError):
        return exc

    # Log full technical exception details server-side
    logger.error("Mapping technical exception: %r", exc, exc_info=True)

    exc_str = str(exc).lower()
    exc_type = type(exc).__name__

    # 1. Groq / HTTP Status Error inspections
    status_code = getattr(exc, "status_code", None)
    if status_code is None and hasattr(exc, "response"):
        status_code = getattr(exc.response, "status_code", None)

    if status_code == 429 or "rate_limit" in exc_str or "429" in exc_str or "busy" in exc_str:
        return OmniLensError("rate_limited", original_exc=exc)

    if status_code == 401 or "invalid api key" in exc_str or "groq_api_key" in exc_str or "unauthorized" in exc_str:
        return OmniLensError("auth_error", original_exc=exc)

    if status_code in (400, 404) and ("model" in exc_str or "not found" in exc_str or "decommissioned" in exc_str):
        return OmniLensError("model_unavailable", original_exc=exc)

    if "timeout" in exc_type.lower() or "timeout" in exc_str or status_code in (408, 504):
        return OmniLensError("timeout", original_exc=exc)

    if isinstance(exc, ValueError) and "groq_api_key" in exc_str:
        return OmniLensError("auth_error", original_exc=exc)

    return OmniLensError("internal_error", original_exc=exc)
