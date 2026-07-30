"""Generic event bus: name-keyed fan-out conforming to the EventRunner protocol."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from types import NoneType

import pytest

from otter_ai_core.bus import Bus


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


def _bus() -> Bus:
    # A Bus starts with no registered event types; every test that emits or
    # subscribes must register the event names + their concrete payload types.
    bus = Bus()
    bus.register(ITEM_DONE, Item, NoneType)
    bus.register(PARTIAL_UPDATED, Partial, NoneType)
    bus.register(ITEM_STARTED, Item, NoneType)
    return bus


async def test_bus_fans_out_to_every_subscriber_of_an_event() -> None:
    bus = _bus()
    seen_a: list[str] = []
    seen_b: list[str] = []
    done = asyncio.Event()

    async def handler_a(payload: Item) -> None:
        seen_a.append(payload.value)

    async def handler_b(payload: Item) -> None:
        seen_b.append(payload.value)
        done.set()

    bus.on(ITEM_DONE, handler_a)
    bus.on(ITEM_DONE, handler_b)
    await bus.emit(ITEM_DONE, Item(value="complete"))

    await asyncio.wait_for(done.wait(), 1)
    assert seen_a == ["complete"]
    assert seen_b == ["complete"]
    await bus.aclose()


async def test_bus_dispatches_each_descriptor_to_only_its_subscribers() -> None:
    bus = _bus()
    items: list[str] = []
    partials: list[str] = []
    done = asyncio.Event()

    async def on_item(payload: Item) -> None:
        items.append(payload.value)

    async def on_partial(payload: Partial) -> None:
        partials.append(payload.value)
        done.set()

    bus.on(ITEM_DONE, on_item)
    bus.on(PARTIAL_UPDATED, on_partial)
    await bus.emit(ITEM_DONE, Item(value="an item"))
    await bus.emit(PARTIAL_UPDATED, Partial(value="a partial"))

    await asyncio.wait_for(done.wait(), 1)
    assert items == ["an item"]
    assert partials == ["a partial"]
    await bus.aclose()


async def test_bus_on_returns_idempotent_unsubscribe() -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

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
    assert seen == ["first"]
    await bus.aclose()


async def test_bus_emit_with_no_subscribers_is_a_noop() -> None:
    bus = _bus()
    # No subscribers — emitting must not raise and the worker drains cleanly.
    await bus.emit(ITEM_DONE, Item(value="nobody listening"))
    await bus.aclose()


async def test_bus_drains_already_emitted_events_before_aclose() -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    bus.on(ITEM_DONE, handler)
    await bus.emit(ITEM_DONE, Item(value="queued"))
    await asyncio.wait_for(done.wait(), 1)
    assert seen == ["queued"]
    await bus.aclose()


async def test_bus_isolates_and_logs_a_handler_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising handler is isolated + logged; sibling handlers still run."""
    bus = _bus()
    sibling_ran: list[str] = []
    done = asyncio.Event()

    async def boom(_payload: Item) -> None:
        raise RuntimeError("handler exploded")

    async def sibling(payload: Item) -> None:
        sibling_ran.append(payload.value)
        done.set()

    # Subscribe the raising handler first, then the sibling; both must be
    # attempted and the sibling must still fire after the boom.
    bus.on(ITEM_DONE, boom)
    bus.on(ITEM_DONE, sibling)

    with caplog.at_level(logging.ERROR, logger="otter_ai_core.bus"):
        await bus.emit(ITEM_DONE, Item(value="survives"))

    await asyncio.wait_for(done.wait(), 1)
    assert sibling_ran == ["survives"]
    assert any("bus handler raised" in record.getMessage() for record in caplog.records)
    await bus.aclose()


async def test_bus_two_events_sharing_a_payload_type_route_independently() -> None:
    """Two events with the same payload type are distinct routing keys."""
    bus = _bus()
    done_events: list[str] = []
    started_events: list[str] = []
    done = asyncio.Event()

    async def on_done(payload: Item) -> None:
        done_events.append(payload.value)
        done.set()

    async def on_started(payload: Item) -> None:
        started_events.append(payload.value)

    bus.on(ITEM_DONE, on_done)
    bus.on(ITEM_STARTED, on_started)
    await bus.emit(ITEM_STARTED, Item(value="began"))
    await bus.emit(ITEM_DONE, Item(value="finished"))

    await asyncio.wait_for(done.wait(), 1)
    assert started_events == ["began"]
    assert done_events == ["finished"]
    await bus.aclose()


async def test_bus_aclose_is_idempotent() -> None:
    bus = _bus()
    await bus.aclose()
    await bus.aclose()  # no error
    assert bus._task.done()


def test_bus_emit_is_a_coroutine_function() -> None:
    # Emitter conformance: ``emit`` must be async to satisfy EventRunner.
    assert inspect.iscoroutinefunction(Bus.emit)


async def test_bus_register_rejects_a_non_none_response_type() -> None:
    bus = Bus()
    with pytest.raises(ValueError):
        bus.register(ITEM_DONE, Item, object)
    await bus.aclose()


async def test_bus_register_rejects_a_duplicate_hook_name() -> None:
    bus = Bus()
    bus.register(ITEM_DONE, Item, NoneType)
    # Even an identical re-registration is rejected, to keep ownership explicit.
    with pytest.raises(ValueError):
        bus.register(ITEM_DONE, Item, NoneType)
    await bus.aclose()


async def test_bus_on_rejects_an_unregistered_type() -> None:
    bus = Bus()  # nothing registered

    async def handler(_payload: object) -> None:
        pass

    with pytest.raises(ValueError):
        bus.on("never.registered", handler)
    await bus.aclose()


async def test_bus_emit_rejects_an_unregistered_type() -> None:
    bus = Bus()  # nothing registered
    with pytest.raises(ValueError):
        await bus.emit("never.registered", Item(value="x"))
    await bus.aclose()


async def test_bus_emit_rejects_a_wrong_payload_type() -> None:
    bus = _bus()
    # ITEM_DONE is registered for Item; a Partial payload must be rejected.
    with pytest.raises(ValueError):
        await bus.emit(ITEM_DONE, Partial(value="wrong"))
    await bus.aclose()
