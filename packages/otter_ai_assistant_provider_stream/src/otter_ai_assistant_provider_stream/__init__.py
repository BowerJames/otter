"""otter-ai-assistant-provider-stream — provider/dispatch layer for otter-ai-core.

This package adds the dispatch layer :mod:`otter_ai_core` deliberately omits:

* a built-in model catalog (generated from models.dev, ``openai`` + ``zai``);
* env-key resolution (explicit > env > raise);
* thinking-level clamping (port of pi-ai's ``clampThinkingLevel``);
* three runtime registries (providers, catalog, api stream fns);
* the seam :func:`create_assistant_message_stream_by_provider`, a concrete
  value of :data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`.

Importing the package auto-registers the built-ins (mirrors pi-ai's
``index.ts``, not ``base.ts``): ``openai`` and ``zai`` work immediately.

It dispatches through :mod:`otter_ai_chat_completions`; future provider
packages register additional api stream fns without this package changing.
"""

from __future__ import annotations

from otter_ai_assistant_provider_stream.api_registry import (
    get_api_stream_fn,
    list_apis,
    register_api_stream_fn,
)
from otter_ai_assistant_provider_stream.builtins import (
    get_default_api_stream_fn,
    register_built_ins,
    reset,
)
from otter_ai_assistant_provider_stream.catalog import (
    all_models,
    get_model,
    list_models,
    register_model,
)
from otter_ai_assistant_provider_stream.env import find_env_keys, get_env_api_key
from otter_ai_assistant_provider_stream.providers import (
    get_provider,
    list_providers,
    register_provider,
    unregister_provider,
)
from otter_ai_assistant_provider_stream.stream import (
    create_assistant_message_stream_by_provider,
)
from otter_ai_assistant_provider_stream.thinking import (
    clamp_thinking_level,
    get_supported_thinking_levels,
    resolve_reasoning_effort,
)
from otter_ai_assistant_provider_stream.types import (
    BUILT_IN_PROVIDERS,
    DEFAULT_API,
    ModelProviderConfig,
    ModelProviderOptions,
    ModelProviderOverrides,
    ProviderConfig,
    ThinkingLevel,
)

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # core seam
    "create_assistant_message_stream_by_provider",
    # caller config
    "ModelProviderConfig",
    "ModelProviderOptions",
    "ModelProviderOverrides",
    "ThinkingLevel",
    "BUILT_IN_PROVIDERS",
    "DEFAULT_API",
    # registry entry
    "ProviderConfig",
    # registries
    "register_provider",
    "get_provider",
    "unregister_provider",
    "list_providers",
    "register_model",
    "get_model",
    "list_models",
    "all_models",
    "register_api_stream_fn",
    "get_api_stream_fn",
    "list_apis",
    "get_default_api_stream_fn",
    "register_built_ins",
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
