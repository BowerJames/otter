"""Behavioural tests for the realtime connection seam, faking the WS."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _realtime_helpers import (
    FakeRealtimeWS,
    content_part_added,
    make_model,
    make_options,
    response_completed,
    response_created,
    simple_context,
    text_frame_delta,
    text_frame_done,
    user_text,
)

import otter_ai_realtime._transport as transport
from otter_ai_core.model_connection import (
    ConnectionErrorEvent,
    ResponseDoneEvent,
)
from otter_ai_realtime import create_realtime_model_connection


async def _drain(conn: Any) -> list[Any]:
    out: list[Any] = []
    async for event in conn:
        out.append(event)
    return out


def _install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeRealtimeWS) -> None:
    async def _connect(model: Any, api_key: str) -> FakeRealtimeWS:
        return fake

    monkeypatch.setattr(transport, "connect_ws", _connect)


async def test_happy_path_emits_session_update_replay_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    ctx = simple_context(user_text("seed hello"), system_prompt="be helpful")
    conn = create_realtime_model_connection(make_options(), ctx)

    # Let the backend open + send session.update + replay, then drive a response.
    fake.feed(
        response_created(),
        content_part_added(),
        text_frame_delta("Hi "),
        text_frame_delta("there"),
        text_frame_done("Hi there"),
        response_completed(),
    )
    fake.close_inbound()

    events = await _drain(conn)

    # Opening frames landed on the wire in order.
    types_sent = [f["type"] for f in fake.sent]
    assert types_sent[0] == "session.update"
    assert fake.sent[0]["session"]["instructions"] == "be helpful"
    assert types_sent[1] == "conversation.item.create"
    assert fake.sent[1]["item"]["content"] == [
        {"type": "input_text", "text": "seed hello"}
    ]

    # Inbound events are the otter ServerEvent sequence.
    event_types = [type(e).__name__ for e in events]
    assert event_types[:3] == [
        "ResponseStartedEvent",
        "ResponseTextStartEvent",
        "ResponseTextUpdatedEvent",
    ]
    assert event_types[-1] == "ResponseDoneEvent"
    assert events[-1].partial.content[0].text == "Hi there"


async def test_connect_failure_emits_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _connect(model: Any, api_key: str) -> Any:  # noqa: ARG001
        raise OSError("refused")

    monkeypatch.setattr(transport, "connect_ws", _connect)
    conn = create_realtime_model_connection(make_options(), simple_context())
    events = await _drain(conn)

    assert len(events) == 1
    assert isinstance(events[0], ConnectionErrorEvent)
    assert events[0].reason == "connect_failed"
    assert "refused" in events[0].message


async def test_missing_api_key_emits_connection_error() -> None:
    options = make_options(model=make_model(api_key=None))
    conn = create_realtime_model_connection(options, simple_context())
    events = await _drain(conn)
    assert len(events) == 1
    assert isinstance(events[0], ConnectionErrorEvent)
    assert events[0].reason == "connect_failed"


async def test_mid_session_transport_error_emits_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from websockets.exceptions import ConnectionClosedError

    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    conn = create_realtime_model_connection(make_options(), simple_context())
    await asyncio.sleep(0)  # let the backend open + send session.update

    # Simulate a transport error mid-stream.
    fake.raise_on_recv = ConnectionClosedError(None, None)
    events = await _drain(conn)

    assert any(isinstance(e, ConnectionErrorEvent) for e in events)
    assert all(
        not isinstance(e, (ResponseDoneEvent,)) for e in events
    )  # no clean response completion


async def test_abort_tears_down_gracefully_no_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    abort = asyncio.Event()
    conn = create_realtime_model_connection(make_options(), simple_context(), abort)
    await asyncio.sleep(0)

    abort.set()
    events = await _drain(conn)

    assert not any(isinstance(e, ConnectionErrorEvent) for e in events)
    assert fake.closed


async def test_close_ends_connection_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    conn = create_realtime_model_connection(make_options(), simple_context())
    await asyncio.sleep(0)

    conn.close()
    events = await _drain(conn)

    assert not any(isinstance(e, ConnectionErrorEvent) for e in events)


async def test_response_abort_client_event_sends_cancel_and_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from otter_ai_core.model_connection import AbortResponseEvent

    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    conn = create_realtime_model_connection(make_options(), simple_context())
    await asyncio.sleep(0)

    # Push a per-response abort.
    conn.send(AbortResponseEvent(type="response.abort"))

    # Give the pump time to drain and send the cancel frame.
    for _ in range(10):
        await asyncio.sleep(0)
    # The connection stays open (not closed by a per-response abort).
    assert not fake.closed
    assert any(f.get("type") == "response.cancel" for f in fake.sent)

    conn.close()
    await _drain(conn)


async def test_on_connect_observer_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRealtimeWS()
    _install_fake(monkeypatch, fake)

    seen: list[str] = []

    async def on_connect(event: Any) -> None:
        seen.append(event.url)

    options = make_options()
    options.hooks.on_connect = on_connect
    conn = create_realtime_model_connection(options, simple_context())
    await asyncio.sleep(0)
    conn.close()
    await _drain(conn)

    assert seen and "realtime" in seen[0]
