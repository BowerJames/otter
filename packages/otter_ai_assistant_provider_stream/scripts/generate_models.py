#!/usr/bin/env python3
"""Regenerate the committed model catalog from models.dev.

Fetches ``https://models.dev/api.json`` at dev time and writes
``src/otter_ai_assistant_provider_stream/_catalog_generated.py``. This is a
Python port of the ``openai`` and ``zai-coding-plan`` branches of pi-ai's
``scripts/generate-models.ts``, scoped to the two built-in providers this
package ships.

Run manually (no runtime network):

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
    """Render a JSON value as a Python literal with tab indentation."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + "\t"
        items = [
            f"{inner}{repr(key)}: {_render_value(val, inner)}"
            for key, val in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = indent + "\t"
        items = [_render_value(item, inner) for item in value]
        return "[\n" + ",\n".join(items) + "\n" + indent + "]"
    # Scalars: repr gives valid Python (True/False/None/str/int/float).
    return repr(value)


def _render(models: list[dict[str, Any]]) -> str:
    """Render the catalog as a Python source module."""
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


def _fetch() -> dict[str, Any]:
    req = urllib.request.Request(_MODELS_DEV_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — trusted URL
        data = json.loads(resp.read().decode("utf-8"))
    return cast("dict[str, Any]", data)


def main() -> int:
    out_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "otter_ai_assistant_provider_stream"
        / "_catalog_generated.py"
    )
    data = _fetch()
    models = parse_models_dev(data)
    out_path.write_text(_render(models), encoding="utf-8")
    print(f"Wrote {len(models)} models to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
