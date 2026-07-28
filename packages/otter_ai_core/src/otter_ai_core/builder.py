from __future__ import annotations

from collections.abc import Callable

#: An options-binding callable. ``[TOptions] -> TResult``.
#:
#: The common shape of otter's producer seams: takes a per-call options bundle
#: and returns the options-bound result. Specialized by fixing ``TResult`` to a
#: particular bound-fn type (see module docstring).
type BuilderFn[TOptions, TResult] = Callable[[TOptions], TResult]
