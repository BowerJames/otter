import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from otter_ai_core.agent_loop.agent_tool import AgentToolResult
from otter_ai_core.agent_loop.hooks import (
    BEFORE_TOOL_CALL,
    TOOL_RESULT,
    ToolResultHookParams,
)
from otter_ai_core.agent_loop.state import State
from otter_ai_core.context import (
    AssistantContextItem,
    ContentType,
    Role,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from otter_ai_core.hook_runner import Hook, HookHandler, HookRunner
from otter_ai_core.interfaces import AgentTool, ModelController
from otter_ai_core.model_connection import AddToolResultMessage, AddUserMessage


class QueueMode(StrEnum):
    ONE_BY_ONE = "one_by_one"
    ALL_AT_ONCE = "all_at_once"


class ToolExecMode(StrEnum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"


@dataclass(slots=True)
class AgentLoop:
    _controller: ModelController
    _follow_up_mode: QueueMode
    _steering_mode: QueueMode
    #: Execution handlers the loop dispatches ``ToolCall``\ s to (by ``name``).
    #: Note: the model must be told about the corresponding ``Tool`` definitions
    #: out of band (server/transport-side); this list holds execution only.
    _tools: list[AgentTool[BaseModel, Any]] = field(default_factory=list)
    #: How a turn's tool calls are executed. Defaults to sequential.
    _tool_exec_mode: ToolExecMode = ToolExecMode.SEQUENTIAL
    #: Cap on completed turns (one turn = one generation + its tool results).
    #: ``None`` (default) loops to completion. Must be ``>= 1``; the loop always
    #: runs at least one turn regardless.
    _max_turns: int | None = None
    #: Extension registry callers attach typed hooks to via :meth:`on`. The loop
    #: emits :data:`~otter_ai_core.agent_loop.hooks.BEFORE_TOOL_CALL` before each
    #: tool call is executed and
    #: :data:`~otter_ai_core.agent_loop.hooks.TOOL_RESULT` after a tool actually
    #: executes (see :meth:`_execute_one`).
    _hook_runner: HookRunner = field(default_factory=HookRunner)
    _state: State = field(default_factory=State)
    _abort_signal: asyncio.Event = field(default_factory=asyncio.Event)
    _steering_queue: asyncio.Queue[UserMessage] = field(default_factory=asyncio.Queue)
    _follow_up_queue: asyncio.Queue[UserMessage] = field(default_factory=asyncio.Queue)
    _task: asyncio.Task[None] | None = field(default=None)

    def __post_init__(self) -> None:
        self._task = asyncio.create_task(self._run())

    # ------------------------------------------------------------------ #
    # Hook surface
    # ------------------------------------------------------------------ #

    @property
    def hook_runner(self) -> HookRunner:
        return self._hook_runner

    def on[TParams, TReturn](
        self, hook: Hook[TParams, TReturn], handler: HookHandler[TParams, TReturn]
    ) -> Callable[[], None]:
        return self._hook_runner.register(hook, handler)

    # ------------------------------------------------------------------ #
    # Steering & follow-ups
    # ------------------------------------------------------------------ #

    def _require_running(self, action: str) -> None:
        task = self._task
        if task is not None and task.done():
            raise RuntimeError(f"AgentLoop run task has finished; cannot {action}.")

    def steer(self, message: UserMessage) -> None:
        self._require_running("steer")
        self._steering_queue.put_nowait(message)

    def follow_up(self, message: UserMessage) -> None:
        self._require_running("follow_up")
        self._follow_up_queue.put_nowait(message)

    async def _run(self) -> None:
        try:
            await self._run_outer_loop()
        finally:
            self._state.set_idle()

    async def _run_outer_loop(self) -> None:
        while not self._follow_up_queue.empty():
            messages: list[UserMessage] = _drain_queue(self._follow_up_queue, self._follow_up_mode)
            for message in messages:
                _ = await self._controller.add_message(AddUserMessage(message=message))
            await self._run_inner_loop()

    async def _run_inner_loop(self) -> None:
        turns = 0
        while True:
            # Steering = user messages injected before each turn (between turns).
            for message in _drain_queue(self._steering_queue, self._steering_mode):
                _ = await self._controller.add_message(AddUserMessage(message=message))

            assistant_item: AssistantContextItem = await self._controller.generate()
            tool_calls = assistant_item.message.tool_calls

            if tool_calls:
                if await self._execute_tools(tool_calls):
                    return  # a tool requested termination

            # ---- turn boundary: one generation (+ its tool results) complete ----
            turns += 1

            if not tool_calls:
                return  # model finished cleanly — nothing left to execute

            self._check_for_abort()  # between turns; raises CancelledError if set

            if self._max_turns is not None and turns >= self._max_turns:
                return  # cap reached

    async def _execute_tools(self, tool_calls: list[ToolCall]) -> bool:
        match self._tool_exec_mode:
            case ToolExecMode.SEQUENTIAL:
                pairs = [await self._execute_one(call) for call in tool_calls]
            case ToolExecMode.CONCURRENT:
                pairs = await asyncio.gather(*(self._execute_one(c) for c in tool_calls))

        terminate = False
        for result, terminated in pairs:
            _ = await self._controller.add_message(AddToolResultMessage(message=result))
            terminate = terminate or terminated
        return terminate

    async def _execute_one(self, call: ToolCall) -> tuple[ToolResultMessage, bool]:
        intercepted = await self._hook_runner.emit(BEFORE_TOOL_CALL, call)
        if intercepted is not None:
            return self._to_tool_result_message(call, intercepted), intercepted.terminate

        tool = next((t for t in self._tools if t.name == call.name), None)
        if tool is None:
            return self._unknown_tool_result(call), False
        result = await tool.execute(call.id, call.arguments, self._abort_signal)
        override = await self._hook_runner.emit(
            TOOL_RESULT, ToolResultHookParams(tool_call=call, result=result)
        )
        if override is not None:
            result = override
        return self._to_tool_result_message(call, result), result.terminate

    def _to_tool_result_message(
        self, call: ToolCall, result: AgentToolResult[Any]
    ) -> ToolResultMessage:
        return ToolResultMessage(
            role=Role.ToolResult,
            tool_call_id=call.id,
            tool_name=call.name,
            content=result.result,
            details=result.details,
            is_error=result.is_error,
            timestamp=_now_ms(),
        )

    def _unknown_tool_result(self, call: ToolCall) -> ToolResultMessage:
        available = ", ".join(sorted(t.name for t in self._tools)) or "(none configured)"
        return ToolResultMessage(
            role=Role.ToolResult,
            tool_call_id=call.id,
            tool_name=call.name,
            content=[
                TextContent(
                    type=ContentType.Text,
                    text=f"Unknown tool {call.name!r}. Available tools: {available}.",
                )
            ],
            details=None,
            is_error=True,
            timestamp=_now_ms(),
        )

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


def _now_ms() -> int:
    return int(time.time() * 1000)
