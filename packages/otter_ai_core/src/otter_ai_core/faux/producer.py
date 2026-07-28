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
        return list(self._requests)

    @property
    def response_count(self) -> int:
        return self._response_count

    @property
    def last_create(self) -> CreateResponse | None:
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
    pair: ModelConnectionPair = create_connection()
    producer = FauxModelProducer(pair.backend, script)
    controller = ModelController(pair.client)
    return FauxModel(controller=controller, producer=producer)
