from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from otter_ai_core.context import (
    AssistantContent,
    ContentType,
    StopReason,
    TextContent,
    ToolCall,
    Usage,
    UsageCost,
)

# --------------------------------------------------------------------------- #
# Determinism factories — each is a zero-arg callable that returns a FRESH,
# independent generator. The producer calls the factory once at construction;
# the script never holds the generator itself, so it stays state-free and
# shareable.
#
# Defined before FauxModelScript because the script references them as field
# defaults, and dataclass field defaults are evaluated at class-definition
# time — a forward reference here would be a NameError at import.
# --------------------------------------------------------------------------- #

#: A zero-arg factory that returns a fresh, independent ``"item-N"`` id generator.
ItemIdFactory = Callable[[], Callable[[], str]]

#: A zero-arg factory that returns a fresh, independent assistant-timestamp generator.
ClockFactory = Callable[[], Callable[[], int]]


def monotonic_item_ids() -> Callable[[], str]:
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"item-{n}"

    return gen


def deterministic_clock() -> Callable[[], int]:
    n = 0

    def gen() -> int:
        nonlocal n
        value = n
        n += 1
        return value

    return gen


def real_clock() -> Callable[[], int]:
    return lambda: int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# Message / usage builders
# --------------------------------------------------------------------------- #


def faux_text(text: str) -> list[AssistantContent]:
    return [TextContent(type=ContentType.Text, text=text)]


def faux_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
    )


# --------------------------------------------------------------------------- #
# Script value objects (frozen, state-free)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FauxProvenance:
    api: str = "responses"
    provider: str = "faux"
    model: str = "faux-model"


@dataclass(frozen=True, slots=True)
class FauxStreamPolicy:
    enabled: bool = False
    chunk_size: int = 1


@dataclass(frozen=True, slots=True)
class FauxResponse:
    content: list[AssistantContent]
    stop_reason: StopReason | None = None
    usage: Usage | None = None
    provenance: FauxProvenance | None = None
    stream: FauxStreamPolicy | None = None
    #: ``None`` => inherit ``FauxModelScript.delay``; ``0.0`` => explicitly no
    #: latency window (distinguishable from "unset", unlike a truthiness test).
    delay: float | None = None

    # ---- ergonomic builders -------------------------------------------------

    @classmethod
    def text(
        cls,
        text: str,
        *,
        stop_reason: StopReason | None = None,
        usage: Usage | None = None,
        provenance: FauxProvenance | None = None,
        stream: FauxStreamPolicy | None = None,
        delay: float | None = None,
    ) -> FauxResponse:
        return cls(
            content=faux_text(text),
            stop_reason=stop_reason,
            usage=usage,
            provenance=provenance,
            stream=stream,
            delay=delay,
        )

    @classmethod
    def tool_calls(
        cls,
        calls: list[ToolCall],
        *,
        text: str = "",
        stop_reason: StopReason | None = None,
        usage: Usage | None = None,
        provenance: FauxProvenance | None = None,
        stream: FauxStreamPolicy | None = None,
        delay: float | None = None,
    ) -> FauxResponse:
        # Omit the text block entirely when empty (a real tool-call turn usually
        # has no accompanying text); include it only when the test sets ``text``.
        content: list[AssistantContent] = (
            [TextContent(type=ContentType.Text, text=text), *calls] if text else [*calls]
        )
        return cls(
            content=content,
            stop_reason=stop_reason,
            usage=usage,
            provenance=provenance,
            stream=stream,
            delay=delay,
        )


@dataclass(frozen=True, slots=True)
class FauxCompactionOutcome:
    summary: str = "faux compaction summary"
    first_kept_item_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class FauxBranchOutcome:
    error_message: str | None = None


class FauxResponseRepeat(StrEnum):
    ERROR = "error"
    LAST = "last"


@dataclass(frozen=True, slots=True)
class FauxModelScript:
    responses: list[FauxResponse] = field(default_factory=list)
    repeat: FauxResponseRepeat = FauxResponseRepeat.ERROR
    stream: FauxStreamPolicy = field(default_factory=FauxStreamPolicy)
    #: Default latency (seconds) inserted between ``response.started`` and the
    #: terminal ``response.done`` when a ``FauxResponse`` sets ``delay=None``.
    #: ``0.0`` (default) is fully synchronous.
    delay: float = 0.0
    compaction: FauxCompactionOutcome = field(default_factory=FauxCompactionOutcome)
    branch: FauxBranchOutcome = field(default_factory=FauxBranchOutcome)
    provenance: FauxProvenance = field(default_factory=FauxProvenance)
    usage: Usage | None = None  # None => faux_usage() zero-cost default
    #: Server-assigned item-id generator factory. The producer calls it once at
    #: construction; each producer gets an independent counter. Default: the
    #: module-level ``monotonic_item_ids`` factory (``"item-1"``, ``"item-2"``,
    #: …), shared across all item roles. (Distinct from ``ToolCall.id``, which
    #: lives inside the scripted ``AssistantMessage`` and is the test's to set.)
    item_id_factory: ItemIdFactory = field(default=monotonic_item_ids)
    #: Assistant-timestamp generator factory. The producer calls it once at
    #: construction. Default: ``deterministic_clock`` (opaque ordered ints from
    #: ``0``). (Does not govern user/tool-result timestamps, which are
    #: caller-controlled.)
    clock_factory: ClockFactory = field(default=deterministic_clock)


# --------------------------------------------------------------------------- #
# Response convenience constructors (thin aliases over the FauxResponse builders)
# --------------------------------------------------------------------------- #


def faux_text_response(
    text: str,
    *,
    stop_reason: StopReason | None = None,
    usage: Usage | None = None,
    provenance: FauxProvenance | None = None,
    stream: FauxStreamPolicy | None = None,
    delay: float | None = None,
) -> FauxResponse:
    return FauxResponse.text(
        text,
        stop_reason=stop_reason,
        usage=usage,
        provenance=provenance,
        stream=stream,
        delay=delay,
    )


def faux_tool_call_response(
    calls: list[ToolCall],
    *,
    text: str = "",
    stop_reason: StopReason | None = None,
    usage: Usage | None = None,
    provenance: FauxProvenance | None = None,
    stream: FauxStreamPolicy | None = None,
    delay: float | None = None,
) -> FauxResponse:
    return FauxResponse.tool_calls(
        calls,
        text=text,
        stop_reason=stop_reason,
        usage=usage,
        provenance=provenance,
        stream=stream,
        delay=delay,
    )
