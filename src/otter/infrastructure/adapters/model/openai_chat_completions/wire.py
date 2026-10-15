"""Model input and turns in the chat completions format."""

import json
from typing import assert_never

from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
)

from otter.core.domain.messages import (
    AssistantMessage,
    AssistantPart,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.core.model import ModelInput


def messages_of(model_input: ModelInput) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = []
    if model_input.system is not None:
        messages.append({"role": "system", "content": model_input.system})
    messages.extend(_message_of(entry) for entry in model_input.context)
    return messages


def tools_of(tools: tuple[ToolSpec, ...]) -> list[ChatCompletionFunctionToolParam]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }
        for tool in tools
    ]


def turn_of(message: ChatCompletionMessage) -> AssistantMessage:
    """The model's turn, read from the message it replied with.

    Tool arguments that are not valid JSON raise `json.JSONDecodeError`.
    """
    content: list[AssistantPart] = []
    # Not part of the chat completions format: providers that show their reasoning
    # (Z.ai among them) add it to the message as this extra field.
    thinking = (message.model_extra or {}).get("reasoning_content")
    if isinstance(thinking, str) and thinking:
        content.append(ThinkingPart(thinking))
    if message.content:
        content.append(TextPart(message.content))
    content.extend(
        ToolCall(call.id, call.function.name, json.loads(call.function.arguments))
        for call in message.tool_calls or []
        if call.type == "function"
    )
    return AssistantMessage(tuple(content))


def _message_of(entry: ContextEntry) -> ChatCompletionMessageParam:
    match entry:
        case UserMessage():
            return {"role": "user", "content": [_user_part_of(part) for part in entry.content]}
        case AssistantMessage():
            return _assistant_message_of(entry)
        case ToolResultMessage():
            return {"role": "tool", "tool_call_id": entry.tool_call_id, "content": entry.text}
        case _:
            assert_never(entry)


def _user_part_of(part: UserPart) -> ChatCompletionContentPartParam:
    match part:
        case TextPart():
            return {"type": "text", "text": part.text}
        case ImagePart():
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{part.media_type};base64,{part.data}"},
            }
        case ImageUrlPart():
            return {"type": "image_url", "image_url": {"url": part.url}}
        case AudioPart():
            return {
                "type": "input_audio",
                "input_audio": {"data": part.data, "format": part.format},
            }
        case _:
            assert_never(part)


def _assistant_message_of(message: AssistantMessage) -> ChatCompletionAssistantMessageParam:
    # The format has no place for thinking: it is not sent back.
    wire: ChatCompletionAssistantMessageParam = {"role": "assistant"}
    texts = [part.text for part in message.content if isinstance(part, TextPart)]
    if texts:
        wire["content"] = "\n\n".join(texts)
    calls = [part for part in message.content if isinstance(part, ToolCall)]
    if calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in calls
        ]
    return wire
