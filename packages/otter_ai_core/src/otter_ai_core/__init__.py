from __future__ import annotations

from otter_ai_core.bidirectional_channel import (
    BidirectionalChannelBackend,
    BidirectionalChannelClient,
    BidirectionalChannelPair,
    create_bidirectional_channel,
)
from otter_ai_core.builder import BuilderFn
from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)
from otter_ai_core.connection import (
    ConnectionBackend,
    ConnectionClient,
    ConnectionPair,
    create_connection,
)
from otter_ai_core.context import (
    AssistantContent,
    AssistantContextItem,
    AssistantMessage,
    AssistantMessageDiagnostic,
    Context,
    ContextItem,
    DiagnosticErrorInfo,
    ImageContent,
    Message,
    StopReason,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContent,
    UserContextItem,
    UserMessage,
    context_item,
)
from otter_ai_core.model_controller import ModelController, State
from otter_ai_core.provider_api_model_options import (
    KnownApis,
    KnownProviders,
    ProviderModelOption,
    ThinkingLevel,
)
from otter_ai_core.stream import (
    StreamBackend,
    StreamClient,
    StreamPair,
    create_stream_pair,
)

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # builder
    "BuilderFn",
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
    # messages
    "AssistantMessage",
    "Message",
    "StopReason",
    "ToolResultMessage",
    "UserMessage",
    # context
    "AssistantContextItem",
    "Context",
    "ContextItem",
    "ToolResultContextItem",
    "UserContextItem",
    "context_item",
    # provider/api/model options
    "KnownApis",
    "KnownProviders",
    "ProviderModelOption",
    "ThinkingLevel",
    # channel runtime (one-way)
    "ChannelPair",
    "ChannelReader",
    "ChannelWriter",
    "create_channel",
    # stream runtime (abortable one-way facade over the channel)
    "StreamBackend",
    "StreamClient",
    "StreamPair",
    "create_stream_pair",
    # channel runtime (bidirectional primitive)
    "BidirectionalChannelClient",
    "BidirectionalChannelBackend",
    "BidirectionalChannelPair",
    "create_bidirectional_channel",
    # connection runtime (abortable bidirectional facade over the channel)
    "ConnectionClient",
    "ConnectionBackend",
    "ConnectionPair",
    "create_connection",
    # model controller (high-level conversation driver over a connection;
    # re-exported at the top level, unlike the subpackage-only model_connection)
    "ModelController",
    "State",
]
