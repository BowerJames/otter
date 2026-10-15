"""The errors an agent session determines."""


class SessionEnded(RuntimeError):
    """An ended session was given a prompt."""

    def __init__(self) -> None:
        super().__init__("the session has ended")


class AlreadyStreaming(RuntimeError):
    """A session was streamed while its stream was already being read."""

    def __init__(self) -> None:
        super().__init__("the session is already being streamed")
