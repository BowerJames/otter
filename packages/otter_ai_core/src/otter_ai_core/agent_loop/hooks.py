"""Hook descriptors emitted by :class:`~otter_ai_core.agent_loop.agent_loop.AgentLoop`.

The hook *key* is still a typed :class:`~otter_ai_core.hook_runner.Hook`
descriptor: a :class:`~enum.StrEnum` cannot carry per-member type parameters,
so the type checker could not recover the return type from an enum-keyed
``emit``. Instead the enum here centralizes the hook *name strings* so they are
discoverable rather than magic-string literals, and the typed
:class:`~otter_ai_core.hook_runner.Hook` singleton (built from the enum member)
remains the value callers register against.

Because :class:`~enum.StrEnum` members are :class:`str` instances that hash and
compare equal to their value, ``Hook(AgentLoopHookTypes.X)`` keys identically to
``Hook("x")`` in the :class:`~otter_ai_core.hook_runner.HookRunner` registry.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from otter_ai_core.agent_loop.agent_tool import AgentToolResult
from otter_ai_core.context import ToolCall
from otter_ai_core.hook_runner import Hook


class AgentLoopHookTypes(StrEnum):
    """The ``name`` of a hook emitted by :class:`AgentLoop`."""

    BEFORE_TOOL_CALL = "before_tool_call"


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


__all__ = ["AgentLoopHookTypes", "BEFORE_TOOL_CALL"]
