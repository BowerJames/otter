"""Per-session persistence layer: append-only tree, projection, store, controller.

This subpackage adds a per-session persistence layer to ``otter-ai-core`` so a
single conversation can be **persisted**, **restorable**, **observable**,
**branchable**, **compactable**, and **updatable** (append-only item amendments
— the capability upstream ``pi`` does not have, made first-class here).

Scope is deliberately per-session (no multi-session catalog, no connection
reconciliation, no LLM-step hooks). See the issue spec.

Public surface
--------------
* :data:`SessionEntry` — the append-only tree's discriminated union
  (:mod:`otter_ai_core.session_manager.entries`).
* :class:`SessionMetadata` / :class:`SessionStats` / :class:`BranchSummaryInput`
  (:mod:`otter_ai_core.session_manager.metadata`).
* :class:`SessionError` / :class:`SessionErrorCode`
  (:mod:`otter_ai_core.session_manager.errors`).
* the pure projection functions
  (:mod:`otter_ai_core.session_manager.projection`).
* :class:`SessionStore` — the backend protocol
  (:mod:`otter_ai_core.session_manager.store`).
* :class:`SessionStoreController` — the concrete public surface + its
  :class:`~otter_ai_core.bus.Bus` notification descriptors
  (:mod:`otter_ai_core.session_manager.controller` / ``events``).

Scope is deliberately per-session (no multi-session catalog, no connection
reconciliation, no LLM-step hooks). See the issue spec.
"""

from otter_ai_core.session_manager.controller import SessionStoreController
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
    SessionEntryBase,
    SessionEntryType,
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
    SessionStoreControllerEventTypes,
    TreeChangedPayload,
)
from otter_ai_core.session_manager.metadata import (
    BranchSummaryInput,
    SessionMetadata,
    SessionStats,
)
from otter_ai_core.session_manager.projection import (
    SessionDerivedState,
    SessionProjection,
    apply_compaction_transform,
    apply_updates,
    derive_state,
    entries_to_items,
    project,
)
from otter_ai_core.session_manager.store import SessionStore

__all__ = [
    # entries
    "SessionEntryType",
    "SessionEntryBase",
    "MessageEntry",
    "MessageUpdateEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "ActiveToolsChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "LabelEntry",
    "SessionInfoEntry",
    "SessionEntry",
    # metadata
    "SessionMetadata",
    "BranchSummaryInput",
    "SessionStats",
    # errors
    "SessionError",
    "SessionErrorCode",
    # projection (pure functions)
    "SessionDerivedState",
    "SessionProjection",
    "apply_compaction_transform",
    "apply_updates",
    "derive_state",
    "entries_to_items",
    "project",
    # store protocol (backend seam)
    "SessionStore",
    # controller + observability
    "SessionStoreController",
    "SessionStoreControllerEventTypes",
    "TreeChangedPayload",
    "ENTRY_APPENDED",
    "ITEM_ADDED",
    "ITEM_UPDATED",
    "COMPACTED",
    "TREE_CHANGED",
]
