"""Conversations with the models of Z.ai's coding plan."""

import httpx2
from openai import AsyncOpenAI

from otter.conversation import ConversationFactory
from otter.openai_chat_completions_compatible import OpenAIChatCompletionsCompatibleConversation


def create_zai_coding_plan_conversations(
    api_key: str, *, http_client: httpx2.AsyncClient | None = None
) -> ConversationFactory:
    """Return a factory of conversations with Z.ai coding plan models.

    Every conversation it starts shares one connection to Z.ai, authenticated with
    `api_key`. The coding plan takes text only, so images and audio are not sent: the
    model gets a short note in their place. `http_client` is what requests are sent
    through; leave it out to reach Z.ai over the network.
    """
    client = AsyncOpenAI(
        base_url="https://api.z.ai/api/coding/paas/v4", api_key=api_key, http_client=http_client
    )
    # The coding plan endpoint accepts text only: it answers anything else with a 400.
    return lambda model, *, system=None, tools=(): OpenAIChatCompletionsCompatibleConversation(
        client, model, system=system, tools=tools, supports_images=False, supports_audio=False
    )
