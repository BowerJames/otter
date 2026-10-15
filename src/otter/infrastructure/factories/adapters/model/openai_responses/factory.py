import httpx2
from openai import AsyncOpenAI

from otter.core.model import ModelPort
from otter.infrastructure.adapters.model.openai_responses import OpenAIResponsesAdapter


def create_openai_responses_adapter(
    model_name: str,
    api_key: str,
    *,
    base_url: str,
    http_client: httpx2.AsyncClient | None = None,
) -> ModelPort:
    """Return the model `model_name`, served over the responses endpoint at `base_url`.

    `http_client` is what requests are sent through; leave it out to send them over the
    network.
    """
    return OpenAIResponsesAdapter(
        AsyncOpenAI(base_url=base_url, api_key=api_key, http_client=http_client), model_name
    )
