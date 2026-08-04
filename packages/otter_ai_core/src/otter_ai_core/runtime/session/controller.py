from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from types import NoneType, TracebackType
from typing import Any, Self

from otter_ai_core.data_models.context import Context, ContextItem, Usage, UserContent
from otter_ai_core.data_models.events.session_events import (
    COMPACTED,
    ENTRY_APPENDED,
    ITEM_ADDED,
    ITEM_UPDATED,
    TREE_CHANGED,
    TreeChangedPayload,
)
from otter_ai_core.data_models.provider import ThinkingLevel
from otter_ai_core.data_models.session.entries import (
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
    SessionEntryBase,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)
from otter_ai_core.data_models.session.errors import SessionError, SessionErrorCode
from otter_ai_core.data_models.session.metadata import BranchSummaryInput, SessionMetadata
from otter_ai_core.data_models.session.projection import SessionProjection
from otter_ai_core.interfaces.store import SessionStore
from otter_ai_core.runtime.bus import Bus
from otter_ai_core.runtime.session.projection import project

#: Collapse any run of CR/LF to a single space, then trim (pi's appendSessionName).
_NAME_SANITIZER = re.compile(r"[\r\n]+")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_name(name: str) -> str:
    return _NAME_SANITIZER.sub(" ", name).strip()


#: Maps each session-store event name to the concrete payload class every
#: emitted event must be an instance of. Registered on the controller's Bus at
#: construction. SessionEntryBase stands in for ENTRY_APPENDED because the
#: SessionEntry union is an Annotated form that cannot be used with isinstance.
_SESSION_EVENT_TRIGGER_TYPES: dict[str, type[object]] = {
    ENTRY_APPENDED: SessionEntryBase,
    ITEM_ADDED: MessageEntry,
    ITEM_UPDATED: MessageUpdateEntry,
    COMPACTED: CompactionEntry,
    TREE_CHANGED: TreeChangedPayload,
}


class SessionStoreController[TMetadata: SessionMetadata]:
    __slots__ = ("_store", "_bus", "_lock")

    def __init__(self, store: SessionStore[TMetadata]) -> None:
        self._store = store
        self._bus: Bus = Bus()
        for name, trigger_type in _SESSION_EVENT_TRIGGER_TYPES.items():
            self._bus.register(name, trigger_type, NoneType)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Surfaces
    # ------------------------------------------------------------------ #

    @property
    def store(self) -> SessionStore[TMetadata]:
        return self._store

    @property
    def bus(self) -> Bus:
        return self._bus

    def on(self, type: str, handler: Callable[..., object]) -> Callable[[], None]:
        return self._bus.on(type, handler)

    # ------------------------------------------------------------------ #
    # Reads (lock-free snapshots)
    # ------------------------------------------------------------------ #

    async def metadata(self) -> TMetadata:
        return await self._store.metadata()

    async def leaf_id(self) -> str | None:
        return await self._store.leaf_id()

    async def get_branch(self, *, from_id: str | None = None) -> list[SessionEntry]:
        leaf = from_id if from_id is not None else await self._store.leaf_id()
        return await self._store.path_to_root_or_compaction(leaf)

    async def projection(self) -> SessionProjection:
        path = await self._store.path_to_root_or_compaction(await self._store.leaf_id())
        return project(path)

    async def build_context(self) -> Context:
        return (await self.projection()).context

    # ------------------------------------------------------------------ #
    # Writes (serialized; return the new TREE entry id)
    # ------------------------------------------------------------------ #

    async def _publish(self, entry: SessionEntry) -> None:
        await self._bus.emit(ENTRY_APPENDED, entry)
        match entry:
            case MessageEntry():
                await self._bus.emit(ITEM_ADDED, entry)
            case MessageUpdateEntry():
                await self._bus.emit(ITEM_UPDATED, entry)
            case CompactionEntry():
                await self._bus.emit(COMPACTED, entry)

    async def _new_identity(self) -> tuple[str, str | None, str]:
        return (
            await self._store.create_entry_id(),
            await self._store.leaf_id(),
            _now_iso(),
        )

    async def _commit(self, entry: SessionEntry) -> str:
        await self._store.append_entry(entry)
        await self._publish(entry)
        return entry.id

    async def append_message(self, item: ContextItem) -> str:
        async with self._lock:
            id_, parent_id, ts = await self._new_identity()
            return await self._commit(
                MessageEntry(id=id_, parent_id=parent_id, timestamp=ts, item=item)
            )

    async def update_message(self, item: ContextItem) -> str:
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
                await self._publish(summary_entry)
            await self._bus.emit(
                TREE_CHANGED,
                TreeChangedPayload(
                    new_leaf_id=entry_id, old_leaf_id=old, summary_entry=summary_entry
                ),
            )
            return summary_entry.id if summary_entry is not None else None

    # ------------------------------------------------------------------ #
    # Teardown (owned Bus worker)
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> Self:
        await self._bus.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._bus.end()
        await self._bus.__aexit__(exc_type, exc, tb)


__all__ = ["SessionStoreController"]
