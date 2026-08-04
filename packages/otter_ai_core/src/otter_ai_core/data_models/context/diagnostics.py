from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DiagnosticErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    message: str
    stack: str | None = None
    code: str | int | None = None


class AssistantMessageDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    timestamp: int
    error: DiagnosticErrorInfo | None = None
    details: dict[str, Any] | None = None
