from collections.abc import Sequence
from types import TracebackType
from typing import Any, Self

from pydantic import BaseModel

from otter_ai_core.abstractions import Model, ModelFactory, ToolSpec
from otter_ai_core.agent_session import AgentSession, AgentSessionEvent
from otter_ai_core.fake_model import FakeModel
from otter_ai_core.in_memory_auth_storage import InMemoryAuthStorage
from otter_ai_core.in_memory_session import InMemorySessionManager
from otter_ai_core.model_registry import ModelRegistry
from otter_ai_core.types import (
    AgentToolResult,
    AssistantMessage,
    SessionMessage,
    TextContent,
    ToolCall,
    UserMessage,
)


def _user_message(text: str) -> UserMessage:
    return UserMessage(id=f"user-{text}", content=[TextContent(text=text)])


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        id="assistant-1",
        content=[TextContent(text="reply")],
        tool_calls=[],
        stop_reason="final_response",
    )


def _final_response(text: str) -> AssistantMessage:
    return AssistantMessage(
        id=f"assistant-{text}",
        content=[TextContent(text=text)],
        tool_calls=[],
        stop_reason="final_response",
    )


def _tool_call_response(tool_name: str = "ping") -> AssistantMessage:
    return AssistantMessage(
        id="assistant-tool",
        content=[TextContent(text="calling")],
        tool_calls=[ToolCall(id="call-1", tool_name=tool_name, parameters={})],
        stop_reason="tool_call",
    )


class _NoopParameters(BaseModel):
    pass


class NoopTool:
    """Trivial AgentTool: returns 'ok'; takes no arguments."""

    @property
    def name(self) -> str:
        return "noop"

    @property
    def description(self) -> str:
        return "Does nothing."

    @property
    def parameters(self) -> type[BaseModel]:
        return _NoopParameters

    async def execute(self, arguments: dict[str, Any]) -> AgentToolResult:
        return AgentToolResult(text="ok")


def _noop_tool() -> NoopTool:
    return NoopTool()


class RecordingModelFactory:
    """ModelFactory fake: records every call and yields a FakeModel scripted
    with the given responses (or a pre-built model)."""

    def __init__(self, responses: Sequence[AssistantMessage]) -> None:
        self.calls: list[tuple[str, list[ToolSpec], list[SessionMessage]]] = []
        self._responses = list(responses)
        self._model: Model | None = None

    @classmethod
    def for_model(cls, model: Model) -> Self:
        factory = cls([])
        factory._model = model
        return factory

    def __call__(
        self,
        system_prompt: str,
        tools: list[ToolSpec],
        initial_messages: Sequence[SessionMessage],
    ) -> Model:
        self.calls.append((system_prompt, list(tools), list(initial_messages)))
        if self._model is not None:
            return self._model
        return FakeModel(self._responses)


class StubProvider:
    """Provider fake that always resolves the given factory."""

    def __init__(self, factory: ModelFactory) -> None:
        self._factory = factory

    def get_model_factory(self, model: str, api_key: str) -> ModelFactory:
        return self._factory


class LifecycleSpySessionManager:
    """InMemorySessionManager wrapper that records open/close lifecycle
    calls, for asserting the session's enter/exit wiring."""

    def __init__(self, inner: InMemorySessionManager) -> None:
        self._inner = inner
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> Self:
        self.entered += 1
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited += 1
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def append_message(self, message: SessionMessage) -> None:
        await self._inner.append_message(message)

    async def get_messages(self) -> Sequence[SessionMessage]:
        return await self._inner.get_messages()

    @property
    def entries(self) -> Sequence[SessionMessage]:
        return self._inner.entries


async def seeded_storage(*entries: tuple[str, str]) -> InMemoryAuthStorage:
    storage = InMemoryAuthStorage()
    for provider, api_key in entries:
        await storage.add_api_key(provider, api_key)
    return storage


async def _make_session(
    session_manager: InMemorySessionManager | LifecycleSpySessionManager,
    factory: ModelFactory,
) -> AgentSession:
    registry = ModelRegistry(
        {"openai": StubProvider(factory)},
        await seeded_storage(("openai", "sk-key")),
    )
    return AgentSession(
        model="gpt-4o",
        provider="openai",
        system_prompt="system",
        tools=[],
        session_manager=session_manager,
        model_registry=registry,
    )


async def collect_events(session: AgentSession) -> list[AgentSessionEvent]:
    """Drains the session's channel to a list; ends when the session exits."""
    return [event async for event in session]
