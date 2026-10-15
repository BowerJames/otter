"""The errors the responses adapter determines."""


class ModelFailed(RuntimeError):
    """The provider answered that the model failed to produce its turn."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the model failed: {reason}")
