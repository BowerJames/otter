"""Generic builder type alias — the common shape of otter's producer seams.

A :data:`BuilderFn` is an options-binding callable: it takes a per-call
options bundle (``TOptions``) and returns the options-bound result
(``TResult``). It is the generalization underlying otter's producer-side seam
aliases, which are ``BuilderFn`` specialized to a fixed result type. No such
specialization is defined in core today; a future producer seam (e.g. a
connection-level seam in a dispatch package) will specialize ``BuilderFn``.

A *builder* closes over its options and returns the options-bound value; this
is distinct from driving a specific call, which keeps a registered builder
reusable across many invocations and lets a dispatch layer hand callers the
bound value directly.

The alias references no otter types — only :data:`collections.abc.Callable` —
so it can be imported anywhere with no circular-import risk.
"""

from __future__ import annotations

from collections.abc import Callable

#: An options-binding callable. ``[TOptions] -> TResult``.
#:
#: The common shape of otter's producer seams: takes a per-call options bundle
#: and returns the options-bound result. Specialized by fixing ``TResult`` to a
#: particular bound-fn type (see module docstring).
type BuilderFn[TOptions, TResult] = Callable[[TOptions], TResult]
