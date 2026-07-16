"""Generic typed bus: structural events and discriminator safety."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import pytest

from otter_ai_core.bus import Bus


class SampleEventType(StrEnum):
    ITEM = "item"
    PARTIAL = "partial"


@dataclass(slots=True)
class ItemEvent:
    item: str
    type: Literal[SampleEventType.ITEM] = SampleEventType.ITEM


@dataclass(slots=True)
class PartialEvent:
    partial: str
    type: Literal[SampleEventType.PARTIAL] = SampleEventType.PARTIAL


type SampleEvent = ItemEvent | PartialEvent
type SampleBus = Bus[SampleEventType, SampleEvent]


class ForeignEventType(StrEnum):
    FOREIGN = "foreign"


@dataclass(slots=True)
class ForeignEvent:
    type: Literal[ForeignEventType.FOREIGN] = ForeignEventType.FOREIGN


def _bus() -> SampleBus:
    bus: SampleBus = Bus(SampleEventType)
    return bus


async def test_bus_preserves_structural_union_narrowing() -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(event: SampleEvent) -> None:
        match event.type:
            case SampleEventType.ITEM:
                seen.append(event.item)
            case SampleEventType.PARTIAL:
                seen.append(event.partial)
                done.set()

    bus.subscribe(SampleEventType.ITEM, handler)
    bus.subscribe(SampleEventType.PARTIAL, handler)
    bus.publish(ItemEvent(item="complete"))
    bus.publish(PartialEvent(partial="in progress"))

    await asyncio.wait_for(done.wait(), 1)
    assert seen == ["complete", "in progress"]
    await bus.aclose()


async def test_bus_rejects_an_event_from_another_enum_family() -> None:
    bus: Bus[SampleEventType, ForeignEvent] = Bus(SampleEventType)

    with pytest.raises(RuntimeError, match="does not belong to SampleEventType"):
        bus.publish(ForeignEvent())

    await bus.aclose()


async def test_bus_drops_an_event_mutated_while_queued(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = _bus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(event: SampleEvent) -> None:
        match event.type:
            case SampleEventType.ITEM:
                seen.append(event.item)
            case SampleEventType.PARTIAL:
                seen.append(event.partial)
                done.set()

    bus.subscribe(SampleEventType.ITEM, handler)
    bus.subscribe(SampleEventType.PARTIAL, handler)

    queued = ItemEvent(item="must be dropped")
    with caplog.at_level(logging.ERROR, logger="otter_ai_core.bus"):
        bus.publish(queued)
        # No await has yielded to the worker yet, so this deterministically
        # changes the queued object's discriminator before dispatch.
        object.__setattr__(queued, "type", SampleEventType.PARTIAL)
        bus.publish(PartialEvent(partial="still dispatched"))
        await asyncio.wait_for(done.wait(), 1)

    assert seen == ["still dispatched"]
    assert any("dropped event" in record.getMessage() for record in caplog.records)
    await bus.aclose()
