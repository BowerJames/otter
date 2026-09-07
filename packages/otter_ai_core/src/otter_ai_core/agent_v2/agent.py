import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterable

from otter_ai_core.abstractions import AgentTool, Model
from otter_ai_core.agent_v2.types import (
    AgentEvents,
    AgentIterationEndEvent,
    AgentIterationStartEvent,
    AgentSessionMessageEvent,
    AgentTurnEndEvent,
    AgentTurnStartEvent,
    _Iteration,
)
from otter_ai_core.types import UserMessage


class Agent:
    """Agent loop over a Model seam, observed through a long-lived
    event stream.

    Turns are started with :meth:`prompt` and observed by iterating the
    object returned by :meth:`stream`; events emitted before iteration
    begins are buffered, so a consumer attaching just before a turn
    still sees every event. The stream stays open across turns and ends
    only when :meth:`cancel_stream` closes it.

    Within a turn, each iteration adds pending input messages to the
    model, generates one assistant message, and ends the turn when the
    assistant's ``stop_reason`` is ``final_response``. Assistant messages
    are treated as opaque except for ``stop_reason``.
    """

    def __init__(self, model: Model, tools: list[AgentTool]) -> None:
        names = [tool.name for tool in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate tool names: {duplicates}")
        self._model = model
        self._tools = tools
        self._events: asyncio.Queue[AgentEvents | None] = asyncio.Queue()
        self._turn: asyncio.Task[None] | None = None

    def stream(self) -> AsyncIterable[AgentEvents]:
        return self._stream_events()

    async def _stream_events(self) -> AsyncGenerator[AgentEvents, None]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    def cancel_stream(self) -> None:
        self._events.put_nowait(None)

    def prompt(self, text: str) -> None:
        self._turn = asyncio.create_task(self._run_turn(text))

    def is_idle(self) -> bool:
        return self._turn is None or self._turn.done()

    async def wait_for_idle(self) -> None:
        if self._turn is not None:
            await self._turn

    async def _run_turn(self, text: str) -> None:
        iterations: list[_Iteration] = []
        pending_text: str | None = text

        self._emit(AgentTurnStartEvent(id=_event_id()))

        while True:
            self._emit(AgentIterationStartEvent())

            user_messages: list[UserMessage] = []
            if pending_text is not None:
                message = await self._model.add_user_message(pending_text)
                pending_text = None
                user_messages.append(message)
                self._emit(AgentSessionMessageEvent(id=_event_id(), message=message))

            assistant = await self._model.generate()
            self._emit(AgentSessionMessageEvent(id=_event_id(), message=assistant))

            if assistant.stop_reason == "final_response":
                self._emit(
                    AgentIterationEndEvent(
                        id=_event_id(),
                        user_messages=user_messages,
                        assistant_message=assistant,
                        tool_result_messages=None,
                        termination="final_response",
                    )
                )
                iterations.append(
                    _Iteration(
                        user_messages=user_messages,
                        assistant_message=assistant,
                        tool_result_messages=None,
                    )
                )
                self._emit(
                    AgentTurnEndEvent(
                        id=_event_id(),
                        iterations=iterations,
                        termination="final_response",
                    )
                )
                return

            raise NotImplementedError("tool_call iterations are not implemented yet")

    def _emit(self, event: AgentEvents) -> None:
        self._events.put_nowait(event)


def _event_id() -> str:
    return uuid.uuid4().hex
