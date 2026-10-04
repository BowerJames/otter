"""A session manager that keeps a session's context in a file."""

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, assert_never

from otter.messages import (
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
from otter.session_manager import SessionManager


class FileSystem(Protocol):
    """What a file system session manager needs of the file system it keeps its file in."""

    def read_text(self, path: Path) -> str:
        """Return the text of the UTF-8 file at `path`.

        Raises `FileNotFoundError` if there is no such file.
        """
        ...

    def append_text(self, path: Path, text: str) -> None:
        """Add `text` to the end of the UTF-8 file at `path`.

        A file that does not exist is made, along with any directories it sits in.
        Raises `OSError` if the text cannot be written.
        """
        ...


class _LocalFileSystem:
    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def append_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(text)


_local_file_system = _LocalFileSystem()


def create_file_system_session_manager(
    path: str | os.PathLike[str], *, file_system: FileSystem = _local_file_system
) -> SessionManager:
    """Return a session manager that keeps its entries in the JSON Lines file at `path`.

    Each entry is one line of the file, a JSON object, in the order the entries were
    appended; the file is UTF-8. The entries a file already holds are the entries the
    session manager starts out with, so a session made with it picks up where the one
    that wrote the file left off. A file that does not exist holds no entries: it is
    made, along with any directories it sits in, when the first entry is appended.
    Nothing is read or written until the session manager is used. `file_system` is
    where the file is kept; leave it out to keep it on this machine's file system.

    Errors propagate. An entry that cannot be written raises `OSError`, and the entries
    are as they were. Reading a file
    that holds something other than entries raises `json.JSONDecodeError` for a line
    that is not JSON and `ValueError` for one that is not an entry.
    """
    return _JsonLinesSessionManager(Path(path), file_system)


class _JsonLinesSessionManager:
    def __init__(self, path: Path, file_system: FileSystem) -> None:
        self._path = path
        self._file_system = file_system

    def append(self, entry: ContextEntry) -> None:
        line = json.dumps(_entry_as_json(entry), ensure_ascii=False)
        self._file_system.append_text(self._path, line + "\n")

    def entries(self) -> Sequence[ContextEntry]:
        try:
            text = self._file_system.read_text(self._path)
        except FileNotFoundError:
            return ()
        # Split on the newline alone: a JSON string cannot hold one, but it can hold
        # the other characters `splitlines` breaks on.
        return tuple(_entry_from_json(json.loads(line)) for line in text.split("\n") if line)


def _entry_as_json(entry: ContextEntry) -> dict[str, object]:
    match entry:
        case UserMessage():
            return {"type": "user", "content": [_part_as_json(part) for part in entry.content]}
        case AssistantMessage():
            return {
                "type": "assistant",
                "content": [_part_as_json(part) for part in entry.content],
            }
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


def _entry_from_json(value: Any) -> ContextEntry:
    if not isinstance(value, dict):
        raise ValueError(f"not a context entry: {value!r}")
    try:
        match value["type"]:
            case "user":
                return UserMessage(tuple(_user_part_from_json(part) for part in value["content"]))
            case "assistant":
                return AssistantMessage(
                    tuple(_assistant_part_from_json(part) for part in value["content"])
                )
            case "tool_result":
                return ToolResultMessage(value["tool_call_id"], value["text"])
            case unknown:
                raise ValueError(f"not a context entry: unknown type {unknown!r}")
    except KeyError as error:
        raise ValueError(f"not a context entry: missing {error.args[0]!r}") from error


def _user_part_from_json(part: Any) -> UserPart:
    match part["type"]:
        case "text":
            return TextPart(part["text"])
        case "image":
            return ImagePart(data=part["data"], media_type=part["media_type"])
        case "image_url":
            return ImageUrlPart(url=part["url"])
        case "audio":
            return AudioPart(data=part["data"], format=part["format"])
        case unknown:
            raise ValueError(f"not a context entry: unknown part type {unknown!r}")


def _assistant_part_from_json(part: Any) -> AssistantPart:
    match part["type"]:
        case "thinking":
            return ThinkingPart(part["text"])
        case "text":
            return TextPart(part["text"])
        case "tool_call":
            return ToolCall(id=part["id"], name=part["name"], arguments=part["arguments"])
        case unknown:
            raise ValueError(f"not a context entry: unknown part type {unknown!r}")
