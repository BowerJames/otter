"""Model input and turns in OpenAI's realtime format."""

import base64
import io
import json
import wave
from typing import assert_never

from openai.types.realtime import (
    ConversationItemParam,
    RealtimeResponse,
    RealtimeSessionCreateRequestParam,
)
from openai.types.realtime.realtime_conversation_item_user_message_param import (
    Content as UserContentParam,
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

_IMAGE_URL_OMITTED = "[image omitted: this model takes images inline, not from a URL]"
_AUDIO_OMITTED = "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]"


def session_of(
    system: str | None, tools: tuple[ToolSpec, ...]
) -> RealtimeSessionCreateRequestParam:
    session: RealtimeSessionCreateRequestParam = {"type": "realtime", "output_modalities": ["text"]}
    if system is not None:
        session["instructions"] = system
    if tools:
        session["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            }
            for tool in tools
        ]
    return session


def items_of(entry: ContextEntry) -> list[ConversationItemParam]:
    """The conversation items `entry` is sent as."""
    match entry:
        case UserMessage():
            return [
                {
                    "type": "message",
                    "role": "user",
                    "content": [_user_part_of(part) for part in entry.content],
                }
            ]
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


def turn_of(response: RealtimeResponse) -> AssistantMessage:
    """The model's turn, read from the response that ended it.

    A response that failed raises `ModelFailed`; tool arguments that are not valid JSON
    raise `json.JSONDecodeError`.
    """
    if response.status == "failed":
        failure = response.status_details and response.status_details.error
        raise ModelFailed((failure and (failure.code or failure.type)) or "no reason given")
    content: list[AssistantPart] = []
    for item in response.output or []:
        if item.type == "message" and item.role == "assistant":
            content.extend(TextPart(part.text or part.transcript or "") for part in item.content)
        elif item.type == "function_call":
            content.append(ToolCall(item.call_id or "", item.name, json.loads(item.arguments)))
    return AssistantMessage(tuple(content))


def _user_part_of(part: UserPart) -> UserContentParam:
    match part:
        case TextPart():
            return {"type": "input_text", "text": part.text}
        case ImagePart():
            return {
                "type": "input_image",
                "image_url": f"data:{part.media_type};base64,{part.data}",
            }
        case ImageUrlPart():
            return {"type": "input_text", "text": _IMAGE_URL_OMITTED}
        case AudioPart():
            samples = _samples_of(part)
            if samples is None:
                return {"type": "input_text", "text": _AUDIO_OMITTED}
            return {"type": "input_audio", "audio": base64.b64encode(samples).decode()}
        case _:
            assert_never(part)


def _samples_of(audio: AudioPart) -> bytes | None:
    """The samples of a clip already in the one form the endpoint takes, or None."""
    if audio.format != "wav":
        return None
    try:
        with wave.open(io.BytesIO(base64.b64decode(audio.data))) as clip:
            fits = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) == (1, 2, 24000)
            return clip.readframes(clip.getnframes()) if fits else None
    except (wave.Error, EOFError, ValueError):
        return None


def _assistant_items_of(message: AssistantMessage) -> list[ConversationItemParam]:
    items: list[ConversationItemParam] = []
    for part in message.content:
        match part:
            case TextPart():
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": part.text}],
                    }
                )
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
                # The endpoint has no place for reasoning it did not produce itself.
                pass
            case _:
                assert_never(part)
    return items
