"""Tests for the realtime model-catalog registry + generator branch."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from otter_ai_assistant_provider_stream import (
    all_realtime_models,
    get_realtime_model,
    list_realtime_models,
    register_realtime_model,
)
from otter_ai_realtime import RealtimeCost, RealtimeModel

# The generator lives at scripts/, not under src/.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import generate_models  # type: ignore[import-not-found]  # noqa: E402


class TestRealtimeCatalogRegistry:
    def test_built_in_openai_realtime_models_loaded(self) -> None:
        ids = {m.id for m in all_realtime_models()}
        assert "gpt-4o-realtime-preview" in ids
        assert "gpt-4o-mini-realtime-preview" in ids

    def test_get_realtime_model(self) -> None:
        model = get_realtime_model("openai", "gpt-4o-realtime-preview")
        assert model is not None
        assert model.provider == "openai"
        assert model.api == "realtime"
        assert model.base_url == "https://api.openai.com/v1"

    def test_get_unknown_returns_none(self) -> None:
        assert get_realtime_model("openai", "no-such") is None
        assert get_realtime_model("zai", "gpt-4o-realtime-preview") is None

    def test_list_filters_by_provider(self) -> None:
        models = list_realtime_models("openai")
        assert models
        assert all(m.provider == "openai" for m in models)

    def test_register_overwrites(self) -> None:
        custom = RealtimeModel(
            id="gpt-4o-realtime-preview",
            name="Override",
            provider="openai",
            base_url="https://api.openai.com/v1",
            input_modalities=["text"],
            context_window=1000,
            max_tokens=100,
            cost=RealtimeCost(input=1.0, output=1.0, cache_read=0.0, cache_write=0.0),
        )
        register_realtime_model(custom)
        assert get_realtime_model("openai", "gpt-4o-realtime-preview") is custom


class TestRealtimeGenerator:
    def test_realtime_models_hand_curated_and_valid(self) -> None:
        models = generate_models.realtime_models()
        assert len(models) >= 2
        # Every entry validates into a RealtimeModel.
        for entry in models:
            m = RealtimeModel.model_validate(entry)
            assert m.api == "realtime"
            assert m.provider == "openai"
            assert m.input_modalities == ["text"]  # v1 text-only

    def test_realtime_models_sorted(self) -> None:
        models = generate_models.realtime_models()
        keys = [(m["provider"], m["id"]) for m in models]
        assert keys == sorted(keys)

    def test_render_realtime_round_trips(self) -> None:
        models = generate_models.realtime_models()
        source = generate_models._render_realtime(models)
        namespace: dict[str, Any] = {}
        exec(compile(source, "<generated>", "exec"), namespace)
        catalog = namespace["REALTIME_CATALOG"]
        assert isinstance(catalog, list)
        assert catalog == models

    def test_committed_module_matches_generator(self) -> None:
        # The committed file must round-trip the generator's current output.
        from otter_ai_assistant_provider_stream._realtime_catalog_generated import (
            REALTIME_CATALOG,
        )

        assert REALTIME_CATALOG == generate_models.realtime_models()
