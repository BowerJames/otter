"""Opt-in message normalization for replay-preparation.

These functions prepare a message list for replay to an LLM elsewhere (e.g. in
a provider package). They are intentionally **model-agnostic** and **opt-in**:

* they are **never** applied automatically at :class:`~otter_ai.context.Context`
  construction or via validators;
* call them explicitly only when you intend to replay the messages to a model.

Only the two invariants that require no model knowledge are provided here. The
model-aware invariants from the upstream pi-ai library (image downgrade, and
cross-model handling of thinking/text/thought signatures) require model
knowledge and live outside this data-only package.
"""

from __future__ import annotations

from otter_ai.content import TextContent, ToolCall
from otter_ai.messages import AssistantMessage, Message, ToolResultMessage

#: ``stop_reason`` values whose turns are not safe to replay.
_UNREPLAYABLE_STOP_REASONS = frozenset({"error", "aborted"})


def drop_unreplayable_assistant_turns(messages: list[Message]) -> list[Message]:
    """Return a copy of ``messages`` with unreplayable assistant turns removed.

    Assistant turns whose ``stop_reason`` is ``"error"`` or ``"aborted"`` are
    incomplete (they may carry partial content, reasoning without a following
    item, or unresolved tool calls) and can break replay. Such turns are
    dropped; all other messages are preserved in order.
    """
    return [
        message
        for message in messages
        if not (
            isinstance(message, AssistantMessage)
            and message.stop_reason in _UNREPLAYABLE_STOP_REASONS
        )
    ]


def fill_missing_tool_results(messages: list[Message]) -> list[Message]:
    """Insert synthetic error tool results for orphaned tool calls.

    For every :class:`~otter_ai.messages.ToolCall` that is not followed by a
    matching :class:`~otter_ai.messages.ToolResultMessage` before the next
    assistant/user turn (or the end of the list), a synthetic
    ``tool_result`` is inserted with ``is_error=True`` and text
    ``"No result provided"``. Tool results that already exist are left
    untouched.

    The input list is not mutated; a new list is returned.
    """
    result: list[Message] = []

    pending_tool_calls: list[ToolCall] = []
    seen_result_ids: set[str] = set()

    def _flush_pending() -> None:
        for call in pending_tool_calls:
            if call.id not in seen_result_ids:
                result.append(
                    ToolResultMessage(
                        role="tool_result",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content=[TextContent(type="text", text="No result provided")],
                        is_error=True,
                        timestamp=_synthetic_timestamp(result),
                    )
                )
        pending_tool_calls.clear()
        seen_result_ids.clear()

    for message in messages:
        if isinstance(message, AssistantMessage):
            # A new assistant turn starts a fresh tool-call batch; first close
            # out any still-unresolved calls from the previous assistant turn.
            _flush_pending()
            calls = [block for block in message.content if isinstance(block, ToolCall)]
            if calls:
                pending_tool_calls = calls
                seen_result_ids = set()
            result.append(message)
        elif isinstance(message, ToolResultMessage):
            seen_result_ids.add(message.tool_call_id)
            result.append(message)
        else:
            # A user message interrupts the tool flow; close out orphaned calls.
            _flush_pending()
            result.append(message)

    # Trailing unresolved tool calls at end-of-list.
    _flush_pending()

    return result


def normalize_messages(messages: list[Message]) -> list[Message]:
    """Convenience: drop unreplayable turns, then fill missing tool results.

    Equivalent to::

        fill_missing_tool_results(drop_unreplayable_assistant_turns(messages))
    """
    return fill_missing_tool_results(drop_unreplayable_assistant_turns(messages))


def _synthetic_timestamp(preceding: list[Message]) -> int:
    """Timestamp for a synthetic tool result.

    Uses the timestamp of the preceding tool call when available (so the
    synthetic result sorts after it), otherwise 0.
    """
    for message in reversed(preceding):
        if isinstance(message, AssistantMessage):
            return message.timestamp
    return 0
