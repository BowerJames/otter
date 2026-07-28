from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from otter_ai_core.agent_loop.agent_tool import AgentToolResult
from otter_ai_core.context import ToolCall
from otter_ai_core.hook_runner import Hook


class AgentLoopHookTypes(StrEnum):
    BEFORE_TOOL_CALL = "before_tool_call"
    TOOL_RESULT = "tool_result"


#: Emitted before each :class:`~otter_ai_core.context.ToolCall` is executed —
#: the first real emit site on the loop's :class:`~otter_ai_core.hook_runner.HookRunner`
#: surface. The handler receives the ``ToolCall`` and may return an
#: :class:`~otter_ai_core.agent_loop.agent_tool.AgentToolResult` to
#: **short-circuit** execution (the tool's ``execute`` is not called; the result
#: is still wrapped and fed back to the model as a ``ToolResultMessage``, with
#: ``terminate`` honoured), or ``None`` to defer to normal execution (including
#: unknown-tool synthesis).
BEFORE_TOOL_CALL: Hook[ToolCall, AgentToolResult[Any] | None] = Hook(
    AgentLoopHookTypes.BEFORE_TOOL_CALL
)


@dataclass(frozen=True, slots=True)
class ToolResultHookParams:
    tool_call: ToolCall
    result: AgentToolResult[Any]


#: Emitted after a tool **actually executes** (i.e. its ``execute`` returned) —
#: the post-execution counterpart to :data:`BEFORE_TOOL_CALL`. It is **not**
#: emitted when :data:`BEFORE_TOOL_CALL` short-circuits the call (the tool never
#: ran), nor for unknown-tool synthesis (no tool ran). The handler receives the
#: ``ToolCall`` and the executed ``AgentToolResult``; returning ``None``
#: **persists** the original result, while returning an ``AgentToolResult``
#: **fully replaces** it — its ``result`` / ``details`` / ``is_error`` flow
#: through to the ``ToolResultMessage`` and its ``terminate`` is honoured
#: (exactly as :data:`BEFORE_TOOL_CALL` honours an intercepted result's
#: ``terminate``).
TOOL_RESULT: Hook[ToolResultHookParams, AgentToolResult[Any] | None] = Hook(
    AgentLoopHookTypes.TOOL_RESULT
)


__all__ = ["AgentLoopHookTypes", "BEFORE_TOOL_CALL", "TOOL_RESULT", "ToolResultHookParams"]
