"""The backend seam: a per-session persistence :class:`SessionStore` protocol.

:class:`SessionStore` is the swappable per-session backend
(``pi``'s ``SessionStorage<TMetadata>``) that concrete stores implement:
memory (tests), JSONL, SQLite, Postgres, …. It is the **first generic
:class:`typing.Protocol` in ``otter-ai-core``** (see the issue spec §4
"Repo-fit"): a backend seam needs both structural typing (the stores are
unrelated classes) *and* a metadata type parameter, which a ``type`` alias
cannot express and which concretizing would duplicate. PEP 695 generic
protocols (``class SessionStore[TMetadata: SessionMetadata](Protocol)``)
satisfy both on Python >= 3.12 (the repo floor).

It knows nothing about connections, catalogs, events, or the LLM.

Concurrency / atomicity
-----------------------
A normal append extends the current branch, so ``append_entry`` MUST
atomically (a) validate the parent exists, (b) append the entry, and (c)
advance the leaf to it; ``set_leaf_id`` MUST atomically validate-then-move.
The concrete controller further serializes appends through a lock (§13), but
the store's own atomicity is the last-line guarantee that two racing appends
cannot both parent on a stale leaf and silently corrupt the tree.
"""

from __future__ import annotations

from typing import Protocol

from otter_ai_core.session_manager.entries import (
    SessionEntry,
    SessionEntryType,
)
from otter_ai_core.session_manager.metadata import SessionMetadata, SessionStats


class SessionStore[TMetadata: SessionMetadata](Protocol):
    """Persistence backend for ONE session.

    Implementations: memory (tests), JSONL, SQLite, Postgres, …
    """

    async def metadata(self) -> TMetadata:
        """The session metadata."""
        ...

    async def leaf_id(self) -> str | None:
        """The current leaf entry id (the live branch head), or ``None`` at the root."""
        ...

    async def set_leaf_id(self, leaf_id: str | None) -> None:
        """Move the leaf (a branch move). ``None`` branches to the root."""
        ...

    async def create_entry_id(self) -> str:
        """Produce a fresh, session-unique opaque tree entry id."""
        ...

    async def append_entry(self, entry: SessionEntry) -> None:
        """Append ``entry`` (parented on the current leaf) and advance the leaf to it."""
        ...

    async def get_entry(self, id: str) -> SessionEntry | None:
        """Fetch a single entry by tree id, or ``None`` if absent."""
        ...

    async def find_entries(self, type: SessionEntryType) -> list[SessionEntry]:
        """All entries of a given ``type`` (in append order).

        Returns the broad union (the spec's erased fallback). Callers narrow a
        variant with ``isinstance``: per-literal overloads were explored but
        conflict with ``mypy --strict``'s overload-implementation variance
        check on ``list[T]`` returns, so the erased signature is shipped
        (spec §9 shows it in the protocol body; §16 lists it as the fallback).
        """
        ...

    async def path_to_root_or_compaction(self, leaf_id: str | None) -> list[SessionEntry]:
        """The leaf->root path, stopping at the latest compaction.

        Returned in **append/root->leaf order** (index 0 = oldest/nearest root
        or compaction; last = leaf). Stops at the latest compaction with a
        ``retained_tail`` or whose ``first_kept_entry_id`` is reached (pi's rule).
        """
        ...

    async def entries(
        self, *, after_seq: int | None = None, limit: int | None = None
    ) -> list[SessionEntry]:
        """A cursor over entries in APPEND ORDER.

        ``seq`` is a store-internal monotonic cursor (append order — e.g. JSONL
        line number / row id), NOT a field on :data:`SessionEntry`. Returns
        entries appended AFTER the given ``seq``.
        """
        ...

    async def label(self, target_id: str) -> str | None:
        """The latest label for ``target_id``, or ``None`` (None/empty clears)."""
        ...

    async def session_name(self) -> str | None:
        """The latest recorded session name, or ``None``."""
        ...

    async def stats(self) -> SessionStats:
        """Aggregate session statistics (token/cost/message totals — see §12)."""
        ...


__all__ = [
    "SessionStore",
]
