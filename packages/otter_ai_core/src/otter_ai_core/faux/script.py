"""The script model for :class:`~otter_ai_core.faux.FauxModelProducer`.

A :class:`FauxModelScript` is the test's "what does the model do": plain,
frozen, in-memory configuration (not a serialized Pydantic model). It carries
no determinism state — only zero-arg factory callables the producer instantiates
once at construction (see :mod:`otter_ai_core.faux.producer` §8 of the #129
spec). Every nested value object (``FauxProvenance`` / ``FauxStreamPolicy`` /
``FauxResponse`` / the outcomes) is frozen too.

File ordering is load-bearing
-----------------------------
The determinism factories (``monotonic_item_ids`` / ``deterministic_clock`` /
``real_clock``) are referenced as :class:`FauxModelScript` field *defaults*.
Dataclass field defaults are evaluated at class-definition time, so those
functions must be defined **above** :class:`FauxModelScript` or the import
fails with ``NameError``. This file is ordered accordingly: type aliases +
factories + builders, then the frozen value objects, then
:class:`FauxModelScript`, then the thin response constructors.
"""

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
    """Factory: returns a fresh ``"item-1"``, ``"item-2"``, … generator."""
    n = 0

    def gen() -> str:
        nonlocal n
        n += 1
        return f"item-{n}"

    return gen


def deterministic_clock() -> Callable[[], int]:
    """Factory: returns a fresh ``0``, ``1``, ``2``, … generator.

    The values are **stable, strictly-increasing, opaque integers** — chosen for
    exact, reproducible assertions on ``AssistantMessage.timestamp``, *not*
    realistic epoch-milliseconds (they are far too small to be valid ms). Only
    their ordering and stability matter for tests. Pass :func:`real_clock` when
    actual epoch-ms realism is required.
    """
    n = 0

    def gen() -> int:
        nonlocal n
        value = n
        n += 1
        return value

    return gen


def real_clock() -> Callable[[], int]:
    """Factory: returns a real wall-clock (epoch-ms) generator for when realism matters.

    Pass as ``FauxModelScript(clock_factory=real_clock)`` (the factory itself —
    the producer invokes it). Affects only assistant-message timestamps the
    producer assembles.
    """
    return lambda: int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# Message / usage builders
# --------------------------------------------------------------------------- #


def faux_text(text: str) -> list[AssistantContent]:
    """``[TextContent(type="text", text=text)]`` — the common single-text-block case."""
    return [TextContent(type=ContentType.Text, text=text)]


def faux_usage() -> Usage:
    """A zero-cost :class:`Usage` (tests rarely care about tokens)."""
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
    """Inert assistant provenance defaults (otter never interprets these)."""

    api: str = "responses"
    provider: str = "faux"
    model: str = "faux-model"


@dataclass(frozen=True, slots=True)
class FauxStreamPolicy:
    """Whether/how a response is streamed as response.started/updated/done.

    Default ``enabled=False`` emits ``response.started`` (empty partial) then
    the terminal ``response.done`` — fast and sufficient for non-streaming
    consumers. ``enabled=True`` additionally emits one ``response.updated`` per
    text chunk of size ``chunk_size`` (default 1 char), so streaming-aware
    consumers are exercised.

    Streaming chunks **text** content only: ``ThinkingContent`` and
    ``ToolCall`` blocks are carried in full on the terminal ``response.done``,
    not dribbled across partials.
    """

    enabled: bool = False
    chunk_size: int = 1


@dataclass(frozen=True, slots=True)
class FauxResponse:
    """One scripted assistant response, emitted for a single ``response.create``.

    ``content`` is the assistant message's content blocks (text / thinking /
    tool_call). ``stop_reason`` defaults to ``None`` ("infer: ``ToolUse`` if
    ``content`` contains any :class:`~otter_ai_core.context.ToolCall`, else
    ``Stop``"); an explicit value always wins. ``delay`` (seconds, ``None`` =
    inherit :attr:`FauxModelScript.delay`) inserts an ``await`` between
    ``response.started`` and the terminal ``response.done``, creating an
    in-flight window in which a concurrent protocol ``abort()`` is observable.
    The producer assembles the full :class:`~otter_ai_core.context.AssistantMessage`
    from ``content`` + the script's provenance/usage/clock defaults.

    Every inheritable field (``stop_reason`` / ``usage`` / ``provenance`` /
    ``stream`` / ``delay``) defaults to ``None`` and is resolved with an
    ``is not None`` check, so an explicit falsy value (e.g. ``delay=0.0``) is
    respected rather than masked by the script default.
    """

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
    """The ``compaction.done`` confirm a ``compaction.create`` resolves to.

    ``error_message`` set => the producer emits a *refusal* confirm (mirrors a
    stateless connection that cannot compact in place). Otherwise the confirm's
    ``summary`` / ``first_kept_item_id`` are resolved by the producer as
    ``<client-supplied from the request> or <these defaults>`` — i.e. a
    ``controller.compact(summary="X", first_kept_item_id="k")`` surfaces
    ``X`` / ``k`` on the confirm, exactly as a real stateful server applies a
    client-supplied summary. (``custom_instructions`` is an instruction to the
    server, not an echoed value, so it is intentionally not mapped.)
    """

    summary: str = "faux compaction summary"
    first_kept_item_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class FauxBranchOutcome:
    """The ``branch.moved`` confirm a ``branch.move`` resolves to.

    ``error_message`` set => refusal confirm (``at_item_id`` is always echoed,
    as the protocol requires — it comes from the request, not the outcome).
    """

    error_message: str | None = None


class FauxResponseRepeat(StrEnum):
    """What the producer does once the scripted response list is exhausted.

    ``ERROR`` (default) — emit a terminal ``response.done`` with
    ``stop_reason=Error`` and a clear ``error_message`` (loud, fail-fast: the
    test under-scripted the model). ``LAST`` — keep replaying the final scripted
    response (convenient for "the model always replies X").
    """

    ERROR = "error"
    LAST = "last"


@dataclass(frozen=True, slots=True)
class FauxModelScript:
    """The full configuration a :class:`FauxModelProducer` runs against.

    Frozen and **state-free**: it holds no counters — only factory callables
    the producer instantiates once at construction. A script is therefore a
    stable, shareable value: two producers built from the *same* script each
    materialise their own item-id / clock generators and each start at
    ``item-1`` / timestamp ``0``.
    """

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
