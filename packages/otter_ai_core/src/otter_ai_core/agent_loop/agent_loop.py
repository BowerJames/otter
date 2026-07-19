import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from otter_ai_core.agent_loop.state import State
from otter_ai_core.context import UserMessage
from otter_ai_core.model_connection import (
    AddUserMessage,
    ResponseDone,
    ServerContextEvent,
    ServerContextEventType,
)
from otter_ai_core.model_controller import ModelController


class QueueMode(StrEnum):
    ONE_BY_ONE = "one_by_one"
    ALL_AT_ONCE = "all_at_once"


@dataclass(slots=True)
class AgentLoop:
    _controller: ModelController
    _follow_up_mode: QueueMode
    _steering_mode: QueueMode
    _state: State = field(default_factory=State)
    _abort_signal: asyncio.Event = field(default_factory=asyncio.Event)
    _steering_queue: asyncio.Queue[UserMessage] = field(default_factory=asyncio.Queue)
    _follow_up_queue: asyncio.Queue[UserMessage] = field(default_factory=asyncio.Queue)
    _task: asyncio.Task[None] | None = field(default=None)

    def __post_init__(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await self._run_outer_loop()
        finally:
            self._state.set_idle()

    async def _run_outer_loop(self) -> None:
        while not self._follow_up_queue.empty():
            messages: list[UserMessage] = _drain_queue(self._follow_up_queue, self._follow_up_mode)
            await self._run_inner_loop(messages)

    async def _run_inner_loop(self, messages: list[UserMessage]) -> None:
        while not self._steering_queue.empty():
            messages = messages + _drain_queue(self._steering_queue, self._steering_mode)
            _ = await _generate(self._controller, messages)
            raise NotImplementedError

    def _check_for_abort(self) -> None:
        if self._abort_signal.is_set():
            raise asyncio.CancelledError


def _drain_queue[TItem](queue: asyncio.Queue[TItem], mode: QueueMode) -> list[TItem]:
    match mode:
        case QueueMode.ONE_BY_ONE:
            return [queue.get_nowait()]
        case QueueMode.ALL_AT_ONCE:
            items = []
            while True:
                try:
                    items.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return items


async def _generate(controller: ModelController, messages: list[UserMessage]) -> ResponseDone:
    for message in messages:
        await controller.add_message(AddUserMessage(message=message))
    done: list[ResponseDone] = []

    async def _on_done(event: ServerContextEvent) -> None:
        if isinstance(event, ResponseDone):
            done.append(event)

    unsubscribe = controller.on(ServerContextEventType.RESPONSE_DONE, _on_done)
    try:
        await controller.generate()
    finally:
        unsubscribe()
    if done:
        return done[0]
    raise RuntimeError("Model controller generate did not surface a done response")
