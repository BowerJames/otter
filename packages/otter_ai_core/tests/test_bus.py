"""Generic event bus: name-keyed fan-out conforming to the EventRunner protocol."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from types import NoneType
from typing import Self

import pytest

from otter_ai_core.interfaces.capabilities import Channel
from otter_ai_core.runtime.bus import Bus


@dataclass(slots=True)
class Item:
    value: str


@dataclass(slots=True)
class Partial:
    value: str


#: Three independent event names; two share Item's payload type to exercise
#: independent fan-out of two events carrying the same payload type.
ITEM_DONE = "item.done"
PARTIAL_UPDATED = "partial.updated"
ITEM_STARTED = "item.started"


class _SpyChannel[TEvent](Channel[TEvent]):
    """A minimal Channel test double: records pushes and end() for assertions."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[TEvent | None] = asyncio.Queue()
        self.pushed: list[TEvent] = []
        self.ended: bool = False

    def push(self, event: TEvent) -> None:
        self.pushed.append(event)
        self._queue.put_nowait(event)

    def end(self) -> None:
        if self.ended:
            return
        self.ended = True
        self._queue.put_nowait(None)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


def _bus() -> Bus:
    # A Bus starts with no registered event types; every test that emits or
    # subscribes must register the event names + their concrete payload types.
    # The drain task is NOT started here — it starts on __aenter__.
    bus = Bus()
    bus.register(ITEM_DONE, Item, NoneType)
    bus.register(PARTIAL_UPDATED, Partial, NoneType)
    bus.register(ITEM_STARTED, Item, NoneType)
    return bus


async def test_bus_fans_out_to_every_subscriber_of_an_event() -> None:
    seen_a: list[str] = []
    seen_b: list[str] = []
    done = asyncio.Event()

    async def handler_a(payload: Item) -> None:
        seen_a.append(payload.value)

    async def handler_b(payload: Item) -> None:
        seen_b.append(payload.value)
        done.set()

    async with _bus() as bus:
        bus.on(ITEM_DONE, handler_a)
        bus.on(ITEM_DONE, handler_b)
        await bus.emit(ITEM_DONE, Item(value="complete"))

        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert seen_a == ["complete"]
    assert seen_b == ["complete"]


async def test_bus_dispatches_each_descriptor_to_only_its_subscribers() -> None:
    items: list[str] = []
    partials: list[str] = []
    done = asyncio.Event()

    async def on_item(payload: Item) -> None:
        items.append(payload.value)

    async def on_partial(payload: Partial) -> None:
        partials.append(payload.value)
        done.set()

    async with _bus() as bus:
        bus.on(ITEM_DONE, on_item)
        bus.on(PARTIAL_UPDATED, on_partial)
        await bus.emit(ITEM_DONE, Item(value="an item"))
        await bus.emit(PARTIAL_UPDATED, Partial(value="a partial"))

        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert items == ["an item"]
    assert partials == ["a partial"]


async def test_bus_on_returns_idempotent_unsubscribe() -> None:
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    async with _bus() as bus:
        unsubscribe = bus.on(ITEM_DONE, handler)

        await bus.emit(ITEM_DONE, Item(value="first"))
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["first"]

        unsubscribe()
        unsubscribe()  # idempotent — no error

        published_second = asyncio.Event()

        async def after_unsub(_payload: Item) -> None:
            published_second.set()

        bus.on(ITEM_DONE, after_unsub)
        await bus.emit(ITEM_DONE, Item(value="second"))
        # The unsubscribed handler must not fire; only the still-subscribed one.
        await asyncio.wait_for(published_second.wait(), 1)
        bus.end()
    assert seen == ["first"]


async def test_bus_emit_with_no_subscribers_is_a_noop() -> None:
    async with _bus() as bus:
        # No subscribers — emitting must not raise and the worker drains cleanly.
        await bus.emit(ITEM_DONE, Item(value="nobody listening"))
        bus.end()


async def test_bus_drains_already_emitted_events_before_exit() -> None:
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    async with _bus() as bus:
        bus.on(ITEM_DONE, handler)
        await bus.emit(ITEM_DONE, Item(value="queued"))
        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert seen == ["queued"]


