from typing import Protocol

from otter_ai_core.model import ModelFactory


class Provider(Protocol):
    def get_model_factory(self, model: str, api_key: str) -> ModelFactory: ...
