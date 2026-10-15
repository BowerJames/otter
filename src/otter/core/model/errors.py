"""The errors a model determines."""


class ModelNotOpen(RuntimeError):
    """A model was asked for a turn outside `async with`."""

    def __init__(self) -> None:
        super().__init__("the model is not open: generate inside `async with model`")
