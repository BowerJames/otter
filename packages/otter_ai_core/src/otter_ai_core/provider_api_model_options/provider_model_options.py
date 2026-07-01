from __future__ import annotations

from pydantic import BaseModel

from .apis import KnownApis
from .providers import KnownProviders
from .thinking_level import ThinkingLevel


class ProviderModelOption(BaseModel):
    """The caller's selection of a model + per-call reasoning config.

    Pure data: it identifies a catalog model by ``(provider, model)`` plus the
    api to dispatch it through, the api key, and a thinking level. It realises
    the ``TOptions`` of
    :data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` for the
    provider/dispatch layer
    (:mod:`otter_ai_assistant_provider_stream`).

    No runtime handles (hooks) and no per-call request overrides live here —
    by design (the dispatch layer uses default hooks and applies no overrides
    on top of catalog facts). The abort signal is the producer's second
    argument (an :class:`asyncio.Event`), never part of this bundle.
    """

    model: str
    provider: KnownProviders
    api: KnownApis
    api_key: str | None = None
    thinking_level: ThinkingLevel = ThinkingLevel.Low
