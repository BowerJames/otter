"""Behaviour of create_agent_session, observed at a fake model factory and its fake model."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from otter.agent_session import AssistantTurn, Idle, UserTurn
from otter.conversation import Conversation
from otter.create_agent_session import create_agent_session
from otter.messages import AssistantMessage, TextPart, ToolSpec, UserPart
from otter.model import Model, ModelConfig


@dataclass(frozen=True)
class Config:
    model_name: str
    model_type: str
    provider: str


GLM = Config("glm-5.3", "chat-completions", "zai")


class Echo:
    """A tool the model is told about; these tests never have it run."""

    name = "echo"
    description = "Repeat the text"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }

    async def execute(self, args: Mapping[str, object]) -> str:
        return str(args["text"])


class FakeModels:
    """A test adapter for the model factory: records what each model was made for and
    what its conversation was started with, and answers every prompt with "OK".
    """

    def __init__(self) -> None:
        self.made: list[tuple[ModelConfig, str]] = []
        self.started: list[tuple[str | None, list[ToolSpec]]] = []
        self.user_messages: list[tuple[UserPart, ...]] = []

    def __call__(self, model_config: ModelConfig, api_key: str) -> Model:
        self.made.append((model_config, api_key))
        return self._start_conversation

    def _start_conversation(self, system: str | None, tools: Sequence[ToolSpec]) -> Conversation:
        self.started.append((system, list(tools)))
        return self

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        self.user_messages.append(tuple(content))

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        raise AssertionError("no tool is asked for in these tests")

    async def generate(self) -> AssistantMessage:
        return AssistantMessage(content=(TextPart("OK"),))


@pytest.fixture
def models() -> FakeModels:
    return FakeModels()


def key_for(provider: str) -> str:
    return f"{provider}-key"


def test_the_model_is_made_for_the_configuration_with_its_providers_key(
    models: FakeModels,
) -> None:
    create_agent_session("Be brief.", [], GLM, auth_resolver=key_for, model_factory=models)

    assert models.made == [(GLM, "zai-key")]


def test_the_models_conversation_is_started_with_the_system_prompt_and_tools(
    models: FakeModels,
) -> None:
    create_agent_session("Be brief.", [Echo()], GLM, auth_resolver=key_for, model_factory=models)

    assert models.started == [
        (
            "Be brief.",
            [
                ToolSpec(
                    name="echo",
                    description="Repeat the text",
                    parameters={"type": "object", "properties": {"text": {"type": "string"}}},
                )
            ],
        )
    ]


async def test_the_session_puts_prompts_to_the_model_and_reports_its_answers(
    models: FakeModels,
) -> None:
    session = create_agent_session(
        "Be brief.", [], GLM, auth_resolver=key_for, model_factory=models
    )
    session.prompt("Hello")

    stream = session.stream()
    events = [await anext(stream), await anext(stream), await anext(stream)]

    assert models.user_messages == [(TextPart("Hello"),)]
    assert events == [
        UserTurn((TextPart("Hello"),)),
        AssistantTurn(AssistantMessage(content=(TextPart("OK"),))),
        Idle(),
    ]


def test_a_key_that_cannot_be_resolved_propagates_and_no_model_is_made(
    models: FakeModels,
) -> None:
    def no_key(provider: str) -> str:
        raise LookupError(f"no key for {provider}")

    with pytest.raises(LookupError, match=r"^no key for zai$"):
        create_agent_session("Be brief.", [], GLM, auth_resolver=no_key, model_factory=models)

    assert models.made == []
