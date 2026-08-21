from collections.abc import Mapping

from otter_ai_core.auth_storage import AuthStorage
from otter_ai_core.model import ModelFactory

from .signature import Provider


class ModelRegistry:
    def __init__(self, providers: Mapping[str, Provider], auth_storage: AuthStorage) -> None:
        raise NotImplementedError

    def get_model_factory(self, provider: str, model: str) -> ModelFactory:
        raise NotImplementedError
