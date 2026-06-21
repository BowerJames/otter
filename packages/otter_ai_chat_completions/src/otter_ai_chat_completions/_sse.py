"""Minimal Server-Sent Events line parser over an ``httpx`` streaming response.

The Chat Completions streaming endpoint responds with ``text/event-stream``.
Each SSE event is a block of lines terminated by a blank line; ``data:`` lines
within an event are concatenated. We ignore the other SSE fields (``event:``,
``id:``, ``retry:``) and comment lines (``: …``) — Chat Completions uses only
``data:``. The terminal ``data: [DONE]`` sentinel is yielded verbatim so the
caller can stop iterating.

This is a faithful Python/``asyncio`` port of the framing logic pi-ai gets for
free from the ``openai`` SDK; we hand-write it here because
``otter_ai_chat_completions`` speaks the wire format directly via ``httpx``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx


async def iter_sse_events(response: httpx.Response) -> AsyncIterator[str]:
    """Yield joined ``data:`` payloads from an SSE response stream.

    Events are buffered per SSE block (a blank line dispatches them). Multi-line
    ``data:`` fields within one event are joined with ``\\n`` per the spec. Heartbeat
    comment lines and non-``data`` fields are ignored. The final ``[DONE]``
    sentinel is yielded as a normal payload (callers check for it).
    """
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        # ``aiter_lines`` strips the trailing newline; an empty string is the
        # SSE event delimiter.
        if raw_line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        # SSE comments / heartbeats.
        if raw_line.startswith(":"):
            continue
        if raw_line.startswith("data:"):
            payload = raw_line[5:]
            if payload.startswith(" "):
                payload = payload[1:]
            data_lines.append(payload)
            continue
        # Other SSE fields (``event:``, ``id:``, ``retry:``) are unused here.
    # Flush a trailing event if the stream did not end on a blank line.
    if data_lines:
        yield "\n".join(data_lines)
