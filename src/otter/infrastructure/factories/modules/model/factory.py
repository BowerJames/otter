import httpx2

from otter.core.model import Model, ModelImpl
from otter.infrastructure.factories.adapters.model.openai_chat_completions import (
    create_openai_chat_completions_adapter,
)
from otter.infrastructure.factories.adapters.model.openai_realtime import (
    create_openai_realtime_adapter,
)
from otter.infrastructure.factories.adapters.model.openai_responses import (
    create_openai_responses_adapter,
)

_OPENAI = "https://api.openai.com/v1"
_ZAI = "https://api.z.ai/api/v1"
_ZAI_CODING_PLAN = "https://api.z.ai/api/coding/paas/v4"


def create_model(
    model_type: str,
    provider: str,
    model_name: str,
    api_key: str,
    *,
    http_client: httpx2.AsyncClient | None = None,
) -> Model:
    """Return the model `model_name`, reached with `api_key`.

    `model_type` is how it is spoken to, and `provider` who serves it:
    "chat-completions" is served by "openai" and "zai" (Z.ai's coding plan),
    "responses" by "openai" and "zai", and "realtime" by "openai". Any other pairing
    raises `ValueError`.

    `http_client` is what requests are sent through; leave it out to send them over the
    network. A realtime model is reached over a connection of its own, which
    `http_client` has no part in.
    """
    match model_type, provider:
        case "chat-completions", "openai":
            # Only OpenAI's audio models take audio in: the rest answer it with a 400.
            port = create_openai_chat_completions_adapter(
                model_name, api_key, base_url=_OPENAI, http_client=http_client
            )
            return ModelImpl(port, accepts_images=True, accepts_audio=False)
        case "chat-completions", "zai":
            # The coding plan takes text alone: it answers anything else with a 400.
            port = create_openai_chat_completions_adapter(
                model_name, api_key, base_url=_ZAI_CODING_PLAN, http_client=http_client
            )
            return ModelImpl(port, accepts_images=False, accepts_audio=False)
        case "responses", "openai":
            port = create_openai_responses_adapter(
                model_name, api_key, base_url=_OPENAI, http_client=http_client
            )
            return ModelImpl(port, accepts_images=True, accepts_audio=False)
        case "responses", "zai":
            port = create_openai_responses_adapter(
                model_name, api_key, base_url=_ZAI, http_client=http_client
            )
            return ModelImpl(port, accepts_images=False, accepts_audio=False)
        case "realtime", "openai":
            port = create_openai_realtime_adapter(model_name, api_key)
            return ModelImpl(port, accepts_images=True, accepts_audio=True)
        case _:
            raise ValueError(f"provider {provider!r} serves no {model_type!r} models")
