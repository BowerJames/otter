"""Static contract guard — enforced by mypy, zero-cost at runtime.

Asserts that this package's seam :func:`create_realtime_model_connection`
conforms to
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder`, parameterised
by this package's options bundle (:class:`RealtimeModelOptions`).

mypy is the real enforcer; the entire body is guarded by ``if TYPE_CHECKING:``
so the module contributes nothing at runtime. (Same idiom as the other
packages' ``_typechecks.py`` modules — annotation assignment checks
assignability, which is the conformance semantics we want.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otter_ai_core.model_connection import ModelConnectionFnBuilder
    from otter_ai_realtime.connection import create_realtime_model_connection
    from otter_ai_realtime.options import RealtimeModelOptions

    _check: ModelConnectionFnBuilder[RealtimeModelOptions] = (
        create_realtime_model_connection
    )
