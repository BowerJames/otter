# Codebase Design in Python

The vocabulary in [SKILL.md](SKILL.md) is language-agnostic. This file is its Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Interface** | for classes, a `typing.Protocol`; for functions, a type — `Callable[[], datetime]` |
| **Adapter** | any class or function satisfying the interface's shape |
| **Module** | a class, a module-level function, or a package |
| **Seam** | a typed parameter behaviour varies through: an object interface, a function interface, or a plain value |
| **Resource** | `os.environ`, the filesystem, the clock, the network — reached only behind an adapter |

## Interfaces are types

```python
from typing import Protocol

class PaymentGateway(Protocol):          # the interface at the seam
    def charge(self, amount: float) -> bool: ...

class StripeGateway:                      # an adapter — no inheritance
    def charge(self, amount: float) -> bool: ...
```

Matching is structural: `StripeGateway` satisfies the Protocol by shape alone. Explicit inheritance (`class StripeGateway(PaymentGateway)`) is allowed and documents intent — it lets the type checker flag drift — but it is a declaration, never a requirement.

- Prefer **Protocol over ABC** for interfaces: ABC is nominal (adapters must inherit), and a seam wants *any* satisfier.
- `@runtime_checkable` only checks that methods exist, not their signatures — it is no substitute for the type checker.

A function's interface is its type: `clock: Callable[[], datetime]` says everything a caller must know. When a function interface needs keyword parameters, defaults, or a name, promote it to a Protocol with `__call__`:

```python
class Clock(Protocol):
    def __call__(self, *, tz: str = "UTC") -> datetime: ...
```

## The shapes of a seam

A seam is anywhere behaviour varies without editing the module. In Python it takes three shapes:

```python
def __init__(self,
             gateway: PaymentGateway,            # object interface: a whole adapter can cross it
             clock: Callable[[], datetime],      # function interface: one function swaps
             verbose: bool):                     # plain value: one bit of behaviour
```

All three are seams; they differ in **Depth**. A Protocol carries a whole interface of variation, a Callable one function's worth, a bool one bit. Fit the seam to the variation: a Protocol behind a binary toggle is ceremony; a bool behind a swappable adapter is a wall.

## Modules don't need classes

A module-level function with a typed parameter is already a module with a seam — no class, no framework, no decorators:

```python
def processOrder(order: Order, gateway: PaymentGateway) -> Receipt: ...
```

## Adapters and seams

```python
class PaymentGateway(Protocol): # PaymentGateway is an interface of the processOrder module seam
    def charge(self, amount: float) -> bool:
        ...

def processOrder(order, paymentGateway: PaymentGateway):
    ...

class StripeGateway: # StripeGateway is a module
    def __init__(self, api_key: str, requester: Callable[[Request], Response]):
        ...

    def charge(self, amount: float) -> bool:
        ...

    def refund(self, amount: float) -> bool:
        ...

processOrder(order, StripeGateway()) # StripeGateway is an adapter satisfying the interface at the processOrder module seam
```

## Designing for testability

**Accept dependencies, don't create them.**

```python
# Testable
def processOrder(order, paymentGateway: PaymentGateway): # paymentGateway is a seam of the processOrder module
    ...

# Hard to test
def processOrder(order):
    gateway = StripeGateway()
    ...
```

**Return results, don't produce side effects.**

```python
# Testable
def calculateDiscount(cart) -> Discount:
    ...

# Hard to test
def applyDiscount(cart) -> None:
    cart.total -= discount
    ...
```

## Gotchas

- **Protocol parameter names must match** for structural compatibility — renaming `charge(self, amount)` to `charge(self, amt)` silently breaks the match.
