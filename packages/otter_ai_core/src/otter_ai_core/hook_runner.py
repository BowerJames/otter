from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class Hook[TParams, TReturn]:
    name: str


#: The handler signature for ``Hook[TParams, TReturn]``.
type HookHandler[TParams, TReturn] = Callable[[TParams], Awaitable[TReturn]]


class HookRunner:
    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        # Heterogeneous registry: the per-hook (TParams, TReturn) relationship
        # cannot be tracked through a runtime dict, so storage is erased to
        # ``object`` and recovered with ``cast`` at the typed API boundary.
        # The public API stays fully type-safe; only the internals are erased.
        self._handlers: dict[object, object] = {}

    def register[TParams, TReturn](
        self, hook: Hook[TParams, TReturn], handler: HookHandler[TParams, TReturn]
    ) -> Callable[[], None]:
        if hook in self._handlers:
            raise RuntimeError(f"Hook {hook.name!r} already has a registered handler.")
        self._handlers[hook] = handler

        def _unregister() -> None:
            # Idempotent: a no-op once already removed. The identity check
            # ensures a stale callable cannot remove a *different* handler later
            # registered to the same hook (unregister-then-reregister).
            if self._handlers.get(hook) is handler:
                del self._handlers[hook]

        return _unregister

    async def emit[TParams, TReturn](
        self, hook: Hook[TParams, TReturn], params: TParams
    ) -> TReturn | None:
        handler = self._handlers.get(hook)
        if handler is None:
            return None
        return await cast(HookHandler[TParams, TReturn], handler)(params)
