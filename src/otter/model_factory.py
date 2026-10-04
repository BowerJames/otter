"""The models otter can reach out of the box."""

from collections.abc import Mapping
from typing import Protocol

import httpx2

from otter.auth_resolver import ApiKey, Provider
from otter.conversation import ConversationFactory
from otter.model import Model, ModelConfig, ModelFactory, ModelType
from otter.openai_chat_completions import create_openai_conversations
from otter.openai_responses import create_openai_responses_conversations
from otter.zai_chat_completions import create_zai_coding_plan_conversations
from otter.zai_responses import create_zai_coding_plan_responses_conversations


class _ConversationsOfProvider(Protocol):
    def __call__(
        self, api_key: str, *, http_client: httpx2.AsyncClient | None = None
    ) -> ConversationFactory: ...


_PROVIDERS_OF_MODEL_TYPE: Mapping[ModelType, Mapping[Provider, _ConversationsOfProvider]] = {
    "chat-completions": {
        "openai": create_openai_conversations,
        "zai": create_zai_coding_plan_conversations,
    },
    "responses": {
        "openai": create_openai_responses_conversations,
        "zai": create_zai_coding_plan_responses_conversations,
    },
}


def create_model_factory(http_client: httpx2.AsyncClient | None = None) -> ModelFactory:
    """Return a factory of the models otter knows how to reach.

    The model types "chat-completions" and "responses" are each served by the providers
    "openai" and "zai" (Z.ai's coding plan). The factory raises `ValueError` for any
    other model type, and for a provider that does not serve the model type.
    `http_client` is what requests are sent through; leave it out to reach providers
    over the network.
    """

    def create_model(model_config: ModelConfig, api_key: ApiKey) -> Model:
        model_type, provider = model_config.model_type, model_config.provider
        if model_type not in _PROVIDERS_OF_MODEL_TYPE:
            raise ValueError(f"unknown model type {model_type!r}")
        providers = _PROVIDERS_OF_MODEL_TYPE[model_type]
        if provider not in providers:
            raise ValueError(f"provider {provider!r} does not serve {model_type!r} models")
        create_conversation = providers[provider](api_key, http_client=http_client)
        name = model_config.model_name
        return lambda system, tools: create_conversation(name, system=system, tools=tools)

    return create_model
