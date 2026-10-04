"""Behaviour of the file system session manager, observed through the entries it returns and
the file it writes to a fake file system.
"""

import json
from json import JSONDecodeError
from pathlib import Path

import pytest

from otter.create_file_system_session_manager import create_file_system_session_manager
from otter.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

ASKS = UserMessage((TextPart("What is in a.txt?"),))
CALLS = AssistantMessage((ToolCall("call-1", "read_file", {"path": "a.txt"}),))
RESULT = ToolResultMessage("call-1", "file contents")


PATH = Path("sessions/session.jsonl")


class FakeFileSystem:
    """A test adapter for the file system: holds the text of each file by its path.

    While `failing` is set, an append raises it and writes nothing.
    """

    def __init__(self) -> None:
        self.files: dict[Path, str] = {}
        self.failing: OSError | None = None

    def read_text(self, path: Path) -> str:
        if path not in self.files:
            raise FileNotFoundError(str(path))
        return self.files[path]

    def append_text(self, path: Path, text: str) -> None:
        if self.failing is not None:
            raise self.failing
        self.files[path] = self.files.get(path, "") + text


@pytest.fixture
def files() -> FakeFileSystem:
    return FakeFileSystem()


def test_a_file_that_does_not_exist_holds_no_entries(files: FakeFileSystem) -> None:
    assert list(create_file_system_session_manager(PATH, file_system=files).entries()) == []


def test_making_a_session_manager_does_not_make_its_file(files: FakeFileSystem) -> None:
    create_file_system_session_manager(PATH, file_system=files)

    assert files.files == {}


def test_appended_entries_are_returned_in_the_order_they_were_appended(
    files: FakeFileSystem,
) -> None:
    manager = create_file_system_session_manager(PATH, file_system=files)
    manager.append(ASKS)
    manager.append(CALLS)
    manager.append(RESULT)

    assert list(manager.entries()) == [ASKS, CALLS, RESULT]


def test_a_session_manager_starts_out_with_the_entries_its_file_already_holds(
    files: FakeFileSystem,
) -> None:
    earlier = create_file_system_session_manager(PATH, file_system=files)
    earlier.append(ASKS)
    earlier.append(CALLS)

    manager = create_file_system_session_manager(PATH, file_system=files)
    manager.append(RESULT)

    assert list(manager.entries()) == [ASKS, CALLS, RESULT]


@pytest.mark.parametrize(
    "entry",
    [
        UserMessage(
            (
                TextPart("Look and listen"),
                ImagePart(data="iVBORw==", media_type="image/png"),
                ImageUrlPart(url="https://example.test/cat.png"),
                AudioPart(data="UklGRg==", format="wav"),
            )
        ),
        AssistantMessage(
            (
                ThinkingPart("The notes file is the place to look."),
                TextPart("Let me look."),
                ToolCall("call-1", "read_file", {"path": "notes.txt", "lines": [1, 20]}),
            )
        ),
        ToolResultMessage("call-1", "Buy milk.\nCall Zoë."),
    ],
)
def test_an_entry_is_read_back_as_it_was_appended(
    entry: ContextEntry, files: FakeFileSystem
) -> None:
    create_file_system_session_manager(PATH, file_system=files).append(entry)

    assert list(create_file_system_session_manager(PATH, file_system=files).entries()) == [entry]


def test_each_entry_is_written_as_one_line_of_json(files: FakeFileSystem) -> None:
    manager = create_file_system_session_manager(PATH, file_system=files)
    manager.append(UserMessage((TextPart("What is in a.txt?"),)))
    manager.append(
        AssistantMessage(
            (TextPart("Let me look."), ToolCall("call-1", "read_file", {"path": "a.txt"}))
        )
    )
    manager.append(ToolResultMessage("call-1", "line one\nline two"))

    lines = files.files[PATH].splitlines()

    assert [json.loads(line) for line in lines] == [
        {"type": "user", "content": [{"type": "text", "text": "What is in a.txt?"}]},
        {
            "type": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "a.txt"},
                },
            ],
        },
        {"type": "tool_result", "tool_call_id": "call-1", "text": "line one\nline two"},
    ]


def test_entries_already_returned_are_unchanged_by_a_later_append(files: FakeFileSystem) -> None:
    manager = create_file_system_session_manager(PATH, file_system=files)
    manager.append(ASKS)
    returned = manager.entries()

    manager.append(CALLS)

    assert list(returned) == [ASKS]


def test_the_file_may_be_named_by_a_string(files: FakeFileSystem) -> None:
    create_file_system_session_manager("sessions/session.jsonl", file_system=files).append(ASKS)

    assert list(files.files) == [PATH]


def test_an_entry_that_cannot_be_written_propagates_and_the_entries_are_as_they_were(
    files: FakeFileSystem,
) -> None:
    manager = create_file_system_session_manager(PATH, file_system=files)
    manager.append(ASKS)
    files.failing = OSError("disk full")

    with pytest.raises(OSError, match=r"^disk full$"):
        manager.append(CALLS)

    assert list(manager.entries()) == [ASKS]


def test_reading_a_line_that_is_not_json_raises(files: FakeFileSystem) -> None:
    files.files[PATH] = "not json\n"

    with pytest.raises(JSONDecodeError):
        create_file_system_session_manager(PATH, file_system=files).entries()


@pytest.mark.parametrize(
    "line, message",
    [
        ('{"type": "note", "text": "hi"}', r"^not a context entry: unknown type 'note'$"),
        (
            '{"type": "user", "content": [{"type": "video", "url": "x"}]}',
            r"^not a context entry: unknown part type 'video'$",
        ),
        ('{"type": "tool_result", "text": "hi"}', r"^not a context entry: missing 'tool_call_id'$"),
        ('["user"]', r"^not a context entry: \['user'\]$"),
    ],
)
def test_reading_a_line_that_is_not_an_entry_raises(
    line: str, message: str, files: FakeFileSystem
) -> None:
    files.files[PATH] = line + "\n"

    with pytest.raises(ValueError, match=message):
        create_file_system_session_manager(PATH, file_system=files).entries()
