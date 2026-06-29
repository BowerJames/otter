"""otter-ai-chat-completions — Chat Completions wire-format contract package.

Defines the data model (:class:`ChatCompletionsModel`, cost, compat), the
runtime options bundle (model + hooks), and the seam
:func:`create_chat_completions_assistant_message_stream` — a concrete
implementation of
:data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`
for the Chat Completions wire format. The builder takes the options bundle and
returns an
:class:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`;
the context and abort signal are supplied when that function is invoked.

Scope: this package owns the Chat Completions wire-format contract only.
Provider-specific configuration (compat flags, static headers, env-key
resolution, model catalog) is the consumer's responsibility.
"""

from __future__ import annotations

from otter_ai_chat_completions.hooks import (
    ChatCompletionsHooks,
    OnPayloadEvent,
    OnPayloadHook,
    OnResponseEvent,
    OnResponseHook,
    Payload,
)
from otter_ai_chat_completions.models import (
    CHAT_TEMPLATE_THINKING_EFFORT,
    CHAT_TEMPLATE_THINKING_ENABLED,
    ChatCompletionsApi,
    ChatCompletionsCompat,
    ChatCompletionsCost,
    ChatCompletionsModel,
    ChatCompletionsReasoningEffort,
    ChatCompletionsThinkingLevelKey,
    ChatTemplateKwargValue,
    ChatTemplateKwargVar,
    ChatTemplateKwargVarName,
)
from otter_ai_chat_completions.options import ChatCompletionsModelOptions
from otter_ai_chat_completions.stream import (
    create_chat_completions_assistant_message_stream,
)

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # data model
    "ChatCompletionsApi",
    "ChatCompletionsCompat",
    "ChatCompletionsCost",
    "ChatCompletionsModel",
    "ChatCompletionsReasoningEffort",
    "ChatCompletionsThinkingLevelKey",
    "ChatTemplateKwargValue",
    "ChatTemplateKwargVar",
    "ChatTemplateKwargVarName",
    "CHAT_TEMPLATE_THINKING_ENABLED",
    "CHAT_TEMPLATE_THINKING_EFFORT",
    # hooks
    "ChatCompletionsHooks",
    "OnPayloadEvent",
    "OnPayloadHook",
    "OnResponseEvent",
    "OnResponseHook",
    "Payload",
    # options bundle
    "ChatCompletionsModelOptions",
    # seam
    "create_chat_completions_assistant_message_stream",
]
