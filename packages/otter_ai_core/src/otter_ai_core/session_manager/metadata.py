"""Supporting types for a persisted session.

* :class:`SessionMetadata` — the generic per-session metadata; concrete backends
  extend it (cf. ``pi``'s ``JsonlSessionMetadata``).
* :class:`SessionStats` — aggregate session statistics (token/cost totals +
  message count), computed by the store.
* :class:`BranchSummaryInput` — the caller-supplied summary + accounting recorded
  by :meth:`~otter_ai_core.session_manager.SessionStoreController.move_to`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context import Usage


class SessionMetadata(BaseModel):
    """Generic per-session metadata; concrete backends extend this."""

    model_config = ConfigDict(extra="forbid")

    id: str
    #: ISO-8601 UTC.
    created_at: str


class BranchSummaryInput(BaseModel):
    """A caller-supplied branch summary recorded at a branch point by ``move_to``."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    details: Any | None = None
    usage: Usage | None = None
    from_hook: bool = False


class SessionStats(BaseModel):
    """Aggregate session statistics.

    Field names are aligned with otter's :class:`~otter_ai_core.context.Usage`
    (``input``/``output``/``cache_read``/``cache_write``/``total_tokens`` +
    ``cost.total``), not ``pi``'s "cached/uncached" bucket. The store computes
    these by iterating every entry in append order (see the issue spec §12).
    """

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
