"""otter-ai-assistant-provider-stream — provider/dispatch layer for otter-ai-core.

This package adds the dispatch layer :mod:`otter_ai_core` deliberately omits:

* a built-in model catalog (chat-completions models generated from models.dev,
  plus a hand-curated realtime catalog);
* env-key resolution (explicit > env > raise for chat; explicit > env for
  realtime);
* thinking-level clamping (port of pi-ai's ``clampThinkingLevel``);
* four runtime registries (providers, chat catalog, realtime catalog,
  connection builders);
* the seam :func:`create_model_connection_by_provider` — a concrete value of
  :data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` parameterised
  by :class:`otter_ai_core.ProviderModelOption` that routes on
  :class:`otter_ai_core.KnownApis`:

  - :data:`~otter_ai_core.KnownApis.ChatCompletion` resolves a catalog
    chat-completions model, builds an
    :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`,
    and adapts it to a
    :data:`~otter_ai_core.model_connection.ModelConnectionFn` via
    :mod:`otter_ai_assistant_stream_model_connection`;
  - :data:`~otter_ai_core.KnownApis.Realtime` resolves a realtime catalog model
    and delegates to :mod:`otter_ai_realtime`.

Importing the package auto-registers the built-ins (mirrors pi-ai's
``index.ts``, not ``base.ts``): ``openai`` and ``zai`` work immediately. A
future provider package registers an additional connection builder under a new
:class:`~otter_ai_core.KnownApis` member without this package changing.
"""

from __future__ import annotations

from otter_ai_assistant_provider_stream.builtins import (
    get_chat_completions_builder,
    get_realtime_builder,
    register_built_ins,
    reset,
)
from otter_ai_assistant_provider_stream.catalog import (
    all_models,
    get_model,
    list_models,
    register_model,
)
from otter_ai_assistant_provider_stream.connection import (
    create_model_connection_by_provider,
)
from otter_ai_assistant_provider_stream.connection_registry import (
    get_model_connection_builder,
    list_model_connection_builders,
    register_model_connection_builder,
)
from otter_ai_assistant_provider_stream.env import find_env_keys, get_env_api_key
from otter_ai_assistant_provider_stream.providers import (
    get_provider,
    list_providers,
    register_provider,
    unregister_provider,
)
from otter_ai_assistant_provider_stream.realtime_catalog import (
    all_realtime_models,
    get_realtime_model,
    list_realtime_models,
    register_realtime_model,
)
from otter_ai_assistant_provider_stream.thinking import (
    clamp_thinking_level,
    get_supported_thinking_levels,
    resolve_reasoning_effort,
)
from otter_ai_assistant_provider_stream.types import (
    BUILT_IN_PROVIDERS,
    ProviderConfig,
)
from otter_ai_core import (
    KnownApis,
    KnownProviders,
    ProviderModelOption,
    ThinkingLevel,
)

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # core seam
    "create_model_connection_by_provider",
    # core option types (re-exported)
    "ProviderModelOption",
    "KnownApis",
    "KnownProviders",
    "ThinkingLevel",
    # registry entry
    "ProviderConfig",
    "BUILT_IN_PROVIDERS",
    # registries — providers
    "register_provider",
    "get_provider",
    "unregister_provider",
    "list_providers",
    # registries — chat catalog
    "register_model",
    "get_model",
    "list_models",
    "all_models",
    # registries — realtime catalog
    "register_realtime_model",
    "get_realtime_model",
    "list_realtime_models",
    "all_realtime_models",
    # registries — connection builders
    "register_model_connection_builder",
    "get_model_connection_builder",
    "list_model_connection_builders",
    # registration lifecycle
    "register_built_ins",
    "get_chat_completions_builder",
    "get_realtime_builder",
    "reset",
    # thinking
    "clamp_thinking_level",
    "get_supported_thinking_levels",
    "resolve_reasoning_effort",
    # env
    "find_env_keys",
    "get_env_api_key",
]

# Auto-register built-ins on import (mirrors pi-ai index.ts, not base.ts).
register_built_ins()
