"""The models otter can reach out of the box."""

from collections.abc import Mapping
from typing import Protocol

import httpx2

from otter.auth_resolver import ApiKey, Provider
from otter.conversation import ConversationFactory
from otter.model import Model, ModelConfig, ModelFactory
from otter.openai_chat_completions import create_openai_conversations
from otter.zai_chat_completions import create_zai_coding_plan_conversations


class _ConversationsOfProvider(Protocol):
    def __call__(
        self, api_key: str, *, http_client: httpx2.AsyncClient | None = None
    ) -> ConversationFactory: ...


_CHAT_COMPLETIONS_PROVIDERS: Mapping[Provider, _ConversationsOfProvider] = {
    "openai": create_openai_conversations,
    "zai": create_zai_coding_plan_conversations,
}


def create_model_factory(http_client: httpx2.AsyncClient | None = None) -> ModelFactory:
    """Return a factory of the models otter knows how to reach.

    The "chat-completions" model type is served by the providers "openai" and "zai"
    (Z.ai's coding plan). The factory raises `ValueError` for any other model type, and
    for a provider that does not serve the model type. `http_client` is what requests
    are sent through; leave it out to reach providers over the network.
    """

    def create_model(model_config: ModelConfig, api_key: ApiKey) -> Model:
        if model_config.model_type != "chat-completions":
            raise ValueError(f"unknown model type {model_config.model_type!r}")
        provider = model_config.provider
        if provider not in _CHAT_COMPLETIONS_PROVIDERS:
            raise ValueError(f"provider {provider!r} does not serve 'chat-completions' models")
        create_conversation = _CHAT_COMPLETIONS_PROVIDERS[provider](
            api_key, http_client=http_client
        )
        name = model_config.model_name
        return lambda system, tools: create_conversation(name, system=system, tools=tools)

    return create_model
