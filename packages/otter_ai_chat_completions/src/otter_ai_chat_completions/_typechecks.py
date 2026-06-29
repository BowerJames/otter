"""Static contract guards — enforced by mypy, zero-cost at runtime.

Asserts that this package's seam
:func:`create_chat_completions_assistant_message_stream` conforms to
:data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`,
parameterized by this package's options bundle
(:class:`ChatCompletionsModelOptions`).

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
semantics we want here. (Same idiom as ``otter_ai_core``'s
``test_assistant_message_stream_fn_builder_returns_conforming_callable``.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otter_ai_chat_completions.options import ChatCompletionsModelOptions
    from otter_ai_chat_completions.stream import (
        create_chat_completions_assistant_message_stream,
    )
    from otter_ai_core.assistant_message_stream import (
        AssistantMessageStreamFnBuilder,
    )

    _check: AssistantMessageStreamFnBuilder[ChatCompletionsModelOptions] = (
        create_chat_completions_assistant_message_stream
    )
