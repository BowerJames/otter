"""Context entries as lines of JSON, one entry to a line."""

import json
from typing import assert_never

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
    UserMessage,
    UserPart,
)

from .errors import NotAnEntry


def line_of(entry: ContextEntry) -> str:
    """Return `entry` as one line of JSON, its newline included."""
    return json.dumps(_entry_as_json(entry), ensure_ascii=False) + "\n"


def entries_of(text: str) -> tuple[ContextEntry, ...]:
    """Return the entries written as lines of `text`, in order."""
    # Split on the newline alone: a JSON string cannot hold one, but it can hold the
    # other characters `splitlines` breaks on.
    return tuple(_entry_from_json(json.loads(line)) for line in text.split("\n") if line)


def _entry_as_json(entry: ContextEntry) -> dict[str, object]:
    match entry:
        case UserMessage():
            return {"type": "user", "content": [_part_as_json(part) for part in entry.content]}
        case AssistantMessage():
            return {"type": "assistant", "content": [_part_as_json(part) for part in entry.content]}
        case ToolResultMessage():
            return {"type": "tool_result", "tool_call_id": entry.tool_call_id, "text": entry.text}
        case _:
            assert_never(entry)


def _part_as_json(part: UserPart | AssistantPart) -> dict[str, object]:
    match part:
        case TextPart():
            return {"type": "text", "text": part.text}
        case ImagePart():
            return {"type": "image", "data": part.data, "media_type": part.media_type}
        case ImageUrlPart():
            return {"type": "image_url", "url": part.url}
        case AudioPart():
            return {"type": "audio", "data": part.data, "format": part.format}
        case ThinkingPart():
            return {"type": "thinking", "text": part.text}
        case ToolCall():
            return {
                "type": "tool_call",
                "id": part.id,
                "name": part.name,
                "arguments": dict(part.arguments),
            }
        case _:
            assert_never(part)


def _entry_from_json(value: object) -> ContextEntry:
    entry = _object(value)
    match _field(entry, "type"):
        case "user":
            return UserMessage(tuple(_user_part(part) for part in _list(entry, "content")))
        case "assistant":
            return AssistantMessage(
                tuple(_assistant_part(part) for part in _list(entry, "content"))
            )
        case "tool_result":
            return ToolResultMessage(_field(entry, "tool_call_id"), _field(entry, "text"))
        case unknown:
            raise NotAnEntry(f"unknown entry type {unknown!r}")


def _user_part(value: object) -> UserPart:
    part = _object(value)
    match _field(part, "type"):
        case "text":
            return TextPart(_field(part, "text"))
        case "image":
            return ImagePart(data=_field(part, "data"), media_type=_field(part, "media_type"))
        case "image_url":
            return ImageUrlPart(url=_field(part, "url"))
        case "audio":
            match _field(part, "format"):
                case "wav" | "mp3" as audio_format:
                    return AudioPart(data=_field(part, "data"), format=audio_format)
                case unknown:
                    raise NotAnEntry(f"unknown audio format {unknown!r}")
        case unknown:
            raise NotAnEntry(f"unknown user part type {unknown!r}")


def _assistant_part(value: object) -> AssistantPart:
    part = _object(value)
    match _field(part, "type"):
        case "thinking":
            return ThinkingPart(_field(part, "text"))
        case "text":
            return TextPart(_field(part, "text"))
        case "tool_call":
            arguments = part.get("arguments")
            if not isinstance(arguments, dict):
                raise NotAnEntry("a tool call's arguments are not an object")
            return ToolCall(_field(part, "id"), _field(part, "name"), arguments)
        case unknown:
            raise NotAnEntry(f"unknown assistant part type {unknown!r}")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise NotAnEntry(f"not an object: {value!r}")
    return value


def _field(value: dict[str, object], name: str) -> str:
    field = value.get(name)
    if not isinstance(field, str):
        raise NotAnEntry(f"missing the text field {name!r}")
    return field


def _list(value: dict[str, object], name: str) -> list[object]:
    field = value.get(name)
    if not isinstance(field, list):
        raise NotAnEntry(f"missing the list field {name!r}")
    return field
