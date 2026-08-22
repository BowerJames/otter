from collections.abc import Mapping

from otter_ai_core.auth_storage import AuthStorage

from .model import ModelFactory
from .provider import Provider


class ModelRegistry:
    def __init__(self, providers: Mapping[str, Provider], auth_storage: AuthStorage) -> None:
        self._providers = providers
        self._auth_storage = auth_storage

    async def get_model_factory(self, provider: str, model: str) -> ModelFactory:
        if provider not in self._providers:
            raise KeyError(f"Unknown provider: {provider}")
        api_key = await self._auth_storage.get_api_key(provider)
        try:
            return self._providers[provider].get_model_factory(model, api_key)
        except KeyError as exc:
            raise KeyError(f"Unknown model for provider: {provider}/{model}: {exc}") from exc
