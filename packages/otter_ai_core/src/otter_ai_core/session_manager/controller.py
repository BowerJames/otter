"""The concrete public surface of a persisted session.

:class:`SessionStoreController` wraps a
:class:`~otter_ai_core.session_manager.SessionStore` (``pi``'s ``Session``):
append / **update** / project / branch / compact. It is **pure logic over a
store** — it owns no LLM, no intercept hooks, and no connection knowledge.
Generating a compaction summary or a branch summary is the agent layer's job;
this controller records *caller-supplied* results.

Lifecycle
---------
Constructed over a populated or empty
:class:`~otter_ai_core.session_manager.SessionStore` (construction +
``projection()`` IS restore — §14 of the issue spec). Because it owns a
notification :class:`~otter_ai_core.bus.Bus` (which owns a worker task), the
constructor must run inside a running :mod:`asyncio` loop; tear the bus down
with :meth:`aclose` (or ``async with``).

Concurrency
-----------
Single-writer appends/updates/moves, enforced **inside the controller** via an
:class:`asyncio.Lock` (§13): the entry id + parent leaf are read and the entry
appended atomically under the lock, so two racing appends cannot both parent on
a stale leaf. Reads are **lock-free snapshots**: the tree is append-only and a
path read returns a consistent list, so ``get_branch`` / ``build_context`` /
``projection`` never block a writer.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from otter_ai_core.bus import Bus, BusEvent, BusHandler
from otter_ai_core.context import Context, ContextItem, Usage, UserContent
from otter_ai_core.provider_api_model_options import ThinkingLevel
from otter_ai_core.session_manager.entries import (
    ActiveToolsChangeEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    MessageEntry,
    MessageUpdateEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)
from otter_ai_core.session_manager.errors import SessionError, SessionErrorCode
from otter_ai_core.session_manager.events import (
    COMPACTED,
    ENTRY_APPENDED,
    ITEM_ADDED,
    ITEM_UPDATED,
    TREE_CHANGED,
    TreeChangedPayload,
)
from otter_ai_core.session_manager.metadata import BranchSummaryInput, SessionMetadata
from otter_ai_core.session_manager.projection import SessionProjection, project
from otter_ai_core.session_manager.store import SessionStore

#: Default graceful-drain deadline (seconds) for :meth:`SessionStoreController.aclose`.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0

#: Collapse any run of CR/LF to a single space, then trim (pi's appendSessionName).
_NAME_SANITIZER = re.compile(r"[\r\n]+")


def _now_iso() -> str:
    """ISO-8601 UTC (the entry ``timestamp`` convention)."""
    return datetime.now(UTC).isoformat()


def _sanitize_name(name: str) -> str:
    return _NAME_SANITIZER.sub(" ", name).strip()


class SessionStoreController[TMetadata: SessionMetadata]:
    """An open persisted session: append / update / project / branch / compact.

    Pure logic over a :class:`SessionStore`; observable via its :attr:`bus`;
    concurrency-safe via its append lock. The controller has NO concept of busy
    and NO LLM-step hooks.
    """

    __slots__ = ("_store", "_bus", "_lock")

    def __init__(self, store: SessionStore[TMetadata]) -> None:
        self._store = store
        self._bus: Bus = Bus()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Surfaces
    # ------------------------------------------------------------------ #

    @property
    def store(self) -> SessionStore[TMetadata]:
        """The backing :class:`SessionStore` (raw access for advanced consumers)."""
        return self._store

    @property
    def bus(self) -> Bus:
        """The descriptor-keyed pub/sub bus every change is published to."""
        return self._bus

    def on[TPayload](
        self, event: BusEvent[TPayload], handler: BusHandler[TPayload]
    ) -> Callable[[], None]:
        """Subscribe ``handler`` to ``event``; return an idempotent unsubscribe callable."""
        return self._bus.subscribe(event, handler)

    # ------------------------------------------------------------------ #
    # Reads (lock-free snapshots)
    # ------------------------------------------------------------------ #

    async def metadata(self) -> TMetadata:
        return await self._store.metadata()

    async def leaf_id(self) -> str | None:
        """The current leaf entry id (the live branch head), or ``None`` at the root."""
        return await self._store.leaf_id()

    async def get_branch(self, *, from_id: str | None = None) -> list[SessionEntry]:
        """The leaf->root path (root->leaf order), optionally from a given entry id."""
        leaf = from_id if from_id is not None else await self._store.leaf_id()
        return await self._store.path_to_root_or_compaction(leaf)

    async def projection(self) -> SessionProjection:
        """The current projected :class:`SessionProjection` (items-only context + state)."""
        path = await self._store.path_to_root_or_compaction(await self._store.leaf_id())
        return project(path)

    async def build_context(self) -> Context:
        """The current projected :class:`Context` (items only; system_prompt/tools=None)."""
        return (await self.projection()).context

    # ------------------------------------------------------------------ #
    # Writes (serialized; return the new TREE entry id)
    # ------------------------------------------------------------------ #

    def _publish(self, entry: SessionEntry) -> None:
        """Publish the coarse ``ENTRY_APPENDED`` plus the matching refined event."""
        self._bus.publish(ENTRY_APPENDED, entry)
        match entry:
            case MessageEntry():
                self._bus.publish(ITEM_ADDED, entry)
            case MessageUpdateEntry():
                self._bus.publish(ITEM_UPDATED, entry)
            case CompactionEntry():
                self._bus.publish(COMPACTED, entry)

    async def _new_identity(self) -> tuple[str, str | None, str]:
        """A fresh ``(id, parent_id, timestamp)`` triple. Caller MUST hold the lock."""
        return (
            await self._store.create_entry_id(),
            await self._store.leaf_id(),
            _now_iso(),
        )

    async def _commit(self, entry: SessionEntry) -> str:
        """Append ``entry`` (advancing the leaf), publish, and return its id.

        Caller MUST hold :attr:`_lock` and have built ``entry`` with
        :meth:`_new_identity` under that lock.
        """
        await self._store.append_entry(entry)
        self._publish(entry)
        return entry.id

    async def append_message(self, item: ContextItem) -> str:
        """Record a conversation item (initial add). Returns the new tree id."""
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                MessageEntry(id=id_, parent_id=parent_id, timestamp=ts, item=item)
            )

    async def update_message(self, item: ContextItem) -> str:
        """Append-only amendment of a previously-recorded item (§8).

        Builds a :class:`MessageUpdateEntry` with ``target_item_id = item.id``.
        An orphan revision (one whose target is not on the path) is harmless:
        it stands as a standalone item at its own position. Returns the new tree
        id.
        """
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                MessageUpdateEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, item=item, target_item_id=item.id
                )
            )

    async def append_model_change(self, provider: str, model: str) -> str:
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                ModelChangeEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, provider=provider, model=model
                )
            )

    async def append_thinking_level_change(self, level: ThinkingLevel) -> str:
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                ThinkingLevelChangeEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, thinking_level=level
                )
            )

    async def append_active_tools_change(self, names: list[str]) -> str:
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                ActiveToolsChangeEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, active_tool_names=names
                )
            )

    async def append_compaction(
        self,
        *,
        summary: str,
        first_kept_entry_id: str | None,
        tokens_before: int,
        retained_tail: list[ContextItem] | None = None,
        details: Any | None = None,
        usage: Usage | None = None,
        from_hook: bool = False,
    ) -> str:
        """Record a caller-supplied compaction. Returns the new tree id."""
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                CompactionEntry(
                    id=id_,
                    parent_id=parent_id,
                    timestamp=ts,
                    summary=summary,
                    first_kept_entry_id=first_kept_entry_id,
                    tokens_before=tokens_before,
                    retained_tail=retained_tail,
                    details=details,
                    usage=usage,
                    from_hook=from_hook,
                )
            )

    async def append_custom(self, custom_type: str, data: Any | None = None) -> str:
        """Record non-projected extension state. Returns the new tree id."""
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                CustomEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, custom_type=custom_type, data=data
                )
            )

    async def append_custom_message(
        self,
        custom_type: str,
        content: str | list[UserContent],
        *,
        display: bool,
        details: Any | None = None,
    ) -> str:
        """Record extension-injected content projected as a user message.

        Returns the new tree id.
        """
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                CustomMessageEntry(
                    id=id_,
                    parent_id=parent_id,
                    timestamp=ts,
                    custom_type=custom_type,
                    content=content,
                    details=details,
                    display=display,
                )
            )

    async def append_label(self, target_id: str, label: str | None) -> str:
        """Label (or clear, with ``label=None``) an existing entry. Returns the new tree id.

        Raises :class:`SessionError` (:attr:`~SessionErrorCode.INVALID_ENTRY`)
        if ``target_id`` does not exist.
        """
        async with self._lock:
            if await self._store.get_entry(target_id) is None:
                raise SessionError(
                    SessionErrorCode.INVALID_ENTRY, f"label target {target_id!r} not found"
                )
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                LabelEntry(
                    id=id_, parent_id=parent_id, timestamp=ts, target_id=target_id, label=label
                )
            )

    async def append_session_name(self, name: str) -> str:
        """Record the session display name; sanitize first (CR/LF collapsed, trimmed).

        Returns the tree id.
        """
        sanitized = _sanitize_name(name)
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                SessionInfoEntry(id=id_, parent_id=parent_id, timestamp=ts, name=sanitized)
            )

    # ------------------------------------------------------------------ #
    # Branching (serialized): move the leaf, optionally record a summary
    # ------------------------------------------------------------------ #

    async def move_to(
        self,
        entry_id: str | None,
        *,
        summary: BranchSummaryInput | None = None,
    ) -> str | None:
        """Move the leaf to ``entry_id`` (``None`` == root), optionally recording a summary.

        After the move, new appends diverge (history is never mutated). If
        ``summary`` is given, a :class:`BranchSummaryEntry` (``from_id =
        entry_id``) is appended at the branch point and its id is returned;
        otherwise ``None``.

        Raises :class:`SessionError` (:attr:`~SessionErrorCode.INVALID_ENTRY`)
        if ``entry_id`` is not ``None`` and does not exist.
        """
        async with self._lock:
            if entry_id is not None and await self._store.get_entry(entry_id) is None:
                raise SessionError(
                    SessionErrorCode.INVALID_ENTRY, f"branch target {entry_id!r} not found"
                )
            old = await self._store.leaf_id()
            await self._store.set_leaf_id(entry_id)
            summary_entry: BranchSummaryEntry | None = None
            if summary is not None:
                id_, _parent_id, ts = await self._new_identity()
                summary_entry = BranchSummaryEntry(
                    id=id_,
                    parent_id=entry_id,
                    timestamp=ts,
                    from_id=entry_id,
                    summary=summary.summary,
                    details=summary.details,
                    usage=summary.usage,
                    from_hook=summary.from_hook,
                )
                await self._store.append_entry(summary_entry)
                self._publish(summary_entry)
            self._bus.publish(
                TREE_CHANGED,
                TreeChangedPayload(
                    new_leaf_id=entry_id, old_leaf_id=old, summary_entry=summary_entry
                ),
            )
            return summary_entry.id if summary_entry is not None else None

    # ------------------------------------------------------------------ #
    # Teardown (owned Bus worker)
    # ------------------------------------------------------------------ #

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        """Tear down the owned :class:`Bus` (reap the worker under ``timeout``)."""
        await self._bus.aclose(timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


__all__ = ["SessionStoreController"]
