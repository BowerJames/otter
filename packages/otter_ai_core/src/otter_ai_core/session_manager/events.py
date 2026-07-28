from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from otter_ai_core.bus import BusEvent
from otter_ai_core.session_manager.entries import (
    BranchSummaryEntry,
    CompactionEntry,
    MessageEntry,
    MessageUpdateEntry,
    SessionEntry,
)


class SessionStoreControllerEventTypes(StrEnum):
    ENTRY_APPENDED = "session.entry_appended"
    ITEM_ADDED = "session.item_added"
    ITEM_UPDATED = "session.item_updated"  # §8 amendment
    COMPACTED = "session.compacted"
    TREE_CHANGED = "session.tree_changed"  # branch / leaf move


@dataclass(frozen=True, slots=True)
class TreeChangedPayload:
    new_leaf_id: str | None
    old_leaf_id: str | None
    summary_entry: BranchSummaryEntry | None


#: After ANY entry is appended (coarse catch-all: one subscriber can refresh
#: any cached view).
ENTRY_APPENDED: BusEvent[SessionEntry] = BusEvent(SessionStoreControllerEventTypes.ENTRY_APPENDED)
#: After a :class:`~otter_ai_core.session_manager.MessageEntry` (initial add).
ITEM_ADDED: BusEvent[MessageEntry] = BusEvent(SessionStoreControllerEventTypes.ITEM_ADDED)
#: After a :class:`~otter_ai_core.session_manager.MessageUpdateEntry` (append-only amendment).
ITEM_UPDATED: BusEvent[MessageUpdateEntry] = BusEvent(SessionStoreControllerEventTypes.ITEM_UPDATED)
#: After a :class:`~otter_ai_core.session_manager.CompactionEntry`.
COMPACTED: BusEvent[CompactionEntry] = BusEvent(SessionStoreControllerEventTypes.COMPACTED)
#: After a leaf move / branch (carries old/new leaf ids + any summary entry).
TREE_CHANGED: BusEvent[TreeChangedPayload] = BusEvent(SessionStoreControllerEventTypes.TREE_CHANGED)


__all__ = [
    "SessionStoreControllerEventTypes",
    "TreeChangedPayload",
    "ENTRY_APPENDED",
    "ITEM_ADDED",
    "ITEM_UPDATED",
    "COMPACTED",
    "TREE_CHANGED",
]
