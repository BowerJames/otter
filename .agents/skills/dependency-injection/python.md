# Dependency Injection in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## Rule 1: code against interfaces

Type dependencies as Protocols (for classes) or Callables (for functions), never as concrete classes:

```python
# Coupled: no seam — the caller is welded to one adapter
def processOrder(order, gateway: StripeGateway):
    ...

# Decoupled: PaymentGateway is the interface at the seam
# Any adapter — Stripe in production, a fake in tests — can satisfy it
def processOrder(order, gateway: PaymentGateway):
    ...
```

## Rule 2: declare seams at construction

The `__init__` signature (or the function signature) is where the interface declares the seam; the methods take only data:

```python
class StripeGateway(PaymentGateway):
    def __init__(self, api_key: str, requester): # Construction for the stripe gateway module includes the requester seam
        ...

    def charge(self, amount: float) -> bool: # Only data passed to the methods of the module, not seams
        ...

    def refund(self, amount: float) -> bool:
        ...
```

A module-level global (`gateway = StripeGateway(KEY)`, imported by consumers) is the same dependency fetched instead of declared — Python's ambient service locator.

## Testing: fixtures wire the graph

A pytest fixture that assembles the graph with fakes is the test doing its own wiring — the same discipline at test scope. A fake is a small class satisfying the Protocol; a seam needs no mock library. `monkeypatch` is a service locator for tests: injecting a fake at the seam beats patching a global every time.

## Gotchas

- **Mutable default arguments** — `def __init__(self, hooks=[])` shares one list across every instance. Defaults must be immutable; use `None` and construct inside.
- **No framework needed.** `dependency-injector` and friends automate wiring; the discipline is stdlib-only — typed parameters and Protocols carry it.
