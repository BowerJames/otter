"""The models otter can reach out of the box."""

from collections.abc import Mapping
from typing import Protocol

import httpx2

from otter.auth_resolver import ApiKey, Provider
from otter.conversation import (
    ConversationFactory,
    create_openai_conversations,
    create_openai_responses_conversations,
    create_zai_coding_plan_conversations,
    create_zai_coding_plan_responses_conversations,
    realtime_as_conversation,
)
from otter.realtime_conversation import RealtimeConnector, create_openai_realtime_conversations

from ._model import Model, ModelConfig, ModelFactory, ModelType


class _ConversationsOfProvider(Protocol):
    def __call__(
        self, api_key: str, *, http_client: httpx2.AsyncClient | None = None
    ) -> ConversationFactory: ...


def _openai_realtime_conversations(
    connector: RealtimeConnector | None,
) -> _ConversationsOfProvider:
    def create_conversations(
        api_key: str, *, http_client: httpx2.AsyncClient | None = None
    ) -> ConversationFactory:
        # A realtime model is reached over a websocket, which `http_client` has no part in.
        create_conversation = create_openai_realtime_conversations(api_key, connector=connector)
        return lambda model, *, system=None, tools=(), context=(): realtime_as_conversation(
            create_conversation(model, system=system, tools=tools, context=context)
        )

    return create_conversations


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


def create_model_factory(
    http_client: httpx2.AsyncClient | None = None,
    *,
    realtime_connector: RealtimeConnector | None = None,
) -> ModelFactory:
    """Return a factory of the models otter knows how to reach.

    The model types "chat-completions" and "responses" are each served by the providers
    "openai" and "zai" (Z.ai's coding plan), and "realtime" by "openai". The factory
    raises `ValueError` for any other model type, and for a provider that does not serve
    the model type. `http_client` is what requests are sent through; leave it out to
    reach providers over the network.

    A realtime model's turns are taken whole and as text. It is reached over a
    connection of its own, made when the conversation is entered and kept until it is
    left, which `http_client` has no part in: `realtime_connector` is
    what that connection is opened through; leave it out to reach providers over the
    network.
    """
    providers_of_model_type: Mapping[ModelType, Mapping[Provider, _ConversationsOfProvider]] = {
        **_PROVIDERS_OF_MODEL_TYPE,
        "realtime": {"openai": _openai_realtime_conversations(realtime_connector)},
    }

    def create_model(model_config: ModelConfig, api_key: ApiKey) -> Model:
        model_type, provider = model_config.model_type, model_config.provider
        if model_type not in providers_of_model_type:
            raise ValueError(f"unknown model type {model_type!r}")
        providers = providers_of_model_type[model_type]
        if provider not in providers:
            raise ValueError(f"provider {provider!r} does not serve {model_type!r} models")
        create_conversation = providers[provider](api_key, http_client=http_client)
        name = model_config.model_name
        return lambda system, tools, context: create_conversation(
            name, system=system, tools=tools, context=context
        )

    return create_model
