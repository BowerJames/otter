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
    model: tuple[str, str] | None
    thinking_level: ThinkingLevel | None
    active_tool_names: list[str] | None


@dataclass(frozen=True, slots=True)
class SessionProjection:
    context: Context
    state: SessionDerivedState


#: Prefix of the synthesized compaction-summary user message.
_COMPACTION_SUMMARY_PREFIX = "[compaction-summary]\n\n"
#: Marker wrapping a synthesized branch-summary user message.
_BRANCH_SUMMARY_PREFIX = "[branch-summary:]\n"
_BRANCH_SUMMARY_SUFFIX = "]"


def _to_ms(iso: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _latest_compaction_index(path: Sequence[SessionEntry]) -> int | None:
    for i in range(len(path) - 1, -1, -1):
        if isinstance(path[i], CompactionEntry):
            return i
    return None


def apply_compaction_transform(path: Sequence[SessionEntry]) -> list[SessionEntry]:
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
