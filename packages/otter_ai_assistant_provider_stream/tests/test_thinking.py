"""Tests for the thinking-level clamping layer (port of pi-ai ``models.ts``)."""

from __future__ import annotations

from typing import cast

import pytest
from _provider_helpers import model_kwargs

from otter_ai_assistant_provider_stream import (
    clamp_thinking_level,
    get_supported_thinking_levels,
)
from otter_ai_assistant_provider_stream.thinking import resolve_reasoning_effort
from otter_ai_assistant_provider_stream.types import ThinkingLevel
from otter_ai_chat_completions import ChatCompletionsModel


def _model(**overrides: object) -> ChatCompletionsModel:
    return ChatCompletionsModel(**{**model_kwargs(), **overrides})


class TestGetSupportedThinkingLevels:
    def test_non_reasoning_model_supports_only_off(self) -> None:
        model = _model(reasoning=False)
        assert get_supported_thinking_levels(model) == ["off"]

    def test_reasoning_model_without_map_supports_all_but_xhigh(self) -> None:
        # No thinking_level_map: every level except xhigh is supported by default.
        model = _model(reasoning=True, thinking_level_map=None)
        assert get_supported_thinking_levels(model) == [
            "off",
            "minimal",
            "low",
            "medium",
            "high",
        ]

    def test_explicit_none_marks_level_unsupported(self) -> None:
        model = _model(
            reasoning=True,
            thinking_level_map={"minimal": None, "low": "high", "high": "high"},
        )
        levels = get_supported_thinking_levels(model)
        assert "minimal" not in levels
        assert "low" in levels
        assert "high" in levels

    def test_xhigh_requires_explicit_non_none_mapping(self) -> None:
        # glm-5.2 map: xhigh explicitly mapped to "max" -> supported.
        glm52_map = {
            "minimal": None,
            "low": "high",
            "medium": "high",
            "high": "high",
            "xhigh": "max",
        }
        model = _model(reasoning=True, thinking_level_map=glm52_map)
        assert "xhigh" in get_supported_thinking_levels(model)

    def test_xhigh_absent_from_map_is_unsupported(self) -> None:
        model = _model(reasoning=True, thinking_level_map={"high": "high"})
        assert "xhigh" not in get_supported_thinking_levels(model)


class TestClampThinkingLevel:
    def test_supported_level_returned_unchanged(self) -> None:
        model = _model(reasoning=True)
        assert clamp_thinking_level(model, "low") == "low"
        assert clamp_thinking_level(model, "high") == "high"

    def test_glm52_minimal_clamps_up_to_low(self) -> None:
        # minimal is explicitly None -> unsupported; scan up finds low.
        glm52_map = {
            "minimal": None,
            "low": "high",
            "medium": "high",
            "high": "high",
            "xhigh": "max",
        }
        model = _model(reasoning=True, thinking_level_map=glm52_map)
        assert clamp_thinking_level(model, "minimal") == "low"

    def test_non_reasoning_clamps_to_off(self) -> None:
        model = _model(reasoning=False)
        assert clamp_thinking_level(model, "high") == "off"
        assert clamp_thinking_level(model, "xhigh") == "off"

    def test_xhigh_on_model_without_xhigh_clamps_down(self) -> None:
        # No xhigh mapping -> unsupported; scan up fails, scan down finds high.
        model = _model(reasoning=True, thinking_level_map={"high": "high"})
        assert clamp_thinking_level(model, "xhigh") == "high"


class TestResolveReasoningEffort:
    def test_off_returns_none(self) -> None:
        assert resolve_reasoning_effort("off") is None

    @pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "xhigh"])
    def test_non_off_returns_level(self, level: str) -> None:
        assert resolve_reasoning_effort(cast("ThinkingLevel", level)) == level
