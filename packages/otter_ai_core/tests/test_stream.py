"""Generic abortable stream runtime: iteration, abort, single-pass, pairing."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields

import pytest

from otter_ai_core import (
    AssistantMessage,
    StreamBackend,
    StreamClient,
    StreamPair,
    Usage,
    UsageCost,
    create_stream,
)
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantMessageStreamBackend,
    AssistantMessageStreamClient,
    AssistantStartEvent,
)


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[],
        api="chat-completions",
        provider="openai",
        model="gpt-test",
        usage=_usage(),
        stop_reason="stop",
        timestamp=0,
    )


# --------------------------------------------------------------------------- #
# create_stream: pairing + shared abort signal
# --------------------------------------------------------------------------- #


def test_create_stream_returns_stream_pair_with_named_fields() -> None:
    """``create_stream()`` returns a frozen ``StreamPair`` (client, backend)."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()

    assert isinstance(pair.client, StreamClient)
    assert isinstance(pair.backend, StreamBackend)
    with pytest.raises(FrozenInstanceError):
        pair.client = pair.client  # type: ignore[misc]
    assert {f.name for f in fields(StreamPair)} == {"client", "backend"}


def test_client_and_backend_share_one_abort_signal() -> None:
    """The abort signal set by the client is the one the backend observes."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()

    assert not pair.backend.abort_signal.is_set()
    pair.client.abort()
    assert pair.backend.abort_signal.is_set()

    # If the two ends did not share one event, the backend's signal would stay
    # unset when the client aborts — so observing it set *is* the sharing proof.


def test_abort_is_idempotent() -> None:
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    pair.client.abort()
    pair.client.abort()  # second set is a no-op, not an error
    assert pair.backend.abort_signal.is_set()


def test_create_stream_distinct_pairs_have_distinct_signals() -> None:
    a: StreamPair[AssistantMessageEvent] = create_stream()
    b: StreamPair[AssistantMessageEvent] = create_stream()
    a.client.abort()
    assert a.backend.abort_signal.is_set()
    assert not b.backend.abort_signal.is_set()


# --------------------------------------------------------------------------- #
# StreamBackend: push/end delegate to the channel writer
# --------------------------------------------------------------------------- #


async def test_backend_push_then_end_drives_client_iteration() -> None:
    """Events pushed on the backend are read by iterating the client."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    start = AssistantStartEvent(role="assistant", type="start", partial=_message())
    done = AssistantDoneEvent(
        role="assistant", type="done", reason="stop", message=_message()
    )

    pair.backend.push(start)
    pair.backend.push(done)
    pair.backend.end()

    seen: list[AssistantMessageEvent] = [event async for event in pair.client]
    assert seen == [start, done]


async def test_backend_end_is_idempotent_and_push_after_end_is_noop() -> None:
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    start = AssistantStartEvent(role="assistant", type="start", partial=_message())

    pair.backend.push(start)
    pair.backend.end()
    pair.backend.push(
        AssistantDoneEvent(
            role="assistant", type="done", reason="stop", message=_message()
        )
    )
    pair.backend.end()  # idempotent

    seen = [event async for event in pair.client]
    assert len(seen) == 1
    assert seen[0] is start


# --------------------------------------------------------------------------- #
# StreamClient: iteration delegates to the reader (single-pass guard honored)
# --------------------------------------------------------------------------- #


async def test_second_iteration_raises_via_delegated_guard() -> None:
    """A second ``async for`` on the client raises (single-pass via reader)."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    pair.backend.push(
        AssistantStartEvent(role="assistant", type="start", partial=_message())
    )
    pair.backend.end()

    async for _event in pair.client:
        pass
    with pytest.raises(RuntimeError, match="single-consumer"):
        async for _event in pair.client:
            pass


async def test_abort_signal_can_be_awaited_by_producer() -> None:
    """A producer task can ``await backend.abort_signal.wait()`` and resolve."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()

    async def producer() -> None:
        await pair.backend.abort_signal.wait()
        pair.backend.push(
            AssistantDoneEvent(
                role="assistant", type="done", reason="stop", message=_message()
            )
        )
        pair.backend.end()

    task = asyncio.create_task(producer())
    await asyncio.sleep(0)  # let the producer park on the wait
    assert not task.done()
    pair.client.abort()
    await task

    seen = [event async for event in pair.client]
    assert len(seen) == 1
    assert isinstance(seen[0], AssistantDoneEvent)


# --------------------------------------------------------------------------- #
# Typed aliases specialize the generic runtime
# --------------------------------------------------------------------------- #


def test_assistant_aliases_are_specializations_of_stream() -> None:
    """The assistant aliases fix TEvent but are the generic stream handles."""
    assert AssistantMessageStreamClient.__origin__ is StreamClient  # type: ignore[attr-defined]
    assert AssistantMessageStreamBackend.__origin__ is StreamBackend  # type: ignore[attr-defined]


def test_assistant_alias_unpack_is_usable_via_create_stream() -> None:
    """The assistant alias is usable via an annotated ``create_stream()`` pair."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    client: AssistantMessageStreamClient = pair.client
    backend: AssistantMessageStreamBackend = pair.backend
    assert isinstance(client, StreamClient)
    assert isinstance(backend, StreamBackend)


def test_stream_client_delegates_iteration_and_does_not_own_a_writer() -> None:
    """The client iterates (delegated) and the backend owns the push surface."""
    pair: StreamPair[AssistantMessageEvent] = create_stream()
    # The client is an async iterable but exposes no push/end surface; the
    # backend is the only side that pushes.
    assert hasattr(pair.client, "__aiter__")
    assert not hasattr(pair.client, "push")
    assert hasattr(pair.backend, "push")
    assert hasattr(pair.backend, "end")
