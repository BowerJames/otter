"""A model served over an OpenAI-compatible responses endpoint."""

from openai import AsyncOpenAI, omit
from openai.types.responses import ResponseInputItemParam

from otter.core.domain.messages import AssistantMessage, ContextEntry
from otter.core.model import ModelInput, ModelPort

from .wire import items_of, output_items_of, tools_of, turn_of


class OpenAIResponsesAdapter(ModelPort):
    """The model `model_name`, served over the responses endpoint `client` reaches.

    The client decides which provider that is (its base URL and API key): any provider
    serving the responses format will do. The whole input is sent with each turn, and
    the provider is asked to keep none of it.

    The model's own turns are sent back exactly as it produced them, reasoning
    included, for as long as the context goes on from the turn before. Turns it did not
    produce here are sent as their text and tool calls: the format has no place for
    thinking it did not produce itself. The client is not the adapter's to close.
    """

    def __init__(self, client: AsyncOpenAI, model_name: str) -> None:
        self._client = client
        self._model_name = model_name
        # Each entry of the last context sent, with the items it was sent as, and the
        # turn the model then produced, with the items it produced.
        self._sent: list[tuple[ContextEntry, list[ResponseInputItemParam]]] = []

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        """Send `model_input` and return the turn the model produces.

        Audio is sent as a note: the format has no place for it. A response reporting
        that the model failed raises `ModelFailed`; tool arguments the model wrote that
        are not valid JSON raise `json.JSONDecodeError`.
        """
        sent = self._items_of(model_input.context)
        response = await self._client.responses.create(
            model=self._model_name,
            input=[item for _, items in sent for item in items],
            instructions=model_input.system if model_input.system is not None else omit,
            tools=tools_of(model_input.tools) or omit,
            store=False,
            # With nothing kept by the provider, reasoning can only be sent back in
            # this form.
            include=["reasoning.encrypted_content"],
        )
        turn = turn_of(response)
        self._sent = [*sent, (turn, output_items_of(response))]
        return turn

    def _items_of(
        self, context: tuple[ContextEntry, ...]
    ) -> list[tuple[ContextEntry, list[ResponseInputItemParam]]]:
        """Each entry of `context` with the items it is sent as, reusing those already sent."""
        reused = 0
        for (sent_entry, _), entry in zip(self._sent, context, strict=False):
            if sent_entry != entry:
                break
            reused += 1
        fresh = [(entry, items_of(entry)) for entry in context[reused:]]
        return [*self._sent[:reused], *fresh]
