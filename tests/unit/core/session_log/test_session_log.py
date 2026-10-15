"""Behaviour of a session log, observed through the entries it returns and the text it keeps."""

import json
from json import JSONDecodeError

import pytest

from otter.core.domain.messages import (
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
from otter.core.session_log import NotAnEntry, SessionLog, SessionLogImpl

from .adapters import FakeSessionLogAdapter

ASKS = UserMessage((TextPart("What is in a.txt?"),))
CALLS = AssistantMessage((ToolCall("call-1", "read_file", {"path": "a.txt"}),))
RESULT = ToolResultMessage("call-1", "file contents")


def setup(port: FakeSessionLogAdapter) -> SessionLog:
    return SessionLogImpl(port)


@pytest.fixture
def port() -> FakeSessionLogAdapter:
    return FakeSessionLogAdapter()


def test_a_log_with_no_text_holds_no_entries(port: FakeSessionLogAdapter) -> None:
    assert list(setup(port).entries()) == []


def test_appended_entries_are_returned_in_the_order_they_were_appended(
    port: FakeSessionLogAdapter,
) -> None:
    log = setup(port)
    log.append(ASKS)
    log.append(CALLS)
    log.append(RESULT)

    assert list(log.entries()) == [ASKS, CALLS, RESULT]


def test_a_log_starts_out_with_the_entries_its_text_already_holds(
    port: FakeSessionLogAdapter,
) -> None:
    earlier = setup(port)
    earlier.append(ASKS)
    earlier.append(CALLS)

    log = setup(port)
    log.append(RESULT)

    assert list(log.entries()) == [ASKS, CALLS, RESULT]


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
        ToolResultMessage("call-1", "Buy milk.\nCall Zoë.\u2028The end."),
    ],
)
def test_an_entry_is_read_back_as_it_was_appended(
    entry: ContextEntry, port: FakeSessionLogAdapter
) -> None:
    setup(port).append(entry)

    assert list(setup(port).entries()) == [entry]


def test_each_entry_is_written_as_one_line_of_json(port: FakeSessionLogAdapter) -> None:
    log = setup(port)
    log.append(UserMessage((TextPart("What is in a.txt?"),)))
    log.append(
        AssistantMessage(
            (TextPart("Let me look."), ToolCall("call-1", "read_file", {"path": "a.txt"}))
        )
    )
    log.append(ToolResultMessage("call-1", "line one\nline two"))

    assert [json.loads(line) for line in port.text.split("\n") if line] == [
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


def test_entries_already_returned_are_unchanged_by_a_later_append(
    port: FakeSessionLogAdapter,
) -> None:
    log = setup(port)
    log.append(ASKS)
    returned = log.entries()

    log.append(CALLS)

    assert list(returned) == [ASKS]


def test_reading_a_line_that_is_not_json_raises() -> None:
    with pytest.raises(JSONDecodeError):
        setup(FakeSessionLogAdapter("not json\n")).entries()


@pytest.mark.parametrize(
    "line, message",
    [
        ('{"type": "note", "text": "hi"}', r"unknown entry type 'note'"),
        (
            '{"type": "user", "content": [{"type": "video", "url": "x"}]}',
            r"unknown user part type 'video'",
        ),
        (
            '{"type": "assistant", "content": [{"type": "image", "data": "x"}]}',
            r"unknown assistant part type 'image'",
        ),
        (
            '{"type": "user", "content": [{"type": "audio", "data": "x", "format": "ogg"}]}',
            r"unknown audio format 'ogg'",
        ),
        ('{"type": "tool_result", "text": "hi"}', r"missing the text field 'tool_call_id'"),
        ('{"type": "user"}', r"missing the list field 'content'"),
        (
            '{"type": "assistant", "content": [{"type": "tool_call", "id": "1", "name": "f"}]}',
            r"arguments are not an object",
        ),
        ('["user"]', r"not an object: \['user'\]"),
    ],
)
def test_reading_a_line_that_is_not_an_entry_raises(line: str, message: str) -> None:
    with pytest.raises(NotAnEntry, match=message):
        setup(FakeSessionLogAdapter(line + "\n")).entries()
