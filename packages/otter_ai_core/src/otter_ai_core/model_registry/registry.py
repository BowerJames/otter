from collections.abc import Callable

from otter_ai_core.abstractions import AgentTool, Model

# A function that will resolve a system prompt and agent tools returning a model adapter
type ModelFactory = Callable[[str, list[AgentTool]], Model]

# A function that will resolve a model name and api key and return a model factory.
type ProviderFn = Callable[[str, str], ModelFactory]

# A function that will resolve only an api key to return a model factoy
type CustomModelFn = Callable[[str], ModelFactory]


class ModelRegistry:
    """
    A registry for storing factories for many Model adapters.
    Supports provider level factories which would provide common builders for a given
    provider allowing the model name and api key to vary as they wish.
    Supports model level factories which provide builders that only require a specific api key.
    """

    def add_provider(self, provider: str, provider_fn: ProviderFn) -> None:
        """
        Add a provider level builder to the registry that is keyed on the `provider` string.
        Will replace an existing one if called with a provider already in the registry.
        """
        raise NotImplementedError

    def add_custom_model(self, model: str, custom_model_fn: CustomModelFn) -> None:
        """
        Add a model level builder to the registry that is keyed on the model string.
        Will replace an existing one if called with a model already in the registry.
        """
        raise NotImplementedError

    def get_model(self, api_key: str, model: str, provider: str | None) -> ModelFactory:
        """
        Resolves the (provider, model) pair in to the correct model factory.
        If provider is `None` it will attempt to resolve against the standalone custom models.
        If provider a string it will look for a provider builder.
        """
        raise NotImplementedError
