"""The faux model-connection producer and one-call integration harness.

:class:`FauxModelProducer` is a concrete, in-process producer that owns a
:data:`~otter_ai_core.model_connection.ModelConnectionBackend` and pumps it with
protocol-conformant but fully scriptable
:data:`~otter_ai_core.model_connection.ServerContextEvent` sequences. It is a
**test double, not a provider**: no inference, no network, no transport, no
registry — a concrete producer over the *existing* backend, which is what a
real provider transport will one day be too.

Lifecycle mirrors :class:`~otter_ai_core.model_controller.ModelController`: the
constructor schedules a background drain task and must be called within a
running :mod:`asyncio` event loop; tear down with ``await producer.aclose()`` or
``async with``.

:class:`FauxModel` / :func:`create_faux_model` wire a real controller over a
real connection in one call so an integration test reads as "give the model this
script, drive the controller/loop, assert on the result" — with no API keys and
no flakiness.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from otter_ai_core._lifecycle import await_or_cancel
from otter_ai_core.connection import create_connection
from otter_ai_core.context import (
    AssistantContent,
    AssistantContextItem,
    AssistantMessage,
    ContentType,
    Role,
    StopReason,
    TextContent,
    ToolCall,
    ToolResultContextItem,
    UserContextItem,
)
from otter_ai_core.model_connection import (
    AbortResponse,
    AddToolResultMessage,
    AddUserMessage,
    BranchMove,
    BranchMoved,
    ClientContextEvent,
    CompactionDone,
    CreateCompaction,
    CreateResponse,
    ModelConnectionBackend,
    ModelConnectionPair,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ToolResultAdded,
    UserItemAdded,
)
from otter_ai_core.model_controller import ModelController

from .script import (
    FauxModelScript,
    FauxResponse,
    FauxResponseRepeat,
    FauxStreamPolicy,
    faux_usage,
)

_log = logging.getLogger(__name__)

#: Default graceful-drain deadline (seconds) for :meth:`FauxModelProducer.aclose`.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0


class FauxModelProducer:
    """Pumps a ModelConnectionBackend with scriptable, protocol-conformant events.

    Construct with a backend and a script; a background ``_run`` task drains
    every :data:`ClientContextEvent` and emits the matching
    :data:`~otter_ai_core.model_connection.ServerContextEvent` sequence per the
    script. Tear down with ``await producer.aclose()`` or ``async with``
    (mirrors :class:`~otter_ai_core.model_controller.ModelController`).

    .. note::
       The constructor schedules a background drain task (via
       :func:`asyncio.create_task`) and so must be called from within a running
       :mod:`asyncio` event loop, exactly like ``ModelController``.
    """

    __slots__ = (
        "_backend",
        "_script",
        "_task",
        # spy surface
        "_requests",
        "_response_count",
        "_last_create",
        # emission state
        "_in_flight",
        "_cursor",
        "_next_id",
        "_clock",
    )

    def __init__(self, backend: ModelConnectionBackend, script: FauxModelScript) -> None:
        self._backend = backend
        self._script = script
        # spy surface
        self._requests: list[ClientContextEvent] = []
        self._response_count: int = 0
        self._last_create: CreateResponse | None = None
        # emission state
        self._in_flight: AssistantContextItem | None = None
        self._cursor: int = 0
        # Materialise PRIVATE generators from the script's factories. The
        # (frozen, shareable) script holds only factories; each producer
        # instantiates its own counters, so two producers on one script each
        # start at item-1 / timestamp 0 and never cross-contaminate.
        self._next_id: Callable[[], str] = script.item_id_factory()
        self._clock: Callable[[], int] = script.clock_factory()
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    # ------------------------------------------------------------------ #
    # Spy surface
    # ------------------------------------------------------------------ #

    @property
    def requests(self) -> list[ClientContextEvent]:
        """A snapshot of every client event drained, in order.

        Returns a fresh list (the authoritative "what did the loop ask for?"
        record) so a test cannot mutate the producer's internal record by
        asserting on the return value.
        """
        return list(self._requests)

    @property
    def response_count(self) -> int:
        """Number of terminal ``response.done`` events emitted (incl. abort/error)."""
        return self._response_count

    @property
    def last_create(self) -> CreateResponse | None:
        """The most recent ``response.create`` the producer drained.

        Today :meth:`ModelController.generate` pushes a bare ``CreateResponse()``
        (advisory ``model`` / ``thinking_level`` both ``None``); this spy is
        therefore an ordering/counting aid today, and surfaces the advisory
        fields only once a controller change forwards session model/thinking
        state per turn. Assert on ``response_count`` / ``requests`` for
        turn-count semantics today.
        """
        return self._last_create

    # ------------------------------------------------------------------ #
    # Lifecycle / teardown
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        try:
            async for event in self._backend:  # drains ClientContextEvent
                self._requests.append(event)
                try:
                    await self._handle(event)
                except StopAsyncIteration:
                    # A latency-window race consumed the outbound close-sentinel
                    # (runtime teardown). Break rather than re-entering
                    # ``__anext__`` (the sentinel is spent).
                    break
        except asyncio.CancelledError:
            raise  # teardown (aclose); let the finally clean up
        except Exception:
            # An unexpected failure in the drain loop: log it and let the task
            # end cleanly rather than dying with an unretrieved exception.
            _log.error("faux producer drain loop exited unexpectedly", exc_info=True)
        finally:
            # Conformant teardown: close the inbound so the controller's drain
            # completes (mirrors the ``_conformant_backend`` in the controller
            # tests). Idempotent.
            self._backend.end()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        """Reap the producer's drain task under ``timeout`` (``None`` = forever).

        Cooperative path: when the paired controller was torn down first (the
        normal :meth:`FauxModel.aclose` ordering, or a standalone test calling
        ``controller.aclose()``), the client closed the outbound, so the
        ``async for`` already exited and the task is already done — a no-op.
        Deterministic fallback (standalone teardown with no client-side close):
        the task is still draining, so it is force-cancelled once the deadline
        elapses (its ``finally`` still calls ``backend.end()``).
        """
        await await_or_cancel(self._task, timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #

    async def _handle(self, event: ClientContextEvent) -> None:
        match event:
            case AddUserMessage():
                self._backend.push(
                    UserItemAdded(item=UserContextItem(id=self._next_id(), message=event.message))
                )
            case AddToolResultMessage():
                self._backend.push(
                    ToolResultAdded(
                        item=ToolResultContextItem(id=self._next_id(), message=event.message)
                    )
                )
            case CreateResponse():
                self._last_create = event
                await self._emit_response(event)
            case AbortResponse():
                # Drained outside a generation: ``_in_flight`` is None (a
                # generation always resolves within one ``_handle`` step unless
                # ``delay>0``). With ``delay>0`` the abort is observed by the
                # latency race, not by this path. No-op either way when nothing
                # is in flight.
                self._abort_in_flight()
            case CreateCompaction():
                self._backend.push(self._compaction_confirm(event))
            case BranchMove():
                self._backend.push(self._branch_confirm(event))
            case _:
                # The producer is contractually protocol-conformant: every
                # ClientContextEvent variant is handled above. A miss here
                # means the union grew without updating the producer — fail
                # loud rather than silently dropping the event.
                raise NotImplementedError(
                    f"FauxModelProducer does not handle client event "
                    f"{type(event).__name__} (type={event.type!r}); "
                    f"extend the producer to cover it."
                )

    # ------------------------------------------------------------------ #
    # Response emission
    # ------------------------------------------------------------------ #

    def _select_response(self) -> FauxResponse | None:
        """Pick the next scripted response via a non-destructive cursor.

        Returns ``None`` when exhausted and ``repeat == ERROR`` (the caller emits
        the terminal error ``response.done``). ``repeat == LAST`` replays the
        final scripted response indefinitely.
        """
        responses = self._script.responses
        if self._cursor < len(responses):
            current = responses[self._cursor]
            self._cursor += 1
            return current
        if self._script.repeat is FauxResponseRepeat.LAST and responses:
            return responses[-1]
        return None

    async def _emit_response(self, event: CreateResponse) -> None:  # noqa: ARG002
        response = self._select_response()
        if response is None:
            # Script exhausted + ERROR policy: route through the SAME started→done
            # helper as a normal response (delay=0, no streaming), so every
            # response.create resolves identically and the count/clear logic is
            # shared in one place.
            await self._emit_terminal_error()
            return

        content = list(response.content)
        stop_reason = self._resolve_stop_reason(response, content)
        # Inheritable fields resolve as ``<response> or <script default>`` with an
        # ``is not None`` check (never a truthiness test) so an explicit value is
        # always respected — matching the §5/§17 inheritance discipline.
        provenance = (
            response.provenance if response.provenance is not None else self._script.provenance
        )
        usage = response.usage
        if usage is None:
            usage = self._script.usage
        if usage is None:
            usage = faux_usage()

        item_id = self._next_id()
        final_message = AssistantMessage(
            role=Role.Assistant,
            content=content,
            api=provenance.api,
            provider=provenance.provider,
            model=provenance.model,
            usage=usage,
            stop_reason=stop_reason,
            timestamp=self._clock(),
        )
        final_item = AssistantContextItem(id=item_id, message=final_message)

        # Resolve inheritable fields once (None => script default) and pass them
        # in explicitly. The helper owns the single started→done skeleton and the
        # single response_count / _in_flight update site for every path.
        delay = response.delay if response.delay is not None else self._script.delay
        stream_policy = response.stream if response.stream is not None else self._script.stream
        await self._emit_started_then_streamed(
            item_id, final_message, final_item, delay=delay, stream_policy=stream_policy
        )

    def _started_partial(self, item_id: str, message: AssistantMessage) -> AssistantContextItem:
        """The empty ``ResponseStarted`` partial: same id/provenance/usage/
        timestamp as the final message, but ``content=[]`` / ``stop_reason=None``.

        Shared by every started→done path (the helper is the single skeleton for
        normal, latency-abort, and terminal-error responses alike), so all push
        an identical-shaped ``ResponseStarted``.
        """
        return AssistantContextItem(
            id=item_id,
            message=message.model_copy(update={"content": [], "stop_reason": None}),
        )

    async def _emit_started_then_streamed(
        self,
        item_id: str,
        final_message: AssistantMessage,
        final_item: AssistantContextItem,
        *,
        delay: float,
        stream_policy: FauxStreamPolicy,
    ) -> None:
        """Emit ``ResponseStarted`` (empty partial) [+ latency window] [+
        ``ResponseUpdated``×k] then ``ResponseDone``.

        The **single** started→done skeleton for *every* ``response.create``:
        normal scripted responses, the latency-abort path, and the
        script-exhausted terminal error all flow through here, so the
        terminal-done ``response_count`` increment and the ``_in_flight`` clear
        live in exactly one place. Sets ``_in_flight`` on the started and clears
        it at both exit points: the normal done push below, and (via
        ``_abort_in_flight``) the latency-abort return.
        """
        self._in_flight = final_item
        self._backend.push(ResponseStarted(partial=self._started_partial(item_id, final_message)))

        if delay > 0:
            # Genuine in-flight window: a concurrent controller.abort() pushes an
            # AbortResponse that this race observes. On abort, emit an Aborted
            # done and return (the count/clear still runs via _abort_in_flight).
            abort = await self._await_abort_within(delay)
            if abort is not None:
                self._abort_in_flight()
                return

        if stream_policy.enabled:
            for partial in self._streaming_partials(
                item_id, final_message, stream_policy.chunk_size
            ):
                self._backend.push(ResponseUpdated(partial=partial))

        self._backend.push(ResponseDone(item=final_item))
        self._response_count += 1
        self._in_flight = None  # normal terminal done

    async def _await_abort_within(self, delay: float) -> AbortResponse | None:
        """Return an ``AbortResponse`` pushed within ``delay`` seconds, else ``None``.

        This is what makes producer-level protocol abort integration-testable.
        It inserts a real ``await`` between ``ResponseStarted`` and
        ``ResponseDone``, creating an in-flight window in which a concurrent
        ``controller.abort()`` — which pushes an ``AbortResponse`` — is
        observable.

        Under the controller's single-flight contract, the only client→server
        *event* that can arrive mid-window is an ``AbortResponse``; runtime
        teardown closes the outbound instead (the raced ``anext`` completes with
        ``StopAsyncIteration``, propagated so ``_run``'s drain exits cleanly).
        Any *other* event mid-window is a single-flight contract violation and
        raises (fail-loud) rather than being silently dropped.

        The explicit two-task ``asyncio.wait`` (not ``wait_for``) finalises each
        task by hand and checks ``get_task.done()`` *after* the wait returns, so
        the "abort and timeout tie" case resolves by reading
        ``get_task.result()`` (the abort wins) rather than discarding a
        just-completed get — loss-free. The consumed abort is appended to
        :attr:`requests` so the spy surface records it regardless of which path
        drained it.
        """
        get_task: asyncio.Task[ClientContextEvent] = asyncio.create_task(anext(self._backend))
        timer: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(delay))
        await asyncio.wait({get_task, timer}, return_when=asyncio.FIRST_COMPLETED)
        # Finalise whichever task did not win, to avoid dangling tasks.
        if not timer.done():
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer
        if not get_task.done():
            # Timer won the race strictly first: no event within the window.
            get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await get_task
            return None
        # get_task won (or tied). ``.result()`` re-raises StopAsyncIteration on
        # outbound-close (teardown) so ``_run``'s drain exits cleanly; otherwise
        # returns the drained event.
        event = get_task.result()
        if not isinstance(event, AbortResponse):
            raise RuntimeError(
                f"FauxModelProducer latency window drained a non-abort event "
                f"{type(event).__name__} ({event.type!r}); under the controller's "
                f"single-flight contract only an AbortResponse can arrive "
                f"mid-generation. This indicates a controller/loop bug or a test "
                f"pushing client events directly during a generation."
            )
        self._requests.append(event)  # record the abort on the spy surface
        return event

    def _resolve_stop_reason(
        self, response: FauxResponse, content: list[AssistantContent]
    ) -> StopReason:
        if response.stop_reason is not None:
            return response.stop_reason
        if any(isinstance(block, ToolCall) for block in content):
            return StopReason.ToolUse
        return StopReason.Stop

    def _streaming_partials(
        self, item_id: str, message: AssistantMessage, chunk_size: int
    ) -> list[AssistantContextItem]:
        """Growing ``ResponseUpdated`` snapshots for the text portion of a response.

        Concatenates every ``TextContent`` block's text and emits one snapshot
        per ``chunk_size``-char prefix (``stop_reason=None`` throughout).
        ``ThinkingContent`` / ``ToolCall`` blocks are **not** streamed: they
        appear in full only on the terminal ``response.done``.
        """
        text = "".join(block.text for block in message.content if isinstance(block, TextContent))
        step = max(chunk_size, 1)
        snapshots: list[AssistantContextItem] = []
        for end in range(1, len(text) + 1, step):
            snapshots.append(
                AssistantContextItem(
                    id=item_id,
                    message=message.model_copy(
                        update={
                            "content": [TextContent(type=ContentType.Text, text=text[:end])],
                            "stop_reason": None,
                        }
                    ),
                )
            )
        return snapshots

    def _abort_in_flight(self) -> None:
        """Close the in-flight generation with an ``Aborted`` done; no-op if idle.

        Reached in two ways: (a) an ``AbortResponse`` drained by the ordinary
        ``_run`` loop — with ``delay=0`` this finds ``_in_flight`` already
        ``None`` (the generation resolved synchronously) and is a no-op; (b) the
        latency race with ``delay>0``, which finds ``_in_flight`` set and emits
        the ``Aborted`` ``response.done`` so a concurrent
        ``controller.abort()`` resolves with the aborted item.

        The aborted ``response.done`` carries the **full** scripted content with
        ``stop_reason=Aborted`` / ``error_message="aborted"`` (not a truncated
        partial): a real provider streams partial content and would truncate at
        the interruption point, but the faux producer trades that realism for
        determinism so the aborted item is reproducible.
        """
        current = self._in_flight
        if current is None:
            return  # nothing in flight
        aborted = AssistantContextItem(
            id=current.id,
            message=current.message.model_copy(
                update={"stop_reason": StopReason.Aborted, "error_message": "aborted"}
            ),
        )
        self._backend.push(ResponseDone(item=aborted))
        self._response_count += 1
        self._in_flight = None

    async def _emit_terminal_error(self) -> None:
        """Script-exhausted + ERROR policy: a terminal ``Error`` ``response.done``.

        Builds the error item and routes it through the **same**
        :meth:`_emit_started_then_streamed` helper as a normal response
        (``delay=0.0``, streaming disabled), so the error path resolves with the
        identical started→done shape and shares the single ``response_count`` /
        ``_in_flight`` update site. Fully synchronous (no latency window, no
        streaming): a ``generate()`` whose script was exhausted returns an error
        item immediately instead of hanging.
        """
        item_id = self._next_id()
        usage = self._script.usage or faux_usage()
        provenance = self._script.provenance
        message = AssistantMessage(
            role=Role.Assistant,
            content=[],
            api=provenance.api,
            provider=provenance.provider,
            model=provenance.model,
            usage=usage,
            stop_reason=StopReason.Error,
            error_message=(
                f"FauxModelProducer: script exhausted (no response for request #{self._cursor + 1})"
            ),
            timestamp=self._clock(),
        )
        item = AssistantContextItem(id=item_id, message=message)
        await self._emit_started_then_streamed(
            item_id, message, item, delay=0.0, stream_policy=FauxStreamPolicy()
        )

    # ------------------------------------------------------------------ #
    # Session-op confirms
    # ------------------------------------------------------------------ #

    def _compaction_confirm(self, event: CreateCompaction) -> CompactionDone:
        outcome = self._script.compaction
        if outcome.error_message is not None:
            return CompactionDone(error_message=outcome.error_message)
        # Mirror a real stateful server: a client-supplied summary / retention
        # point wins over the script default, so controller.compact(summary=...)
        # is exercisable end-to-end. (custom_instructions is an instruction to
        # the server, not an echoed value, so it is intentionally not mapped.)
        return CompactionDone(
            summary=event.summary or outcome.summary,
            first_kept_item_id=event.first_kept_item_id or outcome.first_kept_item_id,
        )

    def _branch_confirm(self, event: BranchMove) -> BranchMoved:
        outcome = self._script.branch
        # at_item_id always echoes the request target, even on refusal (protocol
        # requirement). BranchMoved carries no client-supplied summary field, so
        # event.summary is intentionally not mapped.
        return BranchMoved(at_item_id=event.at_item_id, error_message=outcome.error_message)


# --------------------------------------------------------------------------- #
# One-call integration harness
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FauxModel:
    """A real ModelController driven by a FauxModelProducer over one connection.

    Construct with :func:`create_faux_model`. Drive ``.controller`` exactly as a
    production controller; tear down with ``await model.aclose()`` or
    ``async with``.

    .. note::
       :func:`create_faux_model` schedules two background tasks (the producer
       drain and the controller drain) and must be called within a running
       :mod:`asyncio` event loop.
    """

    controller: ModelController
    producer: FauxModelProducer

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        # 1. Controller teardown aborts the connection (sets abort_signal +
        #    closes outbound) -> the producer's drain loop exits and its
        #    `finally` ends the inbound -> the controller's drain completes.
        await self.controller.aclose(timeout)
        # 2. Reap the producer task (already done via the cooperative path
        #    above; this is a no-op unless teardown was non-cooperative).
        await self.producer.aclose(timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def create_faux_model(script: FauxModelScript) -> FauxModel:
    """Wire a real ModelController + FauxModelProducer over a fresh connection."""
    pair: ModelConnectionPair = create_connection()
    producer = FauxModelProducer(pair.backend, script)
    controller = ModelController(pair.client)
    return FauxModel(controller=controller, producer=producer)
