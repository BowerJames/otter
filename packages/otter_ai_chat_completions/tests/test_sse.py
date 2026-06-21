"""SSE event framing over an ``httpx`` streaming response."""

from __future__ import annotations

import httpx

from otter_ai_chat_completions._sse import iter_sse_events


async def _events(content: str) -> list[str]:
    response = httpx.Response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        content=content.encode("utf-8"),
    )
    return [payload async for payload in iter_sse_events(response)]


async def test_single_data_event() -> None:
    content = 'data: {"a":1}\n\n'
    assert await _events(content) == ['{"a":1}']


async def test_multiple_data_events() -> None:
    content = 'data: {"a":1}\n\ndata: {"b":2}\n\n'
    assert await _events(content) == ['{"a":1}', '{"b":2}']


async def test_multiline_data_joined_with_newline() -> None:
    # SSE spec: consecutive ``data:`` lines are joined with "\n".
    content = "data: line1\ndata: line2\n\n"
    assert await _events(content) == ["line1\nline2"]


async def test_done_sentinel_yielded_verbatim() -> None:
    content = 'data: {"a":1}\n\ndata: [DONE]\n\n'
    assert await _events(content) == ['{"a":1}', "[DONE]"]


async def test_comment_lines_ignored() -> None:
    content = ': heartbeat\n\ndata: {"a":1}\n\n'
    assert await _events(content) == ['{"a":1}']


async def test_non_data_fields_ignored() -> None:
    content = 'event: delta\ndata: {"a":1}\nid: 42\n\n'
    assert await _events(content) == ['{"a":1}']


async def test_data_with_leading_space_stripped() -> None:
    assert await _events('data: {"a":1}\n\n') == ['{"a":1}']


async def test_trailing_event_without_blank_line_flushed() -> None:
    content = 'data: {"a":1}\n\n'  # ends on blank line (standard)
    assert await _events(content) == ['{"a":1}']
    # And the unflushed case (no trailing blank line):
    assert await _events('data: {"a":1}') == ['{"a":1}']
