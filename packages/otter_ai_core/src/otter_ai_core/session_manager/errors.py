"""Stable, backend-agnostic error classification for session stores.

Swappable backends (memory / JSONL / SQLite / Postgres) raise
:class:`SessionError` with a :class:`SessionErrorCode` so a driver/UI can
distinguish "not found" from "storage failure" uniformly — the same instinct
behind otter's discriminated event families.

(:class:`SessionErrorCode.INVALID_ENTRY` covers a bad branch/label target.
There is intentionally no ``INVALID_FORK_TARGET`` — there is no fork without a
catalog, which is out of scope.)
"""

from __future__ import annotations

from enum import StrEnum


class SessionErrorCode(StrEnum):
    """A stable classification for a :class:`SessionError`."""

    NOT_FOUND = "not_found"
    INVALID_SESSION = "invalid_session"
    INVALID_ENTRY = "invalid_entry"
    STORAGE = "storage"
    UNKNOWN = "unknown"


class SessionError(Exception):
    """A classified session error raised by a store or the controller."""

    def __init__(self, code: SessionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


__all__ = [
    "SessionErrorCode",
    "SessionError",
]
