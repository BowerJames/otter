from __future__ import annotations

from typing import Protocol

from otter_ai_core.data_models.session.entries import (
    SessionEntry,
    SessionEntryType,
)
from otter_ai_core.data_models.session.metadata import SessionMetadata, SessionStats


class SessionStore[TMetadata: SessionMetadata](Protocol):
    async def metadata(self) -> TMetadata: ...

    async def leaf_id(self) -> str | None: ...

    async def set_leaf_id(self, leaf_id: str | None) -> None: ...

    async def create_entry_id(self) -> str: ...

    async def append_entry(self, entry: SessionEntry) -> None: ...

    async def get_entry(self, id: str) -> SessionEntry | None: ...

    async def find_entries(self, type: SessionEntryType) -> list[SessionEntry]: ...

    async def path_to_root_or_compaction(self, leaf_id: str | None) -> list[SessionEntry]: ...

    async def entries(
        self, *, after_seq: int | None = None, limit: int | None = None
    ) -> list[SessionEntry]: ...

    async def label(self, target_id: str) -> str | None: ...

    async def session_name(self) -> str | None: ...

    async def stats(self) -> SessionStats: ...


__all__ = [
    "SessionStore",
]
