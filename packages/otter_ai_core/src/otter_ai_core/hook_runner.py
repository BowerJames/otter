"""Generic typed hook runner: emit-and-await (single handler, typed return).

A :class:`HookRunner` is the emit-with-response counterpart to
:mod:`otter_ai_core.bus`. Where the bus fans a fire-and-forget event out to
``N`` handlers (side-effects only, each isolated), a hook runner invokes a
single registered handler and returns its result to the caller, so the caller
can use it to adjust its workflow.

Why descriptors, not an enum key
--------------------------------
Each hook has its own ``(params, return)`` signature, and the set of hooks is
open (consumers — e.g. a future ``AgentLoop`` integration — define their own).
A :class:`~enum.StrEnum` key cannot carry per-member type parameters, so the
type checker could not recover the return type from
``emit(event_type, ...)``. Instead the key is a typed :class:`Hook` descriptor:
a frozen, hashable object parameterized over ``(TParams, TReturn)``.
:meth:`HookRunner.register` / :meth:`HookRunner.emit` infer both type vars
from the descriptor, so the public API is fully type-safe with no
``@overload`` and the set of hooks is infinitely extensible — new hooks need
no change to :class:`HookRunner`. This mirrors the existing
``AgentTool[TParams, TDetails]`` idiom.

One handler per hook
--------------------
A hook has at most one handler. Re-registering a hook raises
:exc:`RuntimeError` (unregister first to replace). Emitting a hook with no
handler returns ``None``.

No owned task / no teardown
---------------------------
Unlike the bus there is no background worker and no channel: dispatch is a dict
lookup followed by a direct ``await``. :class:`HookRunner` therefore owns no
:class:`~asyncio.Task`, binds to no event loop at construction, and needs no
``aclose`` or async-context-manager surface. Handler exceptions propagate to
the caller of :meth:`HookRunner.emit` (the caller is depending on the
response) rather than being isolated and logged, as the bus does for its
subscribers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class Hook[TParams, TReturn]:
    """A typed hook key; the value passed to :meth:`HookRunner.register` / ``emit``.

    Frozen and hashable so a descriptor works as a :class:`dict` key. Define
    hooks as module-level singletons (one per hook), annotated with their
    ``(TParams, TReturn)`` so ``register`` / ``emit`` infer them::

        PING: Hook[Ping, Pong] = Hook("ping")

    .. note::
       Construct via ``Hook("name")`` with an annotation, not
       ``Hook[P, R]("name")``. Subscript-then-construct raises at runtime:
       CPython's generic-alias call tries to set ``__orig_class__``, which a
       frozen + slots dataclass rejects.

    .. note::
       At runtime Python's generic parameters are erased, so two descriptors
       with the same :attr:`name` are the *same key* regardless of their type
       parameters (e.g. a ``Hook[Ping, Pong]`` and a ``Hook[Ping, None]`` built
       with the same name collide). Hence the "define each hook once as a
       module-level singleton" convention.
    """

    name: str


#: The handler signature for ``Hook[TParams, TReturn]``.
type HookHandler[TParams, TReturn] = Callable[[TParams], Awaitable[TReturn]]


class HookRunner:
    """A single-handler, emit-and-await registry keyed by typed :class:`Hook` descriptors.

    Register the (one) handler for a hook with :meth:`register` (which returns
    an unregister callable); invoke it and await its result with :meth:`emit`
    (``None`` if no handler is registered). The runner owns no task and needs
    no teardown.
    """

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
        """Register ``handler`` as the single handler for ``hook``.

        Returns a callable that unregisters it (idempotent). Raises
        :exc:`RuntimeError` if ``hook`` already has a handler — unregister
        first to replace.

        ``(TParams, TReturn)`` are inferred from ``hook``, so the handler's
        signature is checked against the hook's parameter and return types.
        """
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
        """Invoke ``hook``'s handler with ``params`` and await its result.

        Returns ``None`` if no handler is registered for ``hook``. A handler
        exception propagates to the caller (it is not isolated/logged, as the
        bus does for its subscribers).

        ``(TParams, TReturn)`` are inferred from ``hook``, so ``params`` is
        checked against the hook's parameter type and the return is narrowed to
        ``TReturn | None``.
        """
        handler = self._handlers.get(hook)
        if handler is None:
            return None
        return await cast(HookHandler[TParams, TReturn], handler)(params)
