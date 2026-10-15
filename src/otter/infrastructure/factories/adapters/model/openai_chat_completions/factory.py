import httpx2
from openai import AsyncOpenAI

from otter.core.model import ModelPort
from otter.infrastructure.adapters.model.openai_chat_completions import (
    OpenAIChatCompletionsAdapter,
)


def create_openai_chat_completions_adapter(
    model_name: str,
    api_key: str,
    *,
    base_url: str,
    http_client: httpx2.AsyncClient | None = None,
) -> ModelPort:
    """Return the model `model_name`, served over the chat completions endpoint at `base_url`.

    `http_client` is what requests are sent through; leave it out to send them over the
    network.
    """
    return OpenAIChatCompletionsAdapter(
        AsyncOpenAI(base_url=base_url, api_key=api_key, http_client=http_client), model_name
    )
