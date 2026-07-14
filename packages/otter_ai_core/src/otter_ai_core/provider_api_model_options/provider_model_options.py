from __future__ import annotations

from pydantic import BaseModel

from .apis import KnownApis
from .providers import KnownProviders
from .thinking_level import ThinkingLevel


class ProviderModelOption(BaseModel):
    """The caller's selection of a model + per-call reasoning config.

    Pure data: it identifies a catalog model by ``(provider, model)`` plus the
    api to dispatch it through, the api key, and a thinking level. It is the
    caller's options bundle — realising the ``TOptions`` of the dispatch
    layer's producer seam (:data:`otter_ai_core.builder.BuilderFn`).
    """

    model: str
    provider: KnownProviders
    api: KnownApis
    api_key: str | None = None
    thinking_level: ThinkingLevel = ThinkingLevel.Low
