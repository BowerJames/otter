from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context import Usage


class SessionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    #: ISO-8601 UTC.
    created_at: str


class BranchSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    details: Any | None = None
    usage: Usage | None = None
    from_hook: bool = False


class SessionStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_count: int  # MessageEntry count only (updates do not inflate it)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cost_total: float


__all__ = [
    "SessionMetadata",
    "BranchSummaryInput",
    "SessionStats",
]
