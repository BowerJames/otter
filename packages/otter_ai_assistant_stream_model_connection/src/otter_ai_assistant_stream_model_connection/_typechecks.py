"""Static contract guard — enforced by mypy, zero-cost at runtime.

Asserts that this package's seam
:func:`create_assistant_stream_model_connection` conforms to
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder`, parameterised
by :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`.

mypy is the real enforcer; the entire body is guarded by ``if TYPE_CHECKING:``
so the module contributes nothing at runtime and never imports at runtime. It
is intentionally not referenced by any other module (and not exported from
``__init__.py``): mypy scans every file under ``packages`` (see
``[tool.mypy].files``), so the assertion runs whenever ``uv run mypy``
(pre-commit hook / code review) does. Breaking the seam's signature will fail
mypy on this file.

Why annotation assignment and not ``assert_type``: see
``otter_ai_chat_completions/_typechecks.py`` — a function type is never
*identical* to a ``Callable[[...], ...]`` alias, so ``assert_type`` rejects
conforming functions. Annotation assignment checks *assignability*
(conformance), which is the semantics we want here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otter_ai_assistant_stream_model_connection.connection import (
        create_assistant_stream_model_connection,
    )
    from otter_ai_core.assistant_message_stream import AssistantMessageStreamFn
    from otter_ai_core.model_connection import ModelConnectionFnBuilder

    _check: ModelConnectionFnBuilder[AssistantMessageStreamFn] = (
        create_assistant_stream_model_connection
    )
