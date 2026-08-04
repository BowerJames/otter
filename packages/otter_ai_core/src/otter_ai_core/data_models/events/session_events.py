from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from otter_ai_core.data_models.session.entries import BranchSummaryEntry


class SessionStoreControllerEventTypes(StrEnum):
    ENTRY_APPENDED = "session.entry_appended"
    ITEM_ADDED = "session.item_added"
    ITEM_UPDATED = "session.item_updated"  # §8 amendment
    COMPACTED = "session.compacted"
    TREE_CHANGED = "session.tree_changed"  # branch / leaf move


class TreeChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_leaf_id: str | None
    old_leaf_id: str | None
    summary_entry: BranchSummaryEntry | None


# String event names the session store's Bus is keyed on. They alias the
# canonical SessionStoreControllerEventTypes members (the single source of
# truth) so subscribers can refer to a stable name without the enum.
ENTRY_APPENDED: SessionStoreControllerEventTypes = SessionStoreControllerEventTypes.ENTRY_APPENDED
ITEM_ADDED: SessionStoreControllerEventTypes = SessionStoreControllerEventTypes.ITEM_ADDED
ITEM_UPDATED: SessionStoreControllerEventTypes = SessionStoreControllerEventTypes.ITEM_UPDATED
COMPACTED: SessionStoreControllerEventTypes = SessionStoreControllerEventTypes.COMPACTED
TREE_CHANGED: SessionStoreControllerEventTypes = SessionStoreControllerEventTypes.TREE_CHANGED


__all__ = [
    "SessionStoreControllerEventTypes",
    "TreeChangedPayload",
    "ENTRY_APPENDED",
    "ITEM_ADDED",
    "ITEM_UPDATED",
    "COMPACTED",
    "TREE_CHANGED",
]
