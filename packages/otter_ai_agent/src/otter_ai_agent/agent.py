"""The :class:`Agent`: the turn/tool-execution layer over a :class:`ModelSession`.

:class:`Agent` ports pi's agent-loop semantics onto otter's **reactive**
session. It owns an :class:`~otter_ai_agent.AgentBus`, subscribes to the
session bus internally, and drives a per-run coroutine (the *driver*) that
implements the turn FSM:

* add the prompt (and any steering) as context items, then
  :meth:`~otter_ai_core.model_session.ModelSession.create_response`;
* await the turn's terminal (``ResponseDone`` + the assistant item's commit,
  or ``ResponseError`` / ``ResponseAborted`` / a session failure);
* on a tool-use response, execute the calls, add the results, and loop;
* on a stop response (or ``should_stop_after_turn``, or a ``terminate`` batch),
  end the run -- after draining follow-ups.

The driver is a normal coroutine with sequential control flow; the reactivity
lives in the session bus, which the agent subscribes to. The per-turn
"await one response" coupling is a **private** driver detail (a scoped
:class:`asyncio.Future` resolved by the session-bus subscribers and by the
abort signal) -- the session itself stays fully reactive and multi-subscriber.

The agent publishes a reduced :class:`~otter_ai_agent.AgentEvent` family on its
own bus (separate from the session's vocabulary). Two consumption styles:

* :meth:`Agent.on` -- persistent subscriber across runs;
* :meth:`Agent.stream` -- an ``async for`` view of one run;
* :meth:`Agent.run` -- await one run and return its new items.

Single active run: a second :meth:`stream` / :meth:`run` while one is in flight
raises. :meth:`Agent.idle` resolves when the current run (and its inline event
dispatch) has settled.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from otter_ai_core.context import (
    AssistantContextItem,
    AssistantMessage,
    Context,
    ContextItem,
    Role,
    StopReason,
    ToolCall,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.hook import Hook
from otter_ai_core.model_session import ModelSession, SessionEventTypes
from otter_ai_core.model_session.events import (
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDeltaEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    SessionClosedEvent,
    SessionErrorEvent,
    SessionEvent,
)

from .bus import AgentBus
from .events import (
    AgentEndEvent,
    AgentEvent,
    AgentEventType,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from .queue import PendingMessageQueue
from .tools import EventSink, ToolBatch, execute_tool_calls
from .types import (
    AgentConfig,
    PrepareNextTurnContext,
    ShouldStopAfterTurnContext,
)

#: A persistent subscriber registered via :meth:`Agent.on`.
AgentHandler = Callable[[AgentEvent], Awaitable[None]]


def _now_ms() -> int:
    return int(asyncio.get_event_loop().time() * 1000)


def _zero_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _skeleton_message(
    *, stop_reason: StopReason, error_message: str | None = None
) -> AssistantMessage:
    """A minimal assistant message for failure/abort paths with no partial."""
    return AssistantMessage(
        role=Role.Assistant,
        content=[],
        api="unknown",
        provider="unknown",
        model="unknown",
        usage=_zero_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=_now_ms(),
    )


# --------------------------------------------------------------------------- #
# Per-turn / per-run state
# --------------------------------------------------------------------------- #


@dataclass
class _Terminal:
    """The resolved outcome of one turn."""

    kind: str  # "done" | "error" | "aborted"
    message: AssistantMessage
    item: ContextItem | None  # committed assistant item (done only)


@dataclass
class _Turn:
    """Per-turn coordination state shared with the session-bus subscribers."""

    future: asyncio.Future[_Terminal]
    #: Set on ``ResponseDone``; the turn resolves once the assistant item is
    #: also committed (see ``_maybe_resolve``).
    pending_message: AssistantMessage | None = None
    #: Set when the assistant ``ContextItemAdded`` arrives before ``ResponseDone``.
    pending_item: ContextItem | None = None
    #: Latest streaming snapshot (for best-effort abort messages).
    last_partial: AssistantMessage | None = None

    def resolve(self, terminal: _Terminal) -> bool:
        if not self.future.done():
            self.future.set_result(terminal)
            return True
        return False


@dataclass
class _Run:
    abort: asyncio.Event
    new_items: list[ContextItem] = field(default_factory=list)
    turn: _Turn | None = None
    task: asyncio.Task[None] | None = None


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #


class Agent:
    """Stateful agent over a :class:`ModelSession`.

    Construct with a session and an :class:`AgentConfig` (tools + hooks), then
    drive with :meth:`stream` / :meth:`run`. Subscribe to events with
    :meth:`on`; queue steering/follow-up user messages with :meth:`steer` /
    :meth:`follow_up`. Stop with :meth:`abort` (per-turn, session stays open)
    or :meth:`close` (hard).
    """

    _session: ModelSession
    _config: AgentConfig
    _bus: AgentBus
    _steering: PendingMessageQueue
    _follow_up: PendingMessageQueue
    _context: Context
    _run: _Run | None
    _unsubscribers: list[Callable[[], None]]

    def __init__(self, session: ModelSession, config: AgentConfig) -> None:
        self._session = session
        self._config = config
        self._bus = AgentBus()
        self._steering = PendingMessageQueue(config.steering_mode)
        self._follow_up = PendingMessageQueue(config.follow_up_mode)
        self._context = Context()
        self._run = None
        self._unsubscribers = [
            session.on(
                SessionEventTypes.ResponseStarted,
                cast(Hook[SessionEvent, None], self._on_response_started),
            ),
            session.on(
                SessionEventTypes.ResponseDelta,
                cast(Hook[SessionEvent, None], self._on_response_delta),
            ),
            session.on(
                SessionEventTypes.ResponseDone,
                cast(Hook[SessionEvent, None], self._on_response_done),
            ),
            session.on(
                SessionEventTypes.ResponseError,
                cast(Hook[SessionEvent, None], self._on_response_error),
            ),
            session.on(
                SessionEventTypes.ResponseAborted,
                cast(Hook[SessionEvent, None], self._on_response_aborted),
            ),
            session.on(
                SessionEventTypes.ContextItemAdded,
                cast(Hook[SessionEvent, None], self._on_context_item_added),
            ),
            session.on(
                SessionEventTypes.SessionError,
                cast(Hook[SessionEvent, None], self._on_session_error),
            ),
            session.on(
                SessionEventTypes.SessionClosed,
                cast(Hook[SessionEvent, None], self._on_session_closed),
            ),
        ]

    # ----------------------------------------------------------------- #
    # Public surface
    # ----------------------------------------------------------------- #

    @property
    def context(self) -> Context:
        """Live conversation view (synced from committed context items)."""
        return self._context

    @property
    def is_running(self) -> bool:
        return self._run is not None

    def on(
        self, event_type: AgentEventType, handler: AgentHandler
    ) -> Callable[[], None]:
        """Register a persistent subscriber. Returns an unsubscribe callable."""
        return self._bus.subscribe(event_type, handler)

    def steer(self, message: UserMessage) -> None:
        """Queue a user message to inject after the current turn (mid-run)."""
        self._steering.enqueue(message)

    def follow_up(self, message: UserMessage) -> None:
        """Queue a user message to run after the agent would otherwise stop."""
        self._follow_up.enqueue(message)

    def abort(self) -> None:
        """Request the current run stop after the in-flight turn (graceful).

        Signals the run's abort event and calls
        :meth:`ModelSession.abort_response`; the session stays open for further
        runs.
        """
        if self._run is not None:
            self._run.abort.set()
        self._session.abort_response()

    def close(self) -> None:
        """Hard-stop: abort the run and tear down the session connection."""
        if self._run is not None:
            self._run.abort.set()
        self._session.close()

    async def idle(self) -> None:
        """Resolve when the current run (and its inline dispatch) has settled."""
        if self._run is not None and self._run.task is not None:
            await self._run.task

    def stream(
        self, prompt: str | UserMessage | UserContextItem | list[Any]
    ) -> AsyncIterator[AgentEvent]:
        """Start a run and return an ``async for`` view of its events.

        The run is driven by a background task; this iterator taps the agent
        bus and yields until ``agent.end``. Abandoning the iterator does not
        abort the run (use :meth:`abort` / :meth:`close`).
        """
        run = self._start_run(prompt)
        return self._iter_run(run)

    async def run(
        self, prompt: str | UserMessage | UserContextItem | list[Any]
    ) -> list[ContextItem]:
        """Start a run, drain its events, and return the new context items."""
        items: list[ContextItem] = []
        async for event in self.stream(prompt):
            if event.type == AgentEventType.AgentEnd:
                items = event.items
        return items

    # ----------------------------------------------------------------- #
    # Run lifecycle
    # ----------------------------------------------------------------- #

    def _start_run(self, prompt: Any) -> _Run:
        if self._run is not None:
            raise RuntimeError(
                "Agent is already running. Await agent.idle() "
                "before starting another run.",
            )
        run = _Run(abort=asyncio.Event())
        self._run = run
        prompts = self._normalize_prompt(prompt)

        async def runner() -> None:
            try:
                await self._drive(run, prompts)
            except Exception:  # noqa: BLE001 — guarantee agent_end on any failure.
                import logging

                logging.getLogger(__name__).exception("agent driver raised")
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=True,
                    )
                )
            finally:
                if self._run is run:
                    self._run = None

        run.task = asyncio.create_task(runner())
        return run

    async def _iter_run(self, run: _Run) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

        async def tap(event: AgentEvent) -> None:
            queue.put_nowait(event)

        unsubscribe = self._bus.subscribe_all(tap)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.type == AgentEventType.AgentEnd:
                    return
        finally:
            unsubscribe()

    # ----------------------------------------------------------------- #
    # The driver (turn FSM)
    # ----------------------------------------------------------------- #

    async def _drive(self, run: _Run, prompts: list[UserMessage]) -> None:
        await self._bus.publish(AgentStartEvent(type=AgentEventType.AgentStart))

        # Pending user messages to inject before the next create_response.
        # Starts with the prompt + any steering queued before the run.
        pending: list[UserMessage] = [*prompts, *self._steering.drain()]

        has_more = True
        while has_more or pending:
            await self._bus.publish(TurnStartEvent(type=AgentEventType.TurnStart))

            # Inject pending user messages as context items.
            for message in pending:
                await self._add_item(
                    run, UserContextItem.from_message(message, _uuid())
                )
            pending = []

            terminal = await self._run_one_turn(run)

            if terminal.kind in ("error", "aborted"):
                await self._bus.publish(
                    TurnEndEvent(
                        type=AgentEventType.TurnEnd,
                        message=terminal.message,
                        tool_results=[],
                    )
                )
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=True,
                    )
                )
                return

            tool_results, keep_going = await self._handle_tools(run, terminal)

            await self._bus.publish(
                TurnEndEvent(
                    type=AgentEventType.TurnEnd,
                    message=terminal.message,
                    tool_results=tool_results,
                )
            )

            if run.abort.is_set():
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=True,
                    )
                )
                return

            has_more = keep_going

            if await self._should_stop(terminal, tool_results, run):
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=False,
                    )
                )
                return

            await self._apply_prepare_next_turn(terminal, tool_results, run)

            pending = self._steering.drain()

        # Agent would stop -- drain follow-ups.
        follow_ups = self._follow_up.drain()
        if follow_ups:
            await self._drive_follow_ups(run, follow_ups)
        else:
            await self._bus.publish(
                AgentEndEvent(
                    type=AgentEventType.AgentEnd, items=list(run.new_items), error=False
                )
            )

    async def _drive_follow_ups(self, run: _Run, follow_ups: list[UserMessage]) -> None:
        """Re-enter the driver with follow-up messages as the new pending set."""
        # Recursion mirrors pi's outer loop: follow-ups become pending messages
        # and the inner loop runs again.
        pending: list[UserMessage] = list(follow_ups)
        has_more = True
        while has_more or pending:
            await self._bus.publish(TurnStartEvent(type=AgentEventType.TurnStart))
            for message in pending:
                await self._add_item(
                    run, UserContextItem.from_message(message, _uuid())
                )
            pending = []
            terminal = await self._run_one_turn(run)
            if terminal.kind in ("error", "aborted"):
                await self._bus.publish(
                    TurnEndEvent(
                        type=AgentEventType.TurnEnd,
                        message=terminal.message,
                        tool_results=[],
                    )
                )
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=True,
                    )
                )
                return
            tool_results, keep_going = await self._handle_tools(run, terminal)
            await self._bus.publish(
                TurnEndEvent(
                    type=AgentEventType.TurnEnd,
                    message=terminal.message,
                    tool_results=tool_results,
                )
            )
            if run.abort.is_set():
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=True,
                    )
                )
                return
            has_more = keep_going
            if await self._should_stop(terminal, tool_results, run):
                await self._bus.publish(
                    AgentEndEvent(
                        type=AgentEventType.AgentEnd,
                        items=list(run.new_items),
                        error=False,
                    )
                )
                return
            await self._apply_prepare_next_turn(terminal, tool_results, run)
            pending = self._steering.drain()
        more = self._follow_up.drain()
        if more:
            await self._drive_follow_ups(run, more)
        else:
            await self._bus.publish(
                AgentEndEvent(
                    type=AgentEventType.AgentEnd, items=list(run.new_items), error=False
                )
            )

    async def _run_one_turn(self, run: _Run) -> _Terminal:
        """Request one response and await its terminal (abort-aware)."""
        loop = asyncio.get_event_loop()
        turn = _Turn(future=loop.create_future())
        run.turn = turn
        try:
            self._session.create_response()
            return await self._await_turn(run, turn)
        finally:
            run.turn = None

    async def _await_turn(self, run: _Run, turn: _Turn) -> _Terminal:
        """Await the turn future, racing it against the abort signal."""
        if turn.future.done():
            return turn.future.result()
        abort_task = asyncio.create_task(run.abort.wait())
        wait_set: set[asyncio.Future[Any]] = {turn.future, abort_task}
        try:
            await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not abort_task.done():
                abort_task.cancel()
        if not turn.future.done():
            # Abort fired before the session delivered a terminal. Resolve with
            # the best-effort partial so the driver can end gracefully; a late
            # session terminal is ignored (the future is now done).
            partial = turn.last_partial or _skeleton_message(
                stop_reason=StopReason.Aborted
            )
            turn.resolve(_Terminal("aborted", partial, None))
        return turn.future.result()

    async def _handle_tools(
        self, run: _Run, terminal: _Terminal
    ) -> tuple[list[ToolResultMessage], bool]:
        """Execute any tool calls in the turn; add results. Returns
        ``(result_messages, keep_going)``."""
        message = terminal.message
        tool_calls = [c for c in message.content if isinstance(c, ToolCall)]
        if not tool_calls:
            return [], False

        assert terminal.item is not None
        batch: ToolBatch = await execute_tool_calls(
            message, self._config, self._context, run.abort, self._publish_sink()
        )
        for result_message in batch.messages:
            item = ToolResultContextItem.from_message(result_message, _uuid())
            await self._add_item(run, item)
        return batch.messages, (not batch.terminate)

    async def _add_item(self, run: _Run, item: ContextItem) -> None:
        """Add a driver-authored item (user prompt / tool result): update the
        view, emit its message events, and send it to the session."""
        self._context.items.append(item)
        run.new_items.append(item)
        await self._bus.publish(
            MessageStartEvent(type=AgentEventType.MessageStart, item=item)
        )
        await self._bus.publish(
            MessageEndEvent(type=AgentEventType.MessageEnd, item=item)
        )
        self._session.add_context_item(item)

    def _publish_sink(self) -> EventSink:
        return self._bus.publish

    async def _should_stop(
        self, terminal: _Terminal, tool_results: list[ToolResultMessage], run: _Run
    ) -> bool:
        hook = self._config.should_stop_after_turn
        if hook is None:
            return False
        return await hook(
            ShouldStopAfterTurnContext(
                message=terminal.message,
                tool_results=tool_results,
                context=self._context,
                new_items=run.new_items,
            )
        )

    async def _apply_prepare_next_turn(
        self, terminal: _Terminal, tool_results: list[ToolResultMessage], run: _Run
    ) -> None:
        hook = self._config.prepare_next_turn
        if hook is None:
            return
        result = await hook(
            PrepareNextTurnContext(
                message=terminal.message,
                tool_results=tool_results,
                context=self._context,
                new_items=run.new_items,
            )
        )
        if result is not None and result.context is not None:
            self._context = result.context

    # ----------------------------------------------------------------- #
    # Session-bus subscribers (run in the session bus task)
    # ----------------------------------------------------------------- #

    def _active_turn(self) -> _Turn | None:
        run = self._run
        if run is None:
            return None
        return run.turn

    async def _on_response_started(self, event: ResponseStartedEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        turn.last_partial = event.partial
        synthetic = AssistantContextItem.from_message(event.partial, "")
        await self._bus.publish(
            MessageStartEvent(type=AgentEventType.MessageStart, item=synthetic)
        )

    async def _on_response_delta(self, event: ResponseDeltaEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        turn.last_partial = event.partial
        await self._bus.publish(
            MessageUpdateEvent(
                type=AgentEventType.MessageUpdate,
                message=event.partial,
                stream_event=None,
            )
        )

    async def _on_response_done(self, event: ResponseDoneEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        turn.last_partial = event.message
        turn.pending_message = event.message
        self._maybe_resolve_done(turn)

    async def _on_response_error(self, event: ResponseErrorEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        message = event.message
        synthetic = AssistantContextItem.from_message(message, "")
        await self._bus.publish(
            MessageStartEvent(type=AgentEventType.MessageStart, item=synthetic)
        )
        await self._bus.publish(
            MessageEndEvent(type=AgentEventType.MessageEnd, item=synthetic)
        )
        turn.resolve(_Terminal("error", message, None))

    async def _on_response_aborted(self, event: ResponseAbortedEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        message = event.message
        synthetic = AssistantContextItem.from_message(message, "")
        await self._bus.publish(
            MessageStartEvent(type=AgentEventType.MessageStart, item=synthetic)
        )
        await self._bus.publish(
            MessageEndEvent(type=AgentEventType.MessageEnd, item=synthetic)
        )
        turn.resolve(_Terminal("aborted", message, None))

    async def _on_context_item_added(self, event: ContextItemAddedEvent) -> None:
        run = self._run
        item = event.item
        already = any(existing.id == item.id for existing in self._context.items)
        if not already:
            self._context.items.append(item)
            if run is not None:
                run.new_items.append(item)

        # Assistant commit finalises the in-flight turn.
        if item.role == Role.Assistant:
            turn = self._active_turn()
            if turn is not None:
                if not already:
                    await self._bus.publish(
                        MessageEndEvent(type=AgentEventType.MessageEnd, item=item)
                    )
                turn.pending_item = item
                self._maybe_resolve_done(turn)

    async def _on_session_error(self, event: SessionErrorEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        turn.resolve(
            _Terminal(
                "error",
                _skeleton_message(
                    stop_reason=StopReason.Error, error_message=event.message
                ),
                None,
            )
        )

    async def _on_session_closed(self, event: SessionClosedEvent) -> None:
        turn = self._active_turn()
        if turn is None:
            return
        turn.resolve(
            _Terminal(
                "aborted",
                _skeleton_message(
                    stop_reason=StopReason.Aborted, error_message="session closed"
                ),
                None,
            )
        )

    def _maybe_resolve_done(self, turn: _Turn) -> None:
        """Resolve the turn as ``done`` once both the message and the committed
        assistant item have been seen (either may arrive first)."""
        if (
            turn.pending_message is not None
            and turn.pending_item is not None
            and not turn.future.done()
        ):
            turn.future.set_result(
                _Terminal("done", turn.pending_message, turn.pending_item)
            )

    # ----------------------------------------------------------------- #
    # Prompt normalization
    # ----------------------------------------------------------------- #

    def _normalize_prompt(
        self, prompt: str | UserMessage | UserContextItem | list[Any]
    ) -> list[UserMessage]:
        if isinstance(prompt, str):
            return [UserMessage(role=Role.User, content=prompt, timestamp=_now_ms())]
        if isinstance(prompt, UserMessage):
            return [prompt]
        if isinstance(prompt, UserContextItem):
            return [prompt.to_message()]
        if isinstance(prompt, list):
            out: list[UserMessage] = []
            for part in prompt:
                out.extend(self._normalize_prompt(part))
            return out
        raise TypeError(f"Unsupported prompt type: {type(prompt).__name__}")


def _uuid() -> str:
    return str(uuid.uuid4())
