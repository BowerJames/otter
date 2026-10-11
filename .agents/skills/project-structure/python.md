# Project Structure in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Package** | a directory with an `__init__.py` |
| **Entry point** | the package's `__init__.py`, re-exporting names and listing them in `__all__` |
| **Data carrier** | a frozen `dataclass` |
| **Domain package** | a `domain` package with one file per concept — `domain/order.py` |

Python calls every `.py` file a "module". In these skills **module** keeps its codebase-design meaning, so this file says "file" for a `.py` file.

Files behind the entry point are prefixed with `_`, which marks them as not for import from outside the package.

## Example 1: first use

`Order` is first needed by the `OrderProcessor` module, so it is defined in that module's package.

```
src/
  order_processor/
    __init__.py            # the entry point
    _order_processor.py    # OrderProcessor, create_order_processor
    _types.py              # Order, OrderItem, Receipt
  payment_gateway/
    __init__.py            # the entry point
    _payment_gateway.py    # PaymentGateway, create_payment_gateway
    _stripe.py             # StripeGateway
    _paypal.py             # PaypalGateway
```

```python
# order_processor/__init__.py
from ._order_processor import OrderProcessor, create_order_processor
from ._types import Order, OrderItem, Receipt

__all__ = ["Order", "OrderItem", "OrderProcessor", "Receipt", "create_order_processor"]
```

```python
# payment_gateway/__init__.py
from ._payment_gateway import PaymentGateway, create_payment_gateway

__all__ = ["PaymentGateway", "create_payment_gateway"]  # StripeGateway and PaypalGateway are not exported
```

`Order` and `Receipt` appear in the `OrderProcessor` interface, so the entry point exports them. Another package imports only from an entry point:

```python
# order_processor/_order_processor.py
from payment_gateway import PaymentGateway           # good: the entry point
from payment_gateway._stripe import StripeGateway    # bad: reaches behind the entry point
```

## Example 2: second use

Three new modules each need `Order`. Each one meets a different question from rule 2.

**Only a slice.** An `AuditLog` module records which orders were processed. It reads only the id, so it declares its own interface and imports nothing:

```python
# audit_log/_audit_log.py
from typing import Protocol

class Identified(Protocol):        # the slice of Order this module needs
    @property
    def id(self) -> str: ...
```

`Order` satisfies `Identified` by shape, so an `Order` can be passed without `audit_log` knowing the type exists.

**Already depends on the owner.** A `Checkout` module is built on top of an `OrderProcessor`, so it already imports that module's interface. It imports `Order` from the same entry point:

```python
# checkout/_checkout.py
from order_processor import Order, OrderProcessor, Receipt
```

**Otherwise.** An `Invoicing` module needs the whole `Order` and has nothing to do with order processing. `Order` now has no single owner, so it moves to the domain package:

```
src/
  domain/
    order.py               # Order, OrderItem
  invoicing/
    __init__.py
    _invoicing.py          # from domain.order import Order
  order_processor/
    __init__.py
    _order_processor.py    # from domain.order import Order
    _types.py              # Receipt stays: only this module's interface uses it
```

The entry point can keep re-exporting `Order` while callers are updated, so the move is one definition and its import lines:

```python
# order_processor/__init__.py
from domain.order import Order, OrderItem    # re-exported until callers import from domain.order
from ._order_processor import OrderProcessor, create_order_processor
from ._types import Receipt
```

Tests that drive `OrderProcessor` through its factory and interface do not change.

## Checking the rules

[import-linter](https://import-linter.readthedocs.io/) can enforce rule 3: a `forbidden` contract stops `domain` importing from any module's package, and a `layers` contract fixes the direction of imports between packages, which rules out cycles.
