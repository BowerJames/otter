"""Partial-JSON repair + streaming-tolerant parsing."""

from __future__ import annotations

import pytest

from otter_ai_chat_completions._json import (
    parse_json_with_repair,
    parse_streaming_json,
    repair_json,
)


def test_repair_json_doubles_invalid_escape_backslashes() -> None:
    # ``\\x`` is not a valid JSON escape; repair doubles the backslash.
    assert repair_json('{"a": "x\\x"}') == '{"a": "x\\\\x"}'


def test_repair_json_keeps_valid_escapes_intact() -> None:
    assert repair_json('{"a": "line\\nbreak"}') == '{"a": "line\\nbreak"}'


def test_repair_json_escapes_raw_control_chars_in_strings() -> None:
    # A raw tab inside a string must be escaped (JSON forbids raw control chars).
    assert repair_json('{"a": "x\ty"}') == '{"a": "x\\ty"}'


def test_parse_json_with_repair_succeeds_after_repair() -> None:
    assert parse_json_with_repair('{"a": "x\\x"}') == {"a": "x\\x"}


def test_parse_json_with_repair_reraises_unrepairable() -> None:
    import json

    with pytest.raises(json.JSONDecodeError):
        parse_json_with_repair("{not json")


def test_parse_streaming_json_empty_returns_empty_dict() -> None:
    assert parse_streaming_json("") == {}
    assert parse_streaming_json(None) == {}
    assert parse_streaming_json("   ") == {}


def test_parse_streaming_json_complete_object() -> None:
    assert parse_streaming_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_parse_streaming_json_truncated_string_value() -> None:
    assert parse_streaming_json('{"a": "hel') == {"a": "hel"}


def test_parse_streaming_json_truncated_nested_object() -> None:
    assert parse_streaming_json('{"name": "add", "args": {"x": 1') == {
        "name": "add",
        "args": {"x": 1},
    }


def test_parse_streaming_json_non_object_top_level_returns_empty() -> None:
    # Tool-call arguments are always objects on the wire; coerce scalars to {}.
    assert parse_streaming_json("[1, 2, 3") == {}
    assert parse_streaming_json('"str') == {}


def test_parse_streaming_json_hard_failure_returns_empty() -> None:
    # A dangling colon with no value cannot be salvaged; fall back to {}.
    assert parse_streaming_json('{"a":') == {}
