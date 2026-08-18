import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from .signature import AgentTool
from .types import AgentToolResult


@dataclass
class AgentToolHarness:
    tool: AgentTool
    valid_arguments: dict[str, Any]
    invalid_arguments: dict[str, Any] | None
    body_invocations: list[Any]


class AgentToolConformanceSuite:
    @pytest.fixture
    def make_tool(self) -> Callable[[], AgentToolHarness]:
        raise NotImplementedError("conformance suite requires a make_tool fixture")

    @pytest.fixture
    def make_raising_tool(self) -> Callable[[], AgentToolHarness] | None:
        return None

    def test_name_is_non_empty_string(self, make_tool: Callable[[], AgentToolHarness]) -> None:
        harness = make_tool()
        assert isinstance(harness.tool.name, str)
        assert harness.tool.name != ""

    def test_parameters_schema_is_json_serializable(
        self, make_tool: Callable[[], AgentToolHarness]
    ) -> None:
        harness = make_tool()
        schema = harness.tool.parameters.model_json_schema()
        assert isinstance(schema, dict)
        json.dumps(schema)

    def test_harness_declarations_match_parameters(
        self,
        make_tool: Callable[[], AgentToolHarness],
        make_raising_tool: Callable[[], AgentToolHarness] | None,
    ) -> None:
        harness = make_tool()
        harness.tool.parameters.model_validate(harness.valid_arguments)
        if harness.invalid_arguments is not None:
            with pytest.raises(ValidationError):
                harness.tool.parameters.model_validate(harness.invalid_arguments)
        if make_raising_tool is not None:
            raising_harness = make_raising_tool()
            raising_harness.tool.parameters.model_validate(raising_harness.valid_arguments)

    async def test_valid_arguments_run_body_once_and_return_result(
        self, make_tool: Callable[[], AgentToolHarness]
    ) -> None:
        harness = make_tool()
        result = await harness.tool.execute(harness.valid_arguments)
        assert isinstance(result, AgentToolResult)
        assert len(harness.body_invocations) == 1

    async def test_invalid_arguments_return_error_result_without_running_body(
        self, make_tool: Callable[[], AgentToolHarness]
    ) -> None:
        harness = make_tool()
        if harness.invalid_arguments is None:
            pytest.skip("parameters schema accepts every input; no invalid arguments exist")
        result = await harness.tool.execute(harness.invalid_arguments)
        assert isinstance(result, AgentToolResult)
        assert result.is_error is True
        assert len(harness.body_invocations) == 0

    async def test_body_exception_propagates(
        self, make_raising_tool: Callable[[], AgentToolHarness] | None
    ) -> None:
        if make_raising_tool is None:
            pytest.skip("adapter does not provide a raising tool factory")
        harness = make_raising_tool()
        with pytest.raises(ValueError):
            await harness.tool.execute(harness.valid_arguments)
