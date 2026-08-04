"""Test infrastructure: an in-memory :class:`SessionStore` implementation.

Not shipped in the package — the issue spec scopes out a concrete backend. The
pure projection is tested directly over hand-built entry lists
(``test_projection.py``); the controller and store-contract tests stand up a
real store via this class. It implements every protocol method, including the
``stats()`` aggregation rule (issue spec §12).
"""

from __future__ import annotations

from collections.abc import Iterator

from otter_ai_core.data_models.context import AssistantMessage, Usage
from otter_ai_core.data_models.session import (
    BranchSummaryEntry,
    CompactionEntry,
    LabelEntry,
    MessageEntry,
    SessionEntry,
    SessionEntryType,
    SessionError,
    SessionErrorCode,
    SessionInfoEntry,
    SessionMetadata,
    SessionStats,
)


class _MemorySessionStore[TMetadata: SessionMetadata]:
    """An in-memory, insertion-ordered :class:`SessionStore` for tests."""

    def __init__(self, metadata: TMetadata) -> None:
        self._metadata = metadata
        self._entries: dict[str, SessionEntry] = {}  # insertion-ordered
        self._seq: dict[str, int] = {}
        self._seq_counter = 0
        self._leaf_id: str | None = None

    # ----- identity / leaf -----
    async def metadata(self) -> TMetadata:
        return self._metadata

    async def leaf_id(self) -> str | None:
        return self._leaf_id

    async def set_leaf_id(self, leaf_id: str | None) -> None:
        if leaf_id is not None and leaf_id not in self._entries:
            raise SessionError(SessionErrorCode.INVALID_ENTRY, f"entry {leaf_id!r} not found")
        self._leaf_id = leaf_id

    async def create_entry_id(self) -> str:
        self._seq_counter += 1  # borrow the counter for unique ids too
        return f"e{self._seq_counter}"

    async def append_entry(self, entry: SessionEntry) -> None:
        if entry.parent_id is not None and entry.parent_id not in self._entries:
            raise SessionError(
                SessionErrorCode.INVALID_ENTRY, f"parent {entry.parent_id!r} not found"
            )
        if entry.id in self._entries:
            raise SessionError(SessionErrorCode.INVALID_ENTRY, f"entry {entry.id!r} already exists")
        self._seq_counter += 1
        self._entries[entry.id] = entry
        self._seq[entry.id] = self._seq_counter
        self._leaf_id = entry.id

    async def get_entry(self, id: str) -> SessionEntry | None:
        return self._entries.get(id)

    # ----- find_entries (erased; see store.py docstring) -----
    async def find_entries(self, type: SessionEntryType) -> list[SessionEntry]:
        return [entry for entry in self._entries.values() if entry.type == type]

    # ----- path / cursor -----
    async def path_to_root_or_compaction(self, leaf_id: str | None) -> list[SessionEntry]:
        if leaf_id is None:
            return []
        chain: list[SessionEntry] = []
        stop_at: str | None = None
        seen: set[str] = set()
        cur: str | None = leaf_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            entry = self._entries.get(cur)
            if entry is None:
                break
            chain.append(entry)
            if isinstance(entry, CompactionEntry):
                if entry.retained_tail is not None:
                    break  # retained items are carried by the compaction
                if entry.first_kept_entry_id is not None:
                    stop_at = entry.first_kept_entry_id
            if stop_at is not None and cur == stop_at:
                break
            cur = entry.parent_id
        chain.reverse()
        return chain

    async def entries(
        self, *, after_seq: int | None = None, limit: int | None = None
    ) -> list[SessionEntry]:
        ordered = sorted(self._entries.values(), key=lambda e: self._seq[e.id])
        if after_seq is not None:
            ordered = [e for e in ordered if self._seq[e.id] > after_seq]
        if limit is not None:
            ordered = ordered[:limit]
        return ordered

    # ----- labels / name -----
    async def label(self, target_id: str) -> str | None:
        latest: str | None = None
        for entry in self._entries.values():
            if isinstance(entry, LabelEntry) and entry.target_id == target_id:
                latest = entry.label
        return latest

    async def session_name(self) -> str | None:
        latest: str | None = None
        for entry in self._entries.values():
            if isinstance(entry, SessionInfoEntry):
                latest = entry.name
        return latest

    # ----- stats -----
    async def stats(self) -> SessionStats:
        message_count = 0
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_write_tokens = 0
        total_tokens = 0
        cost_total = 0.0
        for entry in self._entries.values():
            if isinstance(entry, MessageEntry):
                message_count += 1
            usage = _entry_usage(entry)
            if usage is not None:
                input_tokens += usage.input
                output_tokens += usage.output
                cache_read_tokens += usage.cache_read
                cache_write_tokens += usage.cache_write
                total_tokens += usage.total_tokens
                cost_total += usage.cost.total
        return SessionStats(
            message_count=message_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            total_tokens=total_tokens,
            cost_total=cost_total,
        )

    def __iter__(self) -> Iterator[tuple[SessionEntry, int]]:
        for entry in sorted(self._entries.values(), key=lambda e: self._seq[e.id]):
            yield entry, self._seq[entry.id]


def _entry_usage(entry: SessionEntry) -> Usage | None:
    """The :class:`~otter_ai_core.data_models.context.Usage` an entry contributes, if any.

    ``None`` when the entry carries no usage. A :class:`MessageUpdateEntry` is
    excluded (an amendment is not a new generation).
    """
    if isinstance(entry, MessageEntry) and isinstance(entry.item.message, AssistantMessage):
        return entry.item.message.usage
    if isinstance(entry, CompactionEntry):
        return entry.usage
    if isinstance(entry, BranchSummaryEntry):
        return entry.usage
    return None
