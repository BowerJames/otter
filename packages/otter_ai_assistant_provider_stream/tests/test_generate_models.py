"""Tests for the models.dev catalog generator (pure parse, no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

# The generator lives at packages/.../scripts/generate_models.py, not under
# src/, so it is not importable as a package module by default. Add the
# scripts directory to sys.path for this test.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import generate_models  # type: ignore[import-not-found]  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "data" / "modelsdev.fixture.json"


def _load_fixture() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(_FIXTURE.read_text(encoding="utf-8")))


def _by_id(models: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    for m in models:
        if m["id"] == model_id:
            return m
    raise AssertionError(f"missing {model_id}")


class TestOpenAiParsing:
    def test_filters_out_non_tool_call(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        ids = {m["id"] for m in models if m["provider"] == "openai"}
        assert "text-embedding-3-large" not in ids
        assert {"gpt-4o", "o3"}.issubset(ids)

    def test_openai_uses_chat_completions(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        for m in models:
            if m["provider"] == "openai":
                assert m["api"] == "chat-completions"
                assert m["base_url"] == "https://api.openai.com/v1"
                assert "compat" not in m  # standard defaults

    def test_openai_fields(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        gpt4o = _by_id(models, "gpt-4o")
        assert gpt4o["reasoning"] is False
        assert gpt4o["input_modalities"] == ["text", "image"]
        assert gpt4o["context_window"] == 128000
        assert gpt4o["max_tokens"] == 16384
        assert gpt4o["cost"]["input"] == 2.5


class TestZaiParsing:
    def test_filters_out_non_tool_call(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        ids = {m["id"] for m in models if m["provider"] == "zai"}
        assert "no-tools" not in ids
        assert {"glm-5.2", "glm-4.5-air"}.issubset(ids)

    def test_zai_base_url_and_api(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        for m in models:
            if m["provider"] == "zai":
                assert m["base_url"] == "https://api.z.ai/api/coding/paas/v4"
                assert m["api"] == "chat-completions"

    def test_glm52_compat_and_map(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        glm52 = _by_id(models, "glm-5.2")
        compat = glm52["compat"]
        assert compat["thinking_format"] == "zai"
        assert compat["supports_developer_role"] is False
        assert compat["supports_reasoning_effort"] is True
        assert compat["zai_tool_stream"] is True
        assert glm52["thinking_level_map"] == {
            "minimal": None,
            "low": "high",
            "medium": "high",
            "high": "high",
            "xhigh": "max",
        }

    def test_glm45_air_excludes_tool_stream(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        glm45 = _by_id(models, "glm-4.5-air")
        compat = glm45["compat"]
        assert "zai_tool_stream" not in compat
        # supports_reasoning_effort only set for glm-5.2.
        assert "supports_reasoning_effort" not in compat

    def test_zai_no_zai_coding_cn(self) -> None:
        # Only the global zai variant is emitted.
        models = generate_models.parse_models_dev(_load_fixture())
        providers = {m["provider"] for m in models}
        assert "zai-coding-cn" not in providers


class TestOutputStability:
    def test_sorted_by_provider_then_id(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        keys = [(m["provider"], m["id"]) for m in models]
        assert keys == sorted(keys)


class TestRenderProducesValidPython:
    def test_render_round_trips(self) -> None:
        models = generate_models.parse_models_dev(_load_fixture())
        source = generate_models._render(models)
        # The rendered source must be valid Python and expose CATALOG.
        namespace: dict[str, Any] = {}
        exec(compile(source, "<generated>", "exec"), namespace)
        catalog = namespace["CATALOG"]
        assert isinstance(catalog, list)
        assert catalog == models
