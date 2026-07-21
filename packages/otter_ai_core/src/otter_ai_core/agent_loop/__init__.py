"""Agent-loop subpackage: the turn/tool-execution cycle over a
:class:`~otter_ai_core.model_controller.ModelController`, and the typed hooks
it emits.
"""

from otter_ai_core.agent_loop.hooks import (
    BEFORE_TOOL_CALL,
    TOOL_RESULT,
    AgentLoopHookTypes,
    ToolResultHookParams,
)

__all__ = [
    "AgentLoopHookTypes",
    "BEFORE_TOOL_CALL",
    "TOOL_RESULT",
    "ToolResultHookParams",
]
