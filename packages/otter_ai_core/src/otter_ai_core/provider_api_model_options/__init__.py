"""Provider/api/model-option subpackage facade.

This package groups the small pure-data enums and the
:class:`ProviderModelOption` bundle that the provider/dispatch layer
(:mod:`otter_ai_assistant_provider_stream`) keys its routing on:

* :class:`KnownApis` — the api shape to dispatch through
  (``chat-completions`` / ``responses`` / ``realtime``).
* :class:`KnownProviders` — the providers with built-in catalog + env support
  (``openai`` / ``zai``).
* :class:`ThinkingLevel` — the off switch plus the five reasoning-effort
  levels (mirrors pi-ai's ``ModelThinkingLevel``).
* :class:`ProviderModelOption` — the caller's selection of a model + per-call
  config; realises the ``TOptions`` of
  :data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` for the
  dispatch layer.

It is a supported import surface (Strategy A — two-layer facade): callers may
import from :mod:`otter_ai_core.provider_api_model_options`. The public
surface is declared via :data:`__all__`. Core defines the types only — no
dispatch, registry, catalog, or transport lives here.
"""

from .apis import KnownApis
from .provider_model_options import ProviderModelOption
from .providers import KnownProviders
from .thinking_level import ThinkingLevel

__all__ = [
    "KnownApis",
    "KnownProviders",
    "ProviderModelOption",
    "ThinkingLevel",
]
