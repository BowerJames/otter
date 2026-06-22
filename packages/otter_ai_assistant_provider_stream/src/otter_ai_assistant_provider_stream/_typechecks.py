"""Static contract guards — enforced by mypy, zero-cost at runtime.

Asserts that this package's dispatch seam
:func:`create_assistant_message_stream_by_provider` conforms to
:data:`otter_ai_core.AssistantMessageStreamFn`, parameterized by this package's
options bundle (:class:`ModelProviderOptions`).

mypy is the real enforcer; the entire body is guarded by ``if TYPE_CHECKING:``
so the module contributes nothing at runtime and never imports at runtime. It
is intentionally not referenced by any other module (and not exported from
``__init__.py``): mypy scans every file under ``packages`` (see
``[tool.mypy].files``), so the assertion runs whenever ``uv run mypy``
(pre-commit hook / code review) does. Breaking the seam's signature will fail
mypy on this file.

Why annotation assignment and not ``assert_type``:
``typing.assert_type`` requires the expression's type to be *identical* to the
asserted type, but a function definition's type is a function type
(``def (...) -> ...``), never identical to a ``Callable[[...], ...]`` alias even
when structurally equivalent — so ``assert_type`` rejects conforming functions.
Annotation assignment checks *assignability* (conformance), which is the
semantics we want here. (Same idiom as
``otter_ai_core``'s ``test_assistant_message_stream_fn_accepts_conforming_callable``.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otter_ai_assistant_provider_stream.stream import (
        create_assistant_message_stream_by_provider,
    )
    from otter_ai_assistant_provider_stream.types import ModelProviderOptions
    from otter_ai_core import AssistantMessageStreamFn

    _check: AssistantMessageStreamFn[ModelProviderOptions] = (
        create_assistant_message_stream_by_provider
    )
