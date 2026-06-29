"""Partial-JSON repair and streaming-tolerant JSON parsing.

A faithful copy of :mod:`otter_ai_chat_completions._json`: tool-call argument
fragments arrive truncated during streaming, so this tolerates incomplete and
slightly malformed input and always returns a ``dict``. Duplicated here so
:mod:`otter_ai_realtime` stays independent of the chat-completions package.
"""

from __future__ import annotations

import json
from typing import Any

_VALID_JSON_ESCAPES = frozenset('"\\/bfnrtu')


def _is_control_character(char: str) -> bool:
    return len(char) > 0 and 0x00 <= ord(char) <= 0x1F


def _escape_control_character(char: str) -> str:
    code = ord(char)
    return {
        0x08: "\\b",
        0x0C: "\\f",
        0x0A: "\\n",
        0x0D: "\\r",
        0x09: "\\t",
    }.get(code, f"\\u{code:04x}")


def repair_json(text: str) -> str:
    """Repair malformed JSON string literals (mirrors pi-ai's ``repairJson``)."""
    repaired: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue
        if char == '"':
            repaired.append(char)
            in_string = False
            index += 1
            continue
        if char == "\\":
            next_char = text[index + 1] if index + 1 < length else None
            if next_char is None:
                repaired.append("\\\\")
                index += 1
                continue
            if next_char == "u":
                digits = text[index + 2 : index + 6]
                if len(digits) == 4 and all(
                    c in "0123456789abcdefABCDEF" for c in digits
                ):
                    repaired.append("\\u" + digits)
                    index += 6
                    continue
            if next_char in _VALID_JSON_ESCAPES:
                repaired.append("\\" + next_char)
                index += 2
                continue
            repaired.append("\\\\")
            index += 1
            continue
        repaired.append(
            _escape_control_character(char) if _is_control_character(char) else char
        )
        index += 1
    return "".join(repaired)


def parse_json_with_repair(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = repair_json(text)
        if repaired != text:
            return json.loads(repaired)
        raise


def _close_partial_json(text: str) -> str:
    stack: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if stack and stack[-1] == char:
                stack.pop()
    suffix = '"' if in_string else ""
    suffix += "".join(reversed(stack))
    return text + suffix


def parse_streaming_json(text: str | None) -> dict[str, Any]:
    """Parse potentially-incomplete streaming JSON into a ``dict``.

    Always returns a ``dict`` (never raises): empty input → ``{}``; on hard
    failure → ``{}``. Tool-call arguments are always objects on the wire.
    """
    if not text or not text.strip():
        return {}
    try:
        result = parse_json_with_repair(text)
    except json.JSONDecodeError:
        try:
            result = json.loads(_close_partial_json(text))
        except json.JSONDecodeError:
            try:
                result = json.loads(repair_json(_close_partial_json(text)))
            except json.JSONDecodeError:
                return {}
    if isinstance(result, dict):
        return result
    return {}