async def test_bus_isolates_and_logs_a_handler_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising handler is isolated + logged; sibling handlers still run."""
    sibling_ran: list[str] = []
    done = asyncio.Event()

    async def boom(_payload: Item) -> None:
        raise RuntimeError("handler exploded")

    async def sibling(payload: Item) -> None:
        sibling_ran.append(payload.value)
        done.set()

    async with _bus() as bus:
        # Subscribe the raising handler first, then the sibling; both must be
        # attempted and the sibling must still fire after the boom.
        bus.on(ITEM_DONE, boom)
        bus.on(ITEM_DONE, sibling)

        with caplog.at_level(logging.ERROR, logger="otter_ai_core.runtime.bus"):
            await bus.emit(ITEM_DONE, Item(value="survives"))

        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert sibling_ran == ["survives"]
    assert any("bus handler raised" in record.getMessage() for record in caplog.records)


async def test_bus_two_events_sharing_a_payload_type_route_independently() -> None:
    """Two events with the same payload type are distinct routing keys."""
    done_events: list[str] = []
    started_events: list[str] = []
    done = asyncio.Event()

    async def on_done(payload: Item) -> None:
        done_events.append(payload.value)
        done.set()

    async def on_started(payload: Item) -> None:
        started_events.append(payload.value)

    async with _bus() as bus:
        bus.on(ITEM_DONE, on_done)
        bus.on(ITEM_STARTED, on_started)
        await bus.emit(ITEM_STARTED, Item(value="began"))
        await bus.emit(ITEM_DONE, Item(value="finished"))

        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert started_events == ["began"]
    assert done_events == ["finished"]


async def test_bus_drain_starts_on_enter_and_drains_backlog() -> None:
    # Events emitted before __aenter__ are buffered on the channel and only
    # dispatched once the drain task starts on enter (FIFO preserved).
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    bus = _bus()
    bus.on(ITEM_DONE, handler)
    await bus.emit(ITEM_DONE, Item(value="queued-before-enter"))
    await asyncio.sleep(0.02)  # drain is not running yet: nothing dispatched
    assert seen == []
    async with bus:
        await asyncio.wait_for(done.wait(), 1)
        bus.end()
    assert seen == ["queued-before-enter"]


async def test_bus_aexit_is_idempotent() -> None:
    # A bus that was never entered has no lifecycle task; __aexit__ is a no-op.
    bus = _bus()
    await bus.__aexit__(None, None, None)
    # An entered + ended bus exits cleanly, and a second __aexit__ is a no-op
    # (the lifecycle task is already done).
    async with bus:
        bus.end()
    await bus.__aexit__(None, None, None)


async def test_bus_aexit_force_cancels_a_wedged_handler() -> None:
    # A handler that never returns wedges the drain. __aexit__ must force-cancel
    # it within the shutdown deadline rather than hanging forever. Unlike the
    # old aclose, teardown always exits cleanly (no exception propagates).
    started = asyncio.Event()

    async def wedged(_payload: Item) -> None:
        started.set()
        await asyncio.Event().wait()  # never set -> hangs

    bus = _bus()
    bus._shutdown_timeout = 0.1
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with bus:
        bus.on(ITEM_DONE, wedged)
        await bus.emit(ITEM_DONE, Item(value="x"))
        await asyncio.wait_for(started.wait(), 1)
    assert loop.time() - start < 2.0  # force-cancelled, did not hang on the 5s default


def test_bus_emit_is_a_coroutine_function() -> None:
    # Emitter conformance: ``emit`` must be async to satisfy EventRunner.
    assert inspect.iscoroutinefunction(Bus.emit)


async def test_bus_register_rejects_a_non_none_response_type() -> None:
    bus = Bus()
    with pytest.raises(ValueError):
        bus.register(ITEM_DONE, Item, object)


async def test_bus_register_rejects_a_duplicate_hook_name() -> None:
    bus = Bus()
    bus.register(ITEM_DONE, Item, NoneType)
    # Even an identical re-registration is rejected, to keep ownership explicit.
    with pytest.raises(ValueError):
        bus.register(ITEM_DONE, Item, NoneType)


async def test_bus_on_rejects_an_unregistered_type() -> None:
    bus = Bus()  # nothing registered

    async def handler(_payload: object) -> None:
        pass

    with pytest.raises(ValueError):
        bus.on("never.registered", handler)


async def test_bus_emit_rejects_an_unregistered_type() -> None:
    bus = Bus()  # nothing registered
    with pytest.raises(ValueError):
        await bus.emit("never.registered", Item(value="x"))


async def test_bus_emit_rejects_a_wrong_payload_type() -> None:
    # ITEM_DONE is registered for Item; a Partial payload must be rejected.
    bus = _bus()
    with pytest.raises(ValueError):
        await bus.emit(ITEM_DONE, Partial(value="wrong"))


async def test_bus_drives_an_injected_custom_channel() -> None:
    # The Bus is programmed to the Channel interface: it must drive ANY injected
    # Channel, not just DefaultChannel. The spy records every push and end() so
    # we can assert the Bus routes emits through the channel, dispatches from
    # it, and tears it down via end() on exit.
    spy: _SpyChannel[tuple[str, object]] = _SpyChannel()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    async with Bus(channel_factory=lambda: spy) as bus:
        bus.register(ITEM_DONE, Item, NoneType)
        bus.on(ITEM_DONE, handler)
        await bus.emit(ITEM_DONE, Item(value="routed"))
        await asyncio.wait_for(done.wait(), 1)
        bus.end()

    assert spy.pushed == [("item.done", Item(value="routed"))]
    assert spy.ended is True
    assert seen == ["routed"]


async def test_bus_is_awaitable_to_join_the_lifecycle() -> None:
    # A TaskRunner is awaitable: ``await bus`` joins the drain lifecycle. Here
    # the bus ends (via end()) so the await resolves promptly.
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    async with _bus() as bus:
        bus.on(ITEM_DONE, handler)
        await bus.emit(ITEM_DONE, Item(value="joined"))
        await asyncio.wait_for(done.wait(), 1)
        bus.end()
        await bus  # join: resolves once the drain task completes
    assert seen == ["joined"]
