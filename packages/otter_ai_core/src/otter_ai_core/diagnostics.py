"""Redacted diagnostic records attached to assistant messages on failure/recovery."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DiagnosticErrorInfo(BaseModel):
    """Structured view of a thrown error captured in a diagnostic record."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    message: str
    stack: str | None = None
    code: str | int | None = None


class AssistantMessageDiagnostic(BaseModel):
    """A single diagnostic event recorded on an assistant message.

    Diagnostics capture provider/runtime failures and recoveries (e.g. a retry
    after a transient error) without affecting the message content itself.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    timestamp: int
    error: DiagnosticErrorInfo | None = None
    details: dict[str, Any] | None = None
