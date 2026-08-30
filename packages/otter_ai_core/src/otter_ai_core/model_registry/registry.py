from collections.abc import Callable

from otter_ai_core.abstractions import AgentTool, Model

# Nominal aliases over `str` naming the positional parameters of the factory
# callables below. Module-private documentation vocabulary: nothing outside
# this module should import them; they are transparent to the type checker.
type _SystemPrompt = str
type _ProviderName = str
type _ModelName = str
type _ApiKey = str

# A function that will resolve a system prompt and agent tools returning a model adapter
type _ModelFactory = Callable[[_SystemPrompt, list[AgentTool]], Model]

# A function that will resolve a model name and api key and return a model factory.
type _ProviderFn = Callable[[_ModelName, _ApiKey], _ModelFactory]

# A function that will resolve only an api key to return a model factory
type _CustomModelFn = Callable[[_ApiKey], _ModelFactory]


class UnknownModelError(Exception):
    """Raised by ModelRegistry.get_model when a resolution path has no
    registration for the requested keys. The message names the missing
    key(s) and the resolution path taken."""


class ModelRegistry:
    """A registry for storing factories for many Model adapters.

    Supports provider level factories which provide common builders for a
    given provider, allowing the model name and api key to vary as they wish.
    Supports model level factories which provide builders that only require a
    specific api key.

    The two kinds are independent namespaces: get_model consults exactly one
    of them, selected by its `provider` argument, with no fallback between
    them. Keys are matched exactly. Resolution failures raise
    UnknownModelError."""

    def add_provider(self, provider: _ProviderName, provider_fn: _ProviderFn) -> None:
        """
        Add a provider level builder to the registry, keyed on the exact
        `provider` string. Registering under a provider already present
        replaces it; the most recent registration wins.
        """
        raise NotImplementedError

    def add_custom_model(self, model: _ModelName, custom_model_fn: _CustomModelFn) -> None:
        """
        Add a model level builder to the registry, keyed on the exact `model`
        string. Registering under a model already present replaces it; the
        most recent registration wins.
        """
        raise NotImplementedError

    def get_model(
        self, provider: _ProviderName | None, model: _ModelName, api_key: _ApiKey
    ) -> _ModelFactory:
        """
        Resolve `(provider, model, api_key)` to the correct model factory.

        The resolution path is selected by `provider`:
        - provider is a string: resolve against registered providers. The
          provider fn is invoked with (model, api_key) and its factory returned.
        - provider is None: resolve against registered custom models. The
          custom model fn is invoked with (api_key) and its factory returned.

        There is no fallback between paths: a string provider that is not
        registered raises UnknownModelError even if a custom model of the same
        name exists, and vice versa. Re-registration takes effect immediately
        for subsequent calls.
        """
        raise NotImplementedError
