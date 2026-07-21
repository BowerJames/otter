"""Generic typed bus: descriptor-keyed fan-out."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pytest

from otter_ai_core.bus import Bus, BusEvent


@dataclass(slots=True)
class Item:
    value: str


@dataclass(slots=True)
class Partial:
    value: str


#: Two independent events with distinct payload types.
ITEM_DONE: BusEvent[Item] = BusEvent("item.done")
PARTIAL_UPDATED: BusEvent[Partial] = BusEvent("partial.updated")

#: A second event that happens to share Item's payload type, to exercise
#: independent fan-out of two events carrying the same payload type.
ITEM_STARTED: BusEvent[Item] = BusEvent("item.started")


def _bus() -> Bus:
    return Bus()


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

    bus.subscribe(ITEM_DONE, handler_a)
    bus.subscribe(ITEM_DONE, handler_b)
    bus.publish(ITEM_DONE, Item(value="complete"))

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

    bus.subscribe(ITEM_DONE, on_item)
    bus.subscribe(PARTIAL_UPDATED, on_partial)
    bus.publish(ITEM_DONE, Item(value="an item"))
    bus.publish(PARTIAL_UPDATED, Partial(value="a partial"))

    await asyncio.wait_for(done.wait(), 1)
    assert items == ["an item"]
    assert partials == ["a partial"]
    await bus.aclose()


async def test_bus_subscribe_returns_idempotent_unsubscribe() -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    unsubscribe = bus.subscribe(ITEM_DONE, handler)

    bus.publish(ITEM_DONE, Item(value="first"))
    await asyncio.wait_for(done.wait(), 1)
    assert seen == ["first"]

    unsubscribe()
    unsubscribe()  # idempotent — no error

    published_second = asyncio.Event()

    async def after_unsub(_payload: Item) -> None:
        published_second.set()

    bus.subscribe(ITEM_DONE, after_unsub)
    bus.publish(ITEM_DONE, Item(value="second"))
    # The unsubscribed handler must not fire; only the still-subscribed one.
    await asyncio.wait_for(published_second.wait(), 1)
    assert seen == ["first"]
    await bus.aclose()


async def test_bus_publish_with_no_subscribers_is_a_noop() -> None:
    bus = _bus()
    # No subscribers — publishing must not raise and the worker drains cleanly.
    bus.publish(ITEM_DONE, Item(value="nobody listening"))
    await bus.aclose()


async def test_bus_drains_already_published_events_before_aclose() -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(payload: Item) -> None:
        seen.append(payload.value)
        done.set()

    bus.subscribe(ITEM_DONE, handler)
    bus.publish(ITEM_DONE, Item(value="queued"))
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
    bus.subscribe(ITEM_DONE, boom)
    bus.subscribe(ITEM_DONE, sibling)

    with caplog.at_level(logging.ERROR, logger="otter_ai_core.bus"):
        bus.publish(ITEM_DONE, Item(value="survives"))

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

    bus.subscribe(ITEM_DONE, on_done)
    bus.subscribe(ITEM_STARTED, on_started)
    bus.publish(ITEM_STARTED, Item(value="began"))
    bus.publish(ITEM_DONE, Item(value="finished"))

    await asyncio.wait_for(done.wait(), 1)
    assert started_events == ["began"]
    assert done_events == ["finished"]
    await bus.aclose()


async def test_bus_aclose_is_idempotent() -> None:
    bus = _bus()
    await bus.aclose()
    await bus.aclose()  # no error
    assert bus._task.done()


async def test_bus_descriptor_hashes_and_compares_by_name() -> None:
    """Two descriptors built from the same name are the same registry key."""
    assert BusEvent("item.done") == BusEvent("item.done")
    assert hash(BusEvent("item.done")) == hash(BusEvent("item.done"))
    assert BusEvent("item.done") != BusEvent("item.started")
