import asyncio
from collections.abc import AsyncIterator, Iterable

from otter_ai_core.agent_tool import AgentTool, AgentToolResult
from otter_ai_core.conversation import SessionMessage, ToolCall, UserMessage

from .hooks import AgentLoopHooks
from .types import (
    AgentLoopEvent,
    AgentLoopModel,
    AgentLoopOptions,
    AgentLoopTurn,
    ToolExecution,
)


class AgentLoopExhausted(RuntimeError): ...


class AgentLoopStranded(RuntimeError): ...


class AgentLoop:
    def __init__(
        self,
        model: AgentLoopModel,
        tools: Iterable[AgentTool] = (),
        options: AgentLoopOptions | None = None,
        hooks: AgentLoopHooks | None = None,
    ) -> None:
        self._model = model
        self._tools = tuple(tools)
        self._options = options or AgentLoopOptions()
        self._hooks = hooks or AgentLoopHooks()
        self._iteration_claimed = False
        self._finished = False
        self._generations_used = 0
        self._follow_up_queue: asyncio.Queue[str] = asyncio.Queue()
        self._steering_queue: asyncio.Queue[str] = asyncio.Queue()
        names = [tool.name for tool in self._tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate tool names: {duplicates}")
        self._tools_by_name: dict[str, AgentTool] = {tool.name: tool for tool in self._tools}

    def follow_up(self, text: str) -> None:
        self._require_not_finished("follow_up")
        self._follow_up_queue.put_nowait(text)

    def steer(self, text: str) -> None:
        self._require_not_finished("steer")
        self._steering_queue.put_nowait(text)

    def __aiter__(self) -> AsyncIterator[AgentLoopEvent]:
        if self._iteration_claimed:
            raise RuntimeError("AgentLoop is single-use; construct a new AgentLoop to run again")
        self._iteration_claimed = True
        return self._iterate()

    def _require_not_finished(self, action: str) -> None:
        if self._finished:
            raise RuntimeError(f"the AgentLoop run has finished; cannot {action}")

    async def _iterate(self) -> AsyncIterator[AgentLoopEvent]:
        try:
            while True:
                follow_ups = self._drain_follow_ups()
                if not follow_ups:
                    break
                terminated = False
                async for event in self._run_turn(follow_ups):
                    yield event
                    if isinstance(event, AgentLoopTurn) and event.termination == "tool_terminated":
                        terminated = True
                if terminated:
                    break
            if not self._steering_queue.empty():
                raise AgentLoopStranded("steering was queued but never preceded a generation")
        finally:
            self._finished = True

    def _drain_follow_ups(self) -> list[str]:
        if self._options.follow_up_drain == "one-by-one":
            if self._follow_up_queue.empty():
                return []
            return [self._follow_up_queue.get_nowait()]
        drained = []
        while not self._follow_up_queue.empty():
            drained.append(self._follow_up_queue.get_nowait())
        return drained

    async def _run_turn(self, follow_ups: list[str]) -> AsyncIterator[AgentLoopEvent]:
        messages: list[SessionMessage] = []
        for text in follow_ups:
            user_message = await self._model.add_user_message(text)
            messages.append(user_message)
            yield user_message
        generations = 0
        tool_executions: list[ToolExecution] = []
        while True:
            max_generations = self._options.max_generations
            if max_generations is not None and self._generations_used >= max_generations:
                raise AgentLoopExhausted(
                    f"max_generations={max_generations} reached before another generate()"
                )
            for message in await self._drain_steering():
                messages.append(message)
                yield message
            assistant = await self._model.generate()
            self._generations_used += 1
            generations += 1
            messages.append(assistant)
            yield assistant
            if assistant.stop_reason != "tool_call" or not assistant.tool_calls:
                yield AgentLoopTurn(
                    messages=messages,
                    assistant_message=assistant,
                    tool_executions=tool_executions,
                    generations=generations,
                    termination="final_response",
                )
                return
            terminated = False
            for call in assistant.tool_calls:
                result = await self._execute_call(call)
                tool_executions.append(
                    ToolExecution(tool_call_id=call.id, tool_name=call.tool_name, result=result)
                )
                feedback = await self._model.add_tool_result_message(call.id, result.text)
                messages.append(feedback)
                yield feedback
                terminated = terminated or result.terminate
            if terminated:
                yield AgentLoopTurn(
                    messages=messages,
                    assistant_message=assistant,
                    tool_executions=tool_executions,
                    generations=generations,
                    termination="tool_terminated",
                )
                return

    async def _drain_steering(self) -> list[UserMessage]:
        if self._steering_queue.empty():
            return []
        if self._options.steering_drain == "one-by-one":
            texts = [self._steering_queue.get_nowait()]
        else:
            texts = []
            while not self._steering_queue.empty():
                texts.append(self._steering_queue.get_nowait())
        drained = []
        for text in texts:
            drained.append(await self._model.add_user_message(text))
        return drained

    async def _execute_call(self, call: ToolCall) -> AgentToolResult:
        if (before_hook := self._hooks.before_tool_call) is not None:
            decision = await before_hook(call)
            if decision.action == "deny":
                reason = decision.reason or f"tool {call.tool_name!r} denied"
                return AgentToolResult(text=reason, is_error=True)
        tool = self._tools_by_name.get(call.tool_name)
        if tool is None:
            return AgentToolResult(text=f"unknown tool: {call.tool_name!r}", is_error=True)
        try:
            result = await tool.execute(call.parameters)
        except Exception as error:
            return AgentToolResult(
                text=f"tool {call.tool_name!r} raised {type(error).__name__}: {error}",
                is_error=True,
            )
        if (result_hook := self._hooks.tool_result) is not None:
            result = await result_hook(call, result)
        return result
