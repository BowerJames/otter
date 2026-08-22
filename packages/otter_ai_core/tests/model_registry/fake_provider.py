from otter_ai_core.agent_tool import AgentTool
from otter_ai_core.conversation import AssistantMessage, TextContent
from otter_ai_core.fake_model import FakeModel
from otter_ai_core.model_registry import EnterableModel, ModelFactory


def _scripted_model(system_prompt: str, tools: list[AgentTool]) -> EnterableModel:
    return FakeModel(
        [
            AssistantMessage(
                id="fake-provider-response",
                content=[TextContent(text="hello")],
                tool_calls=[],
                stop_reason="final_response",
            )
        ]
    )


class FakeProvider:
    def __init__(self, known_models: set[str] | None = None) -> None:
        self._known_models = known_models
        self.received: tuple[str, str] | None = None
        self._factory: ModelFactory = _scripted_model

    def set_returned_factory(self, factory: ModelFactory) -> None:
        self._factory = factory

    @property
    def returned_factory(self) -> ModelFactory:
        return self._factory

    def get_model_factory(self, model: str, api_key: str) -> ModelFactory:
        if self._known_models is not None and model not in self._known_models:
            raise KeyError(f"Unknown model for provider: {model}")
        self.received = (model, api_key)
        return self._factory
