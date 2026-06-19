"""Tool parameter schema handling (dict or Pydantic class -> JSON Schema dict)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from otter_ai import Tool, tool_from_pydantic


class _GetTimeParams(BaseModel):
    timezone: str | None = None


def test_parameters_accepts_dict() -> None:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    tool = Tool(name="noop", description="d", parameters=schema)
    assert tool.parameters == schema


def test_parameters_accepts_pydantic_class() -> None:
    tool = Tool(name="get_time", description="d", parameters=_GetTimeParams)
    assert tool.parameters == _GetTimeParams.model_json_schema()
    # Sanity: the converted schema looks like JSON Schema.
    assert tool.parameters["type"] == "object"
    assert "timezone" in tool.parameters["properties"]


def test_parameters_dict_and_class_round_trip_identically() -> None:
    by_dict = Tool(
        name="get_time", description="d", parameters=_GetTimeParams.model_json_schema()
    )
    by_cls = Tool(name="get_time", description="d", parameters=_GetTimeParams)
    assert by_dict.parameters == by_cls.parameters


def test_parameters_rejects_instance() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Tool(name="get_time", description="d", parameters=_GetTimeParams())
    assert "BaseModel instance" in str(excinfo.value)


def test_parameters_rejects_non_schema_value() -> None:
    with pytest.raises(ValidationError):
        Tool(name="get_time", description="d", parameters="not-a-schema")


def test_tool_from_pydantic_helper() -> None:
    tool = tool_from_pydantic("get_time", "d", _GetTimeParams)
    assert tool.name == "get_time"
    assert tool.parameters == _GetTimeParams.model_json_schema()
