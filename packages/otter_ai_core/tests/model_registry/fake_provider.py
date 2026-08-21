from otter_ai_core.fake_model import FakeModel
from otter_ai_core.model import ModelFactory


class FakeProvider:
    def __init__(self, known_models: set[str] | None = None) -> None:
        self._known_models = known_models
        self.received: tuple[str, str] | None = None
        self._factory: ModelFactory = lambda system_prompt, tools: FakeModel([])

    def set_returned_factory(self, factory: ModelFactory) -> None:
        self._factory = factory

    def get_model_factory(self, model: str, api_key: str) -> ModelFactory:
        if self._known_models is not None and model not in self._known_models:
            raise KeyError(f"Unknown model for provider: {model}")
        self.received = (model, api_key)
        return self._factory
