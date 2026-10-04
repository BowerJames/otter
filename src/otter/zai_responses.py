"""Conversations with the models of Z.ai's coding plan, over its responses endpoint."""

import httpx2
from openai import AsyncOpenAI

from otter.conversation import ConversationFactory
from otter.openai_responses_compatible import OpenAIResponsesCompatibleConversation


def create_zai_coding_plan_responses_conversations(
    api_key: str, *, http_client: httpx2.AsyncClient | None = None
) -> ConversationFactory:
    """Return a factory of conversations with Z.ai coding plan models.

    Every conversation it starts shares one connection to Z.ai, authenticated with
    `api_key`. The coding plan takes text only, so images and audio are not sent: the
    model gets a short note in their place. `http_client` is what requests are sent
    through; leave it out to reach Z.ai over the network.
    """
    client = AsyncOpenAI(
        base_url="https://api.z.ai/api/v1", api_key=api_key, http_client=http_client
    )
    # The endpoint accepts an image but drops it before the model, without saying so.
    return lambda model, *, system=None, tools=(): OpenAIResponsesCompatibleConversation(
        client, model, system=system, tools=tools, supports_images=False
    )
