import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterable
from typing import Literal

from otter_ai_core.abstractions import AgentTool, Model
from otter_ai_core.agent_v2.types import (
    AgentEvents,
    AgentIteration,
    AgentIterationEndEvent,
    AgentIterationStartEvent,
    AgentSessionMessageEvent,
    AgentTurnEndEvent,
    AgentTurnStartEvent,
)
from otter_ai_core.types import AssistantMessage, ToolCall, ToolResultMessage, UserMessage


class Agent:
    """Agent loop over a Model seam, observed through a long-lived
    event stream.

    Turns are started with :meth:`prompt` and observed by iterating the
    object returned by :meth:`stream`; events emitted before iteration
    begins are buffered, so a consumer attaching just before a turn
    still sees every event. The stream stays open across turns, ends
    only when :meth:`cancel_stream` closes it, and supports a single
    consumer at a time — concurrent iterations would split events
    between them.

    Within a turn, each iteration adds pending input messages to the
    model, generates one assistant message, and either ends the turn
    when the assistant's ``stop_reason`` is ``final_response`` or
    executes the requested tool calls and iterates again with their
    results. Assistant messages are treated as opaque except for
    ``stop_reason`` and ``tool_calls``.
    """

    def __init__(self, model: Model, tools: list[AgentTool]) -> None:
        names = [tool.name for tool in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate tool names: {duplicates}")
        self._model = model
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._events: asyncio.Queue[AgentEvents | None] = asyncio.Queue()
        self._turn: asyncio.Task[None] | None = None

    async def stream(self) -> AsyncGenerator[AgentEvents, None]:
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
        iterations: list[AgentIteration] = []
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
                iterations.append(
                    self._close_iteration(user_messages, assistant, None, "final_response")
                )
                self._emit(
                    AgentTurnEndEvent(
                        id=_event_id(),
                        iterations=iterations,
                        termination="final_response",
                    )
                )
                return

            tool_result_messages = await self._execute_tool_calls(assistant.tool_calls)
            iterations.append(
                self._close_iteration(
                    user_messages, assistant, tool_result_messages, "tool_response"
                )
            )

    async def _execute_tool_calls(self, calls: Iterable[ToolCall]) -> list[ToolResultMessage]:
        tool_result_messages: list[ToolResultMessage] = []
        for call in calls:
            tool = self._tools_by_name[call.tool_name]
            result = await tool.execute(call.parameters)
            message = await self._model.add_tool_result_message(call.id, result.text)
            tool_result_messages.append(message)
            self._emit(AgentSessionMessageEvent(id=_event_id(), message=message))
        return tool_result_messages

    def _close_iteration(
        self,
        user_messages: list[UserMessage],
        assistant_message: AssistantMessage,
        tool_result_messages: list[ToolResultMessage] | None,
        termination: Literal["final_response", "tool_response"],
    ) -> AgentIteration:
        self._emit(
            AgentIterationEndEvent(
                id=_event_id(),
                user_messages=user_messages,
                assistant_message=assistant_message,
                tool_result_messages=tool_result_messages,
                termination=termination,
            )
        )
        return AgentIteration(
            user_messages=user_messages,
            assistant_message=assistant_message,
            tool_result_messages=tool_result_messages,
        )

    def _emit(self, event: AgentEvents) -> None:
        self._events.put_nowait(event)


def _event_id() -> str:
    return uuid.uuid4().hex
