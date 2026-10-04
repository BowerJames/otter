"""Conversations with OpenAI's own models, over its responses endpoint."""

import httpx2
from openai import AsyncOpenAI

from otter.conversation import ConversationFactory
from otter.openai_responses_compatible import OpenAIResponsesCompatibleConversation


def create_openai_responses_conversations(
    api_key: str, *, http_client: httpx2.AsyncClient | None = None
) -> ConversationFactory:
    """Return a factory of conversations with OpenAI models.

    Every conversation it starts shares one connection to OpenAI, authenticated with
    `api_key`. Images are sent to the model; audio is not, since the responses endpoint
    has no place for it: the model gets a short note instead. `http_client` is what
    requests are sent through; leave it out to reach OpenAI over the network.
    """
    # The base URL is given outright: left out, the client would take it from the environment.
    client = AsyncOpenAI(
        base_url="https://api.openai.com/v1", api_key=api_key, http_client=http_client
    )
    return lambda model, *, system=None, tools=(), context=(): (
        OpenAIResponsesCompatibleConversation(
            client, model, system=system, tools=tools, context=context
        )
    )
