from typing import Protocol

from ..model import ModelFactory


class Provider(Protocol):
    """Abstraction over a source of chat models for a single vendor.

    Produces model factories bound to the vendor's API."""

    def get_model_factory(self, model: str, api_key: str) -> ModelFactory:
        """Resolves the named model against the vendor's API. The returned
        factory yields a fresh, unentered model per call. Raises KeyError if
        the model is not known to the vendor."""
        ...
