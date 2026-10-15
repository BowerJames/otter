"""The errors the plugin host determines."""


class UnknownTool(LookupError):
    """The model asked for a tool the session does not have; `name` is what it asked for."""

    def __init__(self, name: str) -> None:
        super().__init__(f"the session has no tool named {name!r}")
        self.name = name


class DuplicateTool(ValueError):
    """A session's setup has two tools of one name; `name` is that name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"two tools are named {name!r}")
        self.name = name
