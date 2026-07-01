#!/usr/bin/env python3
"""Regenerate the committed model catalogs.

Writes two committed modules under
``src/otter_ai_assistant_provider_stream/``:

* ``_catalog_generated.py`` — Chat-Completions models, fetched from
  ``https://models.dev/api.json`` (a Python port of the ``openai`` and
  ``zai-coding-plan`` branches of pi-ai's ``scripts/generate-models.ts``,
  scoped to the two built-in providers this package ships).
* ``_realtime_catalog_generated.py`` — Realtime models. **Hand-curated**
  (see :data:`_REALTIME_MODELS`): models.dev does not carry first-party
  realtime models for ``openai``/``zai`` — its realtime entries live under
  third-party gateways, are audio-capable, and have ``tool_call=false``. The
  first-party text-capable realtime models otter dispatches are therefore
  listed here explicitly.

Run manually (the realtime branch needs no network; the chat branch fetches
models.dev):

    uv run python packages/otter_ai_assistant_provider_stream/scripts/generate_models.py

Notes / deviations from pi-ai
-----------------------------
* OpenAI models are emitted with ``api="chat-completions"`` and **no** compat
  (standard defaults). pi-ai emits ``api="openai-responses"``; otter has only
  the chat-completions seam today (issue #15 decision #2).
* Only the **global** ``zai`` variant is emitted (``zai-coding-cn`` is
  omitted — issue #15 decision #6/#7).
* The glm-5.2 ``thinking_level_map`` and the zai compat flags are applied
  verbatim from pi-ai.
* Realtime models are hand-curated and pinned to text-only v1
  (``input_modalities=["text"]``), matching
  :class:`otter_ai_realtime.RealtimeModel`.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, cast

_MODELS_DEV_URL = "https://models.dev/api.json"
_USER_AGENT = "otter-codegen/0.1 (https://github.com/BowerJames/otter)"

#: OpenAI Chat Completions base URL.
_OPENAI_BASE_URL = "https://api.openai.com/v1"

#: OpenAI Realtime base URL (the ``base_url`` a :class:`RealtimeModel` carries;
#: the WS scheme is derived from it by
#: :func:`otter_ai_realtime._transport.realtime_url`).
_OPENAI_REALTIME_BASE_URL = "https://api.openai.com/v1"

#: Hand-curated first-party Realtime models. models.dev does not list these
#: under the ``openai`` provider (it only carries third-party, audio-capable
#: realtime models), so they are hand-listed here. v1 is text-only: rates are
#: USD per million text tokens, matching :class:`otter_ai_realtime.RealtimeCost`.
#:
#: Each entry is a ``RealtimeModel``-shaped dict (validated at catalog-load
#: time). Pricing reflects OpenAI's published realtime rates.
_REALTIME_MODELS: list[dict[str, Any]] = [
    {
        "id": "gpt-4o-realtime-preview",
        "name": "GPT-4o Realtime Preview",
        "provider": "openai",
        "base_url": _OPENAI_REALTIME_BASE_URL,
        "api": "realtime",
        "input_modalities": ["text"],
        "context_window": 128000,
        "max_tokens": 4096,
        "cost": {"input": 5.0, "output": 20.0, "cache_read": 2.5, "cache_write": 0.0},
    },
    {
        "id": "gpt-4o-realtime-preview-2024-12-17",
        "name": "GPT-4o Realtime Preview (2024-12-17)",
        "provider": "openai",
        "base_url": _OPENAI_REALTIME_BASE_URL,
        "api": "realtime",
        "input_modalities": ["text"],
        "context_window": 128000,
        "max_tokens": 4096,
        "cost": {"input": 5.0, "output": 20.0, "cache_read": 2.5, "cache_write": 0.0},
    },
    {
        "id": "gpt-4o-mini-realtime-preview",
        "name": "GPT-4o mini Realtime Preview",
        "provider": "openai",
        "base_url": _OPENAI_REALTIME_BASE_URL,
        "api": "realtime",
        "input_modalities": ["text"],
        "context_window": 128000,
        "max_tokens": 4096,
        "cost": {
            "input": 0.6,
            "output": 2.4,
            "cache_read": 0.3,
            "cache_write": 0.0,
        },
    },
    {
        "id": "gpt-4o-mini-realtime-preview-2024-12-17",
        "name": "GPT-4o mini Realtime Preview (2024-12-17)",
        "provider": "openai",
        "base_url": _OPENAI_REALTIME_BASE_URL,
        "api": "realtime",
        "input_modalities": ["text"],
        "context_window": 128000,
        "max_tokens": 4096,
        "cost": {
            "input": 0.6,
            "output": 2.4,
            "cache_read": 0.3,
            "cache_write": 0.0,
        },
    },
]

#: Global z.ai coding-plan base URL (the ``zai`` provider).
_ZAI_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

#: zai models that do not support ``tool_stream: true`` (pi-ai parity).
_ZAI_TOOL_STREAM_UNSUPPORTED = frozenset(
    {"glm-4.5", "glm-4.5-air", "glm-4.5-flash", "glm-4.5v"}
)

#: glm-5.2 thinking-level map (pi-ai parity).
_ZAI_GLM52_THINKING_LEVEL_MAP: dict[str, str | None] = {
    "minimal": None,
    "low": "high",
    "medium": "high",
    "high": "high",
    "xhigh": "max",
}


def _input_modalities(m: dict[str, Any]) -> list[str]:
    inputs = (m.get("modalities") or {}).get("input") or []
    return ["text", "image"] if "image" in inputs else ["text"]


def _cost(m: dict[str, Any]) -> dict[str, float]:
    cost = m.get("cost") or {}
    return {
        "input": float(cost.get("input") or 0),
        "output": float(cost.get("output") or 0),
        "cache_read": float(cost.get("cache_read") or 0),
        "cache_write": float(cost.get("cache_write") or 0),
    }


def _parse_openai(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse ``data["openai"]["models"]`` into chat-completions catalog dicts."""
    models: list[dict[str, Any]] = []
    raw = (data.get("openai") or {}).get("models") or {}
    for model_id, m in raw.items():
        if m.get("tool_call") is not True:
            continue
        models.append(
            {
                "id": model_id,
                "name": m.get("name") or model_id,
                "provider": "openai",
                "base_url": _OPENAI_BASE_URL,
                "api": "chat-completions",
                "reasoning": m.get("reasoning") is True,
                "input_modalities": _input_modalities(m),
                "cost": _cost(m),
                "context_window": int((m.get("limit") or {}).get("context") or 4096),
                "max_tokens": int((m.get("limit") or {}).get("output") or 4096),
            }
        )
    return models


