from collections.abc import Mapping

from otter_ai_core.abstractions import AuthStorage, ModelFactory, Provider


class ModelRegistry:
    """Resolves a provider name and model name into a model factory bound to
    the provider's stored API key.

    Constructed with an initial provider mapping and an auth storage; the
    storage must hold a key for a provider before models can be resolved
    from it."""

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
        """Resolves the provider and model freshly on every call, using the
        provider's stored API key.

        Raises KeyError naming the provider when no provider is registered
        under the name; KeyError naming both provider and model when the
        provider does not know the model; and the auth storage's KeyError
        naming the provider when no API key is stored for it."""
        if provider not in self._providers:
            raise KeyError(f"Unknown provider: {provider}")
        api_key = await self._auth_storage.get_api_key(provider)
        try:
            return self._providers[provider].get_model_factory(model, api_key)
        except KeyError as exc:
            raise KeyError(f"Unknown model for provider: {provider}/{model}: {exc}") from exc
