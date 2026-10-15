"""A model served over an OpenAI-compatible chat completions endpoint."""

from openai import AsyncOpenAI, omit

from otter.core.domain.messages import AssistantMessage
from otter.core.model import ModelInput, ModelPort

from .wire import messages_of, tools_of, turn_of


class OpenAIChatCompletionsAdapter(ModelPort):
    """The model `model_name`, served over the chat completions endpoint `client` reaches.

    The client decides which provider that is (its base URL and API key): any provider
    serving the chat completions format will do. The whole input is sent with each turn,
    and nothing is held open between turns. The client is not the adapter's to close.
    """

    def __init__(self, client: AsyncOpenAI, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        """Send `model_input` and return the turn the model replies with.

        Thinking in the context is not sent: the format has no place for it. Tool
        arguments the model wrote that are not valid JSON raise `json.JSONDecodeError`.
        """
        completion = await self._client.chat.completions.create(
            model=self._model_name,
            messages=messages_of(model_input),
            tools=tools_of(model_input.tools) or omit,
        )
        return turn_of(completion.choices[0].message)