def _parse_zai(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse ``data["zai-coding-plan"]["models"]`` into global zai catalog dicts.

    Mirrors pi-ai's zai branch: ``thinking_format="zai"``,
    ``supports_developer_role=False``, ``supports_reasoning_effort`` only for
    glm-5.2, ``zai_tool_stream`` for all models except the GLM-4.5 family, and
    the glm-5.2 ``thinking_level_map``.
    """
    models: list[dict[str, Any]] = []
    raw = (data.get("zai-coding-plan") or {}).get("models") or {}
    for model_id, m in raw.items():
        if m.get("tool_call") is not True:
            continue
        is_glm52 = model_id == "glm-5.2"
        compat: dict[str, Any] = {
            "supports_developer_role": False,
            "thinking_format": "zai",
        }
        if is_glm52:
            compat["supports_reasoning_effort"] = True
        if model_id not in _ZAI_TOOL_STREAM_UNSUPPORTED:
            compat["zai_tool_stream"] = True

        entry: dict[str, Any] = {
            "id": model_id,
            "name": m.get("name") or model_id,
            "provider": "zai",
            "base_url": _ZAI_BASE_URL,
            "api": "chat-completions",
            "reasoning": m.get("reasoning") is True,
            "input_modalities": _input_modalities(m),
            "cost": _cost(m),
            "context_window": int((m.get("limit") or {}).get("context") or 4096),
            "max_tokens": int((m.get("limit") or {}).get("output") or 4096),
            "compat": compat,
        }
        if is_glm52:
            entry["thinking_level_map"] = dict(_ZAI_GLM52_THINKING_LEVEL_MAP)
        models.append(entry)
    return models


def parse_models_dev(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a models.dev ``api.json`` payload into catalog dicts.

    Pure (no I/O): exported for unit testing against a frozen fixture.
    Returns openai + global zai models, sorted by (provider, id) for stable
    output.
    """
    models = _parse_openai(data) + _parse_zai(data)
    models.sort(key=lambda e: (e["provider"], e["id"]))
    return models


def _render_value(value: Any, indent: str) -> str:
    """Render a JSON value as a Python literal with 4-space indentation."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + "    "
        items = [
            f"{inner}{repr(key)}: {_render_value(val, inner)}"
            for key, val in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = indent + "    "
        items = [_render_value(item, inner) for item in value]
        return "[\n" + ",\n".join(items) + "\n" + indent + "]"
    # Scalars: repr gives valid Python (True/False/None/str/int/float).
    return repr(value)


def _render(models: list[dict[str, Any]]) -> str:
    """Render the chat-completions catalog as a Python source module."""
    body = _render_value(models, "")
    return f'''"""Auto-generated by scripts/generate_models.py. Do not edit.

Regenerate with:
    uv run python packages/otter_ai_assistant_provider_stream/scripts/generate_models.py

Source: https://models.dev/api.json (openai + zai-coding-plan/global).
"""

from __future__ import annotations

from typing import Any

# A flat list of ChatCompletionsModel-shaped dicts, validated into
# models at catalog load time (see catalog.load_generated_catalog).
CATALOG: list[dict[str, Any]] = {body}

__all__ = ["CATALOG"]
'''


def realtime_models() -> list[dict[str, Any]]:
    """Return a sorted copy of the hand-curated realtime catalog dicts."""
    models = [dict(entry) for entry in _REALTIME_MODELS]
    models.sort(key=lambda e: (e["provider"], e["id"]))
    return models


def _render_realtime(models: list[dict[str, Any]]) -> str:
    """Render the realtime catalog as a Python source module."""
    body = _render_value(models, "")
    return f'''"""Auto-generated by scripts/generate_models.py. Do not edit.

Regenerate with:
    uv run python packages/otter_ai_assistant_provider_stream/scripts/generate_models.py

Source: hand-curated (models.dev carries no first-party realtime models for
openai/zai). See ``_REALTIME_MODELS`` in the generator.
"""

from __future__ import annotations

from typing import Any

# A flat list of RealtimeModel-shaped dicts, validated into models at
# catalog load time (see realtime_catalog.load_generated_realtime_catalog).
REALTIME_CATALOG: list[dict[str, Any]] = {body}

__all__ = ["REALTIME_CATALOG"]
'''


def _fetch() -> dict[str, Any]:
    req = urllib.request.Request(_MODELS_DEV_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — trusted URL
        data = json.loads(resp.read().decode("utf-8"))
    return cast("dict[str, Any]", data)


def main() -> int:
    src_dir = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "otter_ai_assistant_provider_stream"
    )

    # Chat-completions catalog (fetched from models.dev).
    chat_path = src_dir / "_catalog_generated.py"
    data = _fetch()
    models = parse_models_dev(data)
    chat_path.write_text(_render(models), encoding="utf-8")
    print(f"Wrote {len(models)} chat-completions models to {chat_path}")

    # Realtime catalog (hand-curated — no network).
    realtime_path = src_dir / "_realtime_catalog_generated.py"
    rt_models = realtime_models()
    realtime_path.write_text(_render_realtime(rt_models), encoding="utf-8")
    print(f"Wrote {len(rt_models)} realtime models to {realtime_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
