"""The errors a session log determines."""


class NotAnEntry(ValueError):
    """A line of the log is JSON, but not a context entry."""
