"""Conversations with OpenAI's own models, over its realtime endpoint."""

from collections.abc import Callable

from openai import AsyncOpenAI

from ._openai_realtime_conversation import OpenAIRealtimeConversation, RealtimeConnect
from ._realtime_conversation import RealtimeConversationFactory

type RealtimeConnector = Callable[[str], RealtimeConnect]
"""Returns what opens connections to a realtime endpoint, authenticated with the given API key."""


def _connect_to_openai(api_key: str) -> RealtimeConnect:
    # The base URL is given outright: left out, the client would take it from the environment.
    client = AsyncOpenAI(base_url="https://api.openai.com/v1", api_key=api_key)
    return lambda model: client.realtime.connect(model=model)


def create_openai_realtime_conversations(
    api_key: str, *, voice: str | None = None, connector: RealtimeConnector | None = None
) -> RealtimeConversationFactory:
    """Return a factory of realtime conversations with OpenAI models.

    Each conversation it starts makes its own connection to OpenAI, authenticated with
    `api_key`, when it is entered, and closes it when it is left.
    Given a `voice`, the models speak their turns in it; left out, they write them as
    text. Images carried inline and 16-bit mono 24 kHz wav audio are sent to the model;
    it gets a short note in place of anything else. `connector` is what connections are
    opened through; leave it out to reach OpenAI over the network.
    """
    connect = (connector or _connect_to_openai)(api_key)
    return lambda model, *, system=None, tools=(), context=(): OpenAIRealtimeConversation(
        connect, model, system=system, tools=tools, context=context, voice=voice
    )
