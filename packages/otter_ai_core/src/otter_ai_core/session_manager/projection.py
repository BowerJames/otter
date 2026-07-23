"""Pure projection of the append-only entry tree onto an otter :class:`Context`.

A set of **pure, sync, module-level functions** over a
:class:`collections.abc.Sequence` of :data:`~otter_ai_core.session_manager.SessionEntry`
(the leaf→root path the store returns, in **append/root→leaf order**). They take
no ``system_prompt`` and resolve no tools: :func:`project` returns a
:class:`SessionProjection` whose :class:`Context` carries items only
(``system_prompt=None``, ``tools=None``) — layering a system prompt and tools is
the future agent session's job (as ``pi`` does in ``createTurnState``).

These functions are loop-/async-/teardown-free and are the lightweight read path
for tests, exporters, and one-shot reads that need no live controller at all (a
projection can be rebuilt from a raw entry list with no store and no
controller).

Marker convention
------------------
otter's :data:`~otter_ai_core.context.Message` union is closed
(``User | Assistant | ToolResult``) with no ``compactionSummary`` /
``branchSummary`` role (unlike ``pi``'s extensible ``AgentMessage``). So the
synthesized compaction/branch messages are flattened to **user-role** messages
with a ``[compaction-summary]`` / ``[branch-summary:…]`` text marker. The
projection owns this marker text (single-place edit).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from otter_ai_core.context import (
    AssistantMessage,
    Context,
    ContextItem,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.context.role import Role
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


@dataclass(frozen=True, slots=True)
class SessionDerivedState:
    """Settings derived from the latest matching change entry on the path.

    ``model`` is ``(provider, model)`` or ``None`` if underivable (no
    :class:`ModelChangeEntry` and no assistant message provenance on the path).
    """

    model: tuple[str, str] | None
    thinking_level: ThinkingLevel | None
    active_tool_names: list[str] | None


@dataclass(frozen=True, slots=True)
class SessionProjection:
    """The result of projecting a session.

    :attr:`context` carries items only (``system_prompt=None``, ``tools=None``);
    :attr:`state` carries the latest derived settings.
    """

    context: Context
    state: SessionDerivedState


#: Prefix of the synthesized compaction-summary user message.
_COMPACTION_SUMMARY_PREFIX = "[compaction-summary]\n\n"
#: Marker wrapping a synthesized branch-summary user message.
_BRANCH_SUMMARY_PREFIX = "[branch-summary:]\n"
_BRANCH_SUMMARY_SUFFIX = "]"


def _to_ms(iso: str) -> int:
    """Convert an ISO-8601 UTC entry ``timestamp`` to int milliseconds.

    otter's :class:`~otter_ai_core.context.UserMessage` ``timestamp`` is int ms;
    cf. ``pi``'s ``new Date(ts).getTime()``.
    """
    from datetime import datetime

    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _latest_compaction_index(path: Sequence[SessionEntry]) -> int | None:
    for i in range(len(path) - 1, -1, -1):
        if isinstance(path[i], CompactionEntry):
            return i
    return None


def apply_compaction_transform(path: Sequence[SessionEntry]) -> list[SessionEntry]:
    """Return the post-compaction entry view of ``path`` (``pi``'s transform).

    If no :class:`CompactionEntry` is on the path, return the path unchanged.
    If one is, return the live view as a list of *entries* (the union is over
    entries, so the compaction's ``retained_tail`` — a list of
    :class:`~otter_ai_core.context.ContextItem` — is NOT spliced in here; it is
    materialized later by :func:`entries_to_items`):

    * ``retained_tail`` set — ``[compaction] + post-compaction entries``. The
      retained items are carried by the compaction entry and expanded in
      :func:`entries_to_items`.
    * ``first_kept_entry_id`` set (no ``retained_tail``) — ``[compaction] +
      (entries from ``first_kept_entry_id`` up to the compaction) +
      post-compaction entries``.
    """
    idx = _latest_compaction_index(path)
    if idx is None:
        return list(path)
    compaction = path[idx]
    assert isinstance(compaction, CompactionEntry)  # _latest_compaction_index guarantees it
    post = list(path[idx + 1 :])
    if compaction.retained_tail is not None:
        kept: list[SessionEntry] = []
    elif compaction.first_kept_entry_id is not None:
        kept = _kept_window(path, compaction.first_kept_entry_id, idx)
    else:
        kept = []
    return [compaction, *kept, *post]


def _kept_window(
    path: Sequence[SessionEntry], first_kept_entry_id: str, compaction_idx: int
) -> list[SessionEntry]:
    """The retained entries from ``first_kept_entry_id`` up to the compaction."""
    start = next(
        (i for i, entry in enumerate(path) if entry.id == first_kept_entry_id),
        None,
    )
    if start is None:
        return []
    return list(path[start:compaction_idx])


def _compaction_summary_item(compaction: CompactionEntry) -> UserContextItem:
    return UserContextItem(
        id=compaction.id,
        message=UserMessage(
            role=Role.User,
            content=_COMPACTION_SUMMARY_PREFIX + compaction.summary,
            timestamp=_to_ms(compaction.timestamp),
        ),
    )


def _branch_summary_item(entry: BranchSummaryEntry) -> UserContextItem:
    return UserContextItem(
        id=entry.id,
        message=UserMessage(
            role=Role.User,
            content=_BRANCH_SUMMARY_PREFIX + entry.summary + _BRANCH_SUMMARY_SUFFIX,
            timestamp=_to_ms(entry.timestamp),
        ),
    )


def _custom_message_item(entry: CustomMessageEntry) -> UserContextItem:
    return UserContextItem(
        id=entry.id,
        message=UserMessage(
            role=Role.User,
            content=entry.content,
            timestamp=_to_ms(entry.timestamp),
        ),
    )


def entries_to_items(entries: Sequence[SessionEntry]) -> list[ContextItem]:
    """Project entries to otter :class:`ContextItem` s, IN PATH ORDER.

    * :class:`MessageEntry` → its carried :class:`ContextItem` (verbatim).
    * :class:`MessageUpdateEntry` → its carried revised :class:`ContextItem`
      (folded by :func:`apply_updates` next).
    * :class:`CompactionEntry` → a synthesized user-role :class:`ContextItem`
      (the compaction marker), immediately followed by the ``retained_tail``
      items verbatim (their real ids/timestamps).
    * :class:`BranchSummaryEntry` → a synthesized ``UserMessage``
      :class:`ContextItem` with the ``[branch-summary:…]`` marker.
    * :class:`CustomMessageEntry` → a synthesized ``UserMessage``
      :class:`ContextItem` from its ``content`` (always projected; ``display``
      is inert metadata).
    * :class:`LabelEntry` / :class:`SessionInfoEntry` / :class:`CustomEntry` /
      change entries → no items.

    The projection OWNS timestamp + id synthesis for synthesized items: the
    item ``id`` = the tree entry id (unique on the path, stable across
    re-projection) and the ``timestamp`` is the entry's ISO-8601 timestamp
    converted to int ms. Carried items (Message / MessageUpdate / retained_tail)
    pass through with their real ids/timestamps. A projected :class:`Context` is
    therefore always well-formed.
    """
    items: list[ContextItem] = []
    for entry in entries:
        match entry:
            case MessageEntry() | MessageUpdateEntry():
                items.append(entry.item)
            case CompactionEntry():
                items.append(_compaction_summary_item(entry))
                if entry.retained_tail:
                    items.extend(entry.retained_tail)
            case BranchSummaryEntry():
                items.append(_branch_summary_item(entry))
            case CustomMessageEntry():
                items.append(_custom_message_item(entry))
            case (
                ModelChangeEntry()
                | ThinkingLevelChangeEntry()
                | ActiveToolsChangeEntry()
                | CustomEntry()
                | LabelEntry()
                | SessionInfoEntry()
            ):
                pass
    return items


def apply_updates(items: Sequence[ContextItem]) -> list[ContextItem]:
    """Fold append-only item amendments.

    Dedupe by ``item.id`` (the server item id): for each id, keep the **entire
    latest** item (its ``message`` wholesale — content *and* the new timestamp
    and all provenance/accounting fields, not just the inner ``.content``) at
    the **first** occurrence's position, and drop later occurrences. Items
    without an earlier same-id sibling simply stand at their own position
    (robust to a revision whose original was branched away). Synthesized items
    have distinct tree-derived ids, so they are never collapsed with each other
    or with carried items. Relative order of distinct ids is otherwise preserved.

    "Latest" is defined by position in append order (the path the store
    returns), which agrees with timestamp order for a well-formed append log and
    is more robust than comparing timestamps under clock skew.
    """
    latest: dict[str, ContextItem] = {}
    for item in items:
        latest[item.id] = item  # later occurrence overwrites
    seen: set[str] = set()
    out: list[ContextItem] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(latest[item.id])
    return out


def derive_state(path: Sequence[SessionEntry]) -> SessionDerivedState:
    """Derive settings from the latest matching change entry on the path.

    Walks the **un-transformed** path (independent of compaction — state is
    derivable even when a change entry sits before a compaction, so long as it
    remains on the store-returned path):

    * model/provider — latest :class:`ModelChangeEntry`; OR, if none on the
      path, from the latest assistant message's provenance
      (``AssistantMessage.provider`` / ``model``) so a session that never
      recorded a model change still projects a correct model. This is why
      :class:`ModelChangeEntry.provider` is ``str``: ``KnownProviders`` is a
      *closed* :class:`~enum.StrEnum` that would break round-trip for
      runtime-registered providers.
    * thinking level — latest :class:`ThinkingLevelChangeEntry`.
    * active tools — latest :class:`ActiveToolsChangeEntry`.
    """
    model: tuple[str, str] | None = None
    has_model_change = False
    thinking_level: ThinkingLevel | None = None
    active_tool_names: list[str] | None = None
    assistant_model: tuple[str, str] | None = None

    for entry in path:
        if isinstance(entry, ModelChangeEntry):
            # An explicit model change always wins, even over a later assistant
            # message's provenance: the fallback applies only when NO
            # ModelChangeEntry is on the path at all. Overwrite each time so the
            # LATEST model change wins.
            has_model_change = True
            model = (entry.provider, entry.model)
        elif isinstance(entry, MessageEntry | MessageUpdateEntry):
            msg = entry.item.message
            if isinstance(msg, AssistantMessage):
                # Latest assistant-message provenance wins as the fallback
                # (overwrite each time; ModelChangeEntry is resolved below).
                assistant_model = (msg.provider, msg.model)
        elif isinstance(entry, ThinkingLevelChangeEntry):
            thinking_level = entry.thinking_level
        elif isinstance(entry, ActiveToolsChangeEntry):
            active_tool_names = entry.active_tool_names

    return SessionDerivedState(
        model=model if has_model_change else assistant_model,
        thinking_level=thinking_level,
        active_tool_names=active_tool_names,
    )


def project(path: Sequence[SessionEntry]) -> SessionProjection:
    """Compose the projection pipeline over the leaf→root path.

    :func:`apply_compaction_transform` → :func:`entries_to_items` →
    :func:`apply_updates`, plus :func:`derive_state` over the un-transformed
    path.
    """
    transformed = apply_compaction_transform(path)
    items = apply_updates(entries_to_items(transformed))
    context = Context(system_prompt=None, items=items, tools=None)
    state = derive_state(path)
    return SessionProjection(context=context, state=state)


__all__ = [
    "SessionDerivedState",
    "SessionProjection",
    "apply_compaction_transform",
    "entries_to_items",
    "apply_updates",
    "derive_state",
    "project",
]
