"""Context data-model subpackage facade.

This package groups the Pydantic v2 models that represent LLM conversation
context: the top-level :class:`Context`, the :data:`ContextItem` / message
layers, the content blocks, tools-adjacent enums, usage accounting, and
diagnostics.

It is a supported import surface (Strategy A — two-layer facade): callers may
import from :mod:`otter_ai_core` (the headline API) or directly from
:mod:`otter_ai_core.context` (the full data-model surface, including
``Role`` / ``ContentType`` / ``DiagnosticErrorInfo``). The public surface is
declared via :data:`__all__`.
"""

from .content import (
    AssistantContent,
    ContentType,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    UserContent,
)
from .context import Context
from .context_item import (
    AssistantContextItem,
    ContextItem,
    ToolResultContextItem,
    UserContextItem,
    context_item,
)
from .diagnostics import AssistantMessageDiagnostic, DiagnosticErrorInfo
from .messages import (
    AssistantMessage,
    Message,
    StopReason,
    ToolResultMessage,
    UserMessage,
)
from .role import Role
from .usage import Usage, UsageCost

__all__ = [
    # content
    "AssistantContent",
    "ContentType",
    "ImageContent",
    "TextContent",
    "ThinkingContent",
    "ToolCall",
    "UserContent",
    # context
    "Context",
    # context_item
    "AssistantContextItem",
    "ContextItem",
    "ToolResultContextItem",
    "UserContextItem",
    "context_item",
    # diagnostics
    "AssistantMessageDiagnostic",
    "DiagnosticErrorInfo",
    # messages
    "AssistantMessage",
    "Message",
    "StopReason",
    "ToolResultMessage",
    "UserMessage",
    # role
    "Role",
    # usage
    "Usage",
    "UsageCost",
]
