from otter.core.model import ModelPort
from otter.infrastructure.adapters.model.openai_realtime import (
    OpenAIConnect,
    OpenAIRealtimeAdapter,
)


def create_openai_realtime_adapter(model_name: str, api_key: str) -> ModelPort:
    """Return the model `model_name`, served over OpenAI's realtime endpoint."""
    return OpenAIRealtimeAdapter(OpenAIConnect(api_key), model_name)
