from __future__ import annotations

from enum import StrEnum


class SessionErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    INVALID_SESSION = "invalid_session"
    INVALID_ENTRY = "invalid_entry"
    STORAGE = "storage"
    UNKNOWN = "unknown"


class SessionError(Exception):
    def __init__(self, code: SessionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


__all__ = [
    "SessionErrorCode",
    "SessionError",
]
