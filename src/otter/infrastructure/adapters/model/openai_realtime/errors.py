"""The errors the realtime adapter determines."""


class ModelFailed(RuntimeError):
    """The endpoint reported that something failed, or that the model failed its turn."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the model failed: {reason}")


class TurnCutOff(RuntimeError):
    """The connection closed before the model finished its turn."""

    def __init__(self) -> None:
        super().__init__("the connection closed before the model finished its turn")
