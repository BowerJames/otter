"""Model input and turns in the responses format."""

import json
from typing import assert_never, cast

from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseInputContentParam,
    ResponseInputItemParam,
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

from .errors import ModelFailed

_AUDIO_OMITTED = "[audio omitted: this model cannot hear audio]"


def tools_of(tools: tuple[ToolSpec, ...]) -> list[FunctionToolParam]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
            # Left out, the endpoint holds the schema to its strict rules, which a
            # tool's schema need not meet.
            "strict": False,
        }
        for tool in tools
    ]


def items_of(entry: ContextEntry) -> list[ResponseInputItemParam]:
    """The input items `entry` is sent as."""
    match entry:
        case UserMessage():
            return [{"role": "user", "content": [_user_part_of(part) for part in entry.content]}]
        case AssistantMessage():
            return _assistant_items_of(entry)
        case ToolResultMessage():
            return [
                {
                    "type": "function_call_output",
                    "call_id": entry.tool_call_id,
                    "output": entry.text,
                }
            ]
        case _:
            assert_never(entry)


def turn_of(response: Response) -> AssistantMessage:
    """The model's turn, read from the response it was produced in.

    A response reporting that the model failed raises `ModelFailed`; tool arguments
    that are not valid JSON raise `json.JSONDecodeError`.
    """
    if response.error is not None:
        raise ModelFailed(response.error.message)
    content: list[AssistantPart] = []
    for item in response.output:
        if item.type == "reasoning":
            # Providers differ in where they show reasoning: OpenAI as a summary,
            # Z.ai as the reasoning itself.
            thinking = "\n\n".join(part.text for part in item.content or item.summary)
            if thinking:
                content.append(ThinkingPart(thinking))
        elif item.type == "message":
            content.extend(
                TextPart(part.text if part.type == "output_text" else part.refusal)
                for part in item.content
            )
        elif item.type == "function_call":
            content.append(ToolCall(item.call_id, item.name, json.loads(item.arguments)))
    return AssistantMessage(tuple(content))


def output_items_of(response: Response) -> list[ResponseInputItemParam]:
    """The items the model produced, as they are sent back: reasoning included."""
    return [
        cast(ResponseInputItemParam, item.model_dump(mode="json", exclude_unset=True))
        for item in response.output
    ]


def _user_part_of(part: UserPart) -> ResponseInputContentParam:
    match part:
        case TextPart():
            return {"type": "input_text", "text": part.text}
        case ImagePart():
            return {
                "type": "input_image",
                "image_url": f"data:{part.media_type};base64,{part.data}",
                "detail": "auto",
            }
        case ImageUrlPart():
            return {"type": "input_image", "image_url": part.url, "detail": "auto"}
        case AudioPart():
            # The format has no place for audio.
            return {"type": "input_text", "text": _AUDIO_OMITTED}
        case _:
            assert_never(part)


def _assistant_items_of(message: AssistantMessage) -> list[ResponseInputItemParam]:
    items: list[ResponseInputItemParam] = []
    for part in message.content:
        match part:
            case TextPart():
                items.append({"role": "assistant", "content": part.text})
            case ToolCall():
                items.append(
                    {
                        "type": "function_call",
                        "call_id": part.id,
                        "name": part.name,
                        "arguments": json.dumps(part.arguments),
                    }
                )
            case ThinkingPart():
                # Only the provider's own reasoning items can be sent back, and a
                # context entry does not carry them.
                pass
            case _:
                assert_never(part)
    return items
