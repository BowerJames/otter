"""Otter AI — LLM context data model.

This package provides a Pydantic v2 model for representing LLM conversation
context (``Context``, messages, content blocks, tools, usage). It is data-only:
no LLMs, providers, APIs, or streaming.
"""

from __future__ import annotations

from otter_ai.content import (
    AssistantContent,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    UserContent,
)
from otter_ai.context import Context
from otter_ai.diagnostics import (
    AssistantMessageDiagnostic,
    DiagnosticErrorInfo,
)
from otter_ai.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)
from otter_ai.normalize import (
    drop_unreplayable_assistant_turns,
    fill_missing_tool_results,
    normalize_messages,
)
from otter_ai.tools import Tool, tool_from_pydantic
from otter_ai.types import Api, Provider, StopReason
from otter_ai.usage import Usage, UsageCost

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # metadata / literals
    "Api",
    "Provider",
    "StopReason",
    # usage
    "Usage",
    "UsageCost",
    # diagnostics
    "AssistantMessageDiagnostic",
    "DiagnosticErrorInfo",
    # content
    "AssistantContent",
    "ImageContent",
    "TextContent",
    "ThinkingContent",
    "ToolCall",
    "UserContent",
    # tools
    "Tool",
    "tool_from_pydantic",
    # messages
    "AssistantMessage",
    "Message",
    "ToolResultMessage",
    "UserMessage",
    # context
    "Context",
    # normalize (opt-in)
    "drop_unreplayable_assistant_turns",
    "fill_missing_tool_results",
    "normalize_messages",
]
