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
    between them. A prompt sent while a turn is running is queued as a
    steering prompt: the current iteration is left undisturbed and
    the prompt is added as a user message at the next generation
    boundary — the next iteration of the running turn when the
    current one ends with a tool response, otherwise the first
    iteration of a follow-up turn that starts when the running
    turn ends. :meth:`is_idle`
    and :meth:`wait_for_idle` cover a run — the current turn together
    with any follow-up turns it chains.

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
        self._steering_prompts: list[str] = []

    async def stream(self) -> AsyncGenerator[AgentEvents, None]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    def cancel_stream(self) -> None:
        self._events.put_nowait(None)

    def prompt(self, text: str) -> None:
        """Starts a turn from ``text`` when idle. While a turn is
        running, ``text`` is queued as a steering prompt instead: the
        current iteration is left undisturbed and the prompt is added
        as a user message at the next generation boundary — the next
        iteration of the running turn when the current one ends with a
        tool response, otherwise the first iteration of a follow-up
        turn that starts when the running turn ends."""
        if not self.is_idle():
            self._steering_prompts.append(text)
            return
        self._turn = asyncio.create_task(self._run_turns(text))

    def is_idle(self) -> bool:
        return self._turn is None or self._turn.done()

    async def wait_for_idle(self) -> None:
        if self._turn is not None:
            await self._turn

    async def _run_turns(self, text: str) -> None:
        """Runs turns for as long as steering prompts keep arriving: a
        turn that ends with prompts queued chains a follow-up turn that
        drains all of them into its first iteration."""
        texts: list[str] | None = [text]
        while texts is not None:
            await self._run_turn(texts)
            texts = self._drain_steering_prompts()

    def _drain_steering_prompts(self) -> list[str] | None:
        if not self._steering_prompts:
            return None
        drained = self._steering_prompts
        self._steering_prompts = []
        return drained

    async def _run_turn(self, texts: list[str]) -> None:
        iterations: list[AgentIteration] = []
        pending_texts: list[str] | None = texts

        self._emit(AgentTurnStartEvent(id=_event_id()))

        while True:
            self._emit(AgentIterationStartEvent())

            user_messages: list[UserMessage] = []
            if pending_texts is not None:
                for text in pending_texts:
                    message = await self._model.add_user_message(text)
                    user_messages.append(message)
                    self._emit(AgentSessionMessageEvent(id=_event_id(), message=message))
                pending_texts = None

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
            pending_texts = self._drain_steering_prompts()

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
