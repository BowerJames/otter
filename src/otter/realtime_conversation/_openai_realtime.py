"""Conversations with OpenAI's own models, over its realtime endpoint."""

from openai import AsyncOpenAI

from ._openai_realtime_conversation import OpenAIRealtimeConversation
from ._realtime_conversation import RealtimeConversationFactory


def create_openai_realtime_conversations(
    api_key: str, *, voice: str | None = None
) -> RealtimeConversationFactory:
    """Return a factory of realtime conversations with OpenAI models.

    Each conversation it starts makes its own connection to OpenAI, authenticated with
    `api_key`, when its first turn is generated, and should be closed when done with.
    Given a `voice`, the models speak their turns in it; left out, they write them as
    text. Images carried inline and 16-bit mono 24 kHz wav audio are sent to the model;
    it gets a short note in place of anything else.
    """
    # The base URL is given outright: left out, the client would take it from the environment.
    client = AsyncOpenAI(base_url="https://api.openai.com/v1", api_key=api_key)
    return lambda model, *, system=None, tools=(), context=(): OpenAIRealtimeConversation(
        lambda model: client.realtime.connect(model=model),
        model,
        system=system,
        tools=tools,
        context=context,
        voice=voice,
    )
