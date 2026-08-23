from collections.abc import Mapping

from otter_ai_core.auth_storage import AuthStorage

from .model.interface import ModelFactory
from .provider import Provider


class ModelRegistry:
    def __init__(self, providers: Mapping[str, Provider], auth_storage: AuthStorage) -> None:
        self._providers = dict(providers)
        self._auth_storage = auth_storage

    def add_provider(self, provider: str, impl: Provider) -> None:
        """Registers impl under the given provider name, replacing any
        existing provider registered under that name."""
        self._providers[provider] = impl

    def remove_provider(self, provider: str) -> None:
        """Removes the provider registered under the given name. Removing a
        name that is not registered is a no-op."""
        self._providers.pop(provider, None)

    async def get_model_factory(self, provider: str, model: str) -> ModelFactory:
        if provider not in self._providers:
            raise KeyError(f"Unknown provider: {provider}")
        api_key = await self._auth_storage.get_api_key(provider)
        try:
            return self._providers[provider].get_model_factory(model, api_key)
        except KeyError as exc:
            raise KeyError(f"Unknown model for provider: {provider}/{model}: {exc}") from exc
