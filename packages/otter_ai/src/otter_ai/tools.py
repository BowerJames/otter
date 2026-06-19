"""Tool definitions available to the model.

``Tool.parameters`` is stored as a JSON-Schema ``dict`` so that a
:class:`~otter_ai.context.Context` stays pure-JSON-serializable, mirroring the
upstream pi-ai model (where parameters are TypeBox schemas, which are
themselves JSON Schema). For ergonomic construction a Pydantic ``BaseModel``
*subclass* may be passed instead and is converted via
``model_json_schema()``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Tool(BaseModel):
    """A tool the model may call.

    Parameters may be supplied as:

    * a raw JSON-Schema ``dict`` (used as-is), or
    * a Pydantic ``BaseModel`` *subclass* (converted to JSON Schema).

    Passing a Pydantic ``BaseModel`` *instance* is rejected — the schema is
    wanted, not the data.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]

    @field_validator("parameters", mode="before")
    @classmethod
    def _coerce_parameters(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return value
        # Accept a BaseModel *subclass* (type object), but not an *instance*.
        if isinstance(value, type) and issubclass(value, BaseModel):
            return value.model_json_schema()
        if isinstance(value, BaseModel):
            raise ValueError(
                "Tool.parameters expected a JSON-Schema dict or a Pydantic "
                "BaseModel subclass, but got a BaseModel instance; pass the "
                "model class (or its JSON schema) instead."
            )
        raise ValueError(
            "Tool.parameters must be a JSON-Schema dict or a Pydantic "
            "BaseModel subclass."
        )


def tool_from_pydantic(name: str, description: str, model_cls: type[BaseModel]) -> Tool:
    """Build a :class:`Tool` from a Pydantic ``BaseModel`` subclass.

    Convenience wrapper around ``Tool(name=name, description=description,
    parameters=model_cls)``.
    """
    return Tool(name=name, description=description, parameters=model_cls)
