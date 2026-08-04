from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Tool(BaseModel):
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
            "Tool.parameters must be a JSON-Schema dict or a Pydantic BaseModel subclass."
        )

    @classmethod
    def from_pydantic(cls, name: str, description: str, model_cls: type[BaseModel]) -> Tool:
        return cls(name=name, description=description, parameters=model_cls)
