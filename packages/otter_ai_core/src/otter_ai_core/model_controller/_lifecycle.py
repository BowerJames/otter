"""Back-compat re-export of the shared teardown helper.

The single implementation of :func:`await_or_cancel` now lives in
:mod:`otter_ai_core._lifecycle` (shared by the bus, the controller, and the
faux producer). This module re-exports it so the existing import path

    from otter_ai_core.model_controller._lifecycle import await_or_cancel

keeps resolving unchanged. New consumers should import from
:mod:`otter_ai_core._lifecycle` directly.
"""

from __future__ import annotations

from otter_ai_core._lifecycle import await_or_cancel

__all__ = ["await_or_cancel"]
