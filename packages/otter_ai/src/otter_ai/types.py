"""Open-string metadata and shared literals for the context model.

`Api` and `Provider` are intentionally left as open :class:`str` aliases. In
the upstream pi-ai library they drive a provider registry; otter is data-only,
so they exist purely as inert provenance recorded on
:class:`~otter_ai.messages.AssistantMessage`.
"""

from __future__ import annotations

from typing import Literal

#: API shape that produced an assistant message (e.g. ``"anthropic-messages"``).
#: Open string: built-in names are not enumerated because no registry consumes them.
Api = str

#: Provider that produced an assistant message (e.g. ``"anthropic"``).
#: Open string: built-in names are not enumerated because no registry consumes them.
Provider = str

#: Why an assistant turn stopped generating.
StopReason = Literal["stop", "length", "tool_use", "error", "aborted"]
