# Testing in Python

The sections in [SKILL.md](SKILL.md) are language-agnostic. This file is its Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` module. Consider the setup:

```python
class PaymentGateway(Protocol):

    def charge(self, amount: float) -> bool: ...

type OrderProcessor = Callable[[Order], Receipt]

def create_order_processor(
    gateway: PaymentGateway # Seam is passed in the factory for the OrderProcessor module
) -> OrderProcessor:
    def process_order(order: Order) -> Receipt:
        total = 0
        for item in order.items:
            total += item.cost
        payment_successful = gateway.charge(total)
        if not payment_successful:
            raise ...
        return Receipt(
            total=total
        )
    return process_order
```

The test adapter — a working fake, no mock library:

```python
class FakeGateway:                           # a test adapter: decides inward, records outward
    def __init__(self) -> None:
        self.charges: list[float] = []

    def charge(self, amount: float) -> bool: # satisfies the Protocol by shape — no inheritance
        self.charges.append(amount)          # records what crosses the seam outward
        return True                          # decides what crosses inward
```

The test:

```python
def order_with(prices: list[float]) -> Order:  # a harness helper: construction lives in the kit, not the test
    return Order([Item(f"Item {i}", price) for i, price in enumerate(prices)])

def setup(
    gateway: PaymentGateway
) -> OrderProcessor: # Use a helper to wrap the module factory so future changes to the factory design can be localised in the test file
    return create_order_processor(
        gateway
    )

@pytest.mark.parametrize("prices, expected_charge", [
    ([100], 100),                            # worked examples, chosen by hand
    ([100, 40], 140),
])
def test_charges_the_gateway_the_order_total(prices, expected_charge):
    gateway = FakeGateway()                    # the test adapter at the seam
    order_processor = setup(gateway)
    order_processor(order_with(prices))          # driven through the interface
    assert gateway.charges == [expected_charge]    # the outcome crosses the seam — seen by the adapter that receives it
```

- The name is the capability, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each parametrize case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.

## Anti-patterns

**Tautological** — the oracle is the source code:

```python
from order_processor import calculate_total           # a source-code helper

def test_totals_the_receipt():      # tautological
    gateway = FakeGateway()
    order_processor = setup(gateway)
    order = order_with([100, 40])
    assert order_processor(order).total == calculate_total(order)
    # whatever bug calculate_total carries, the expectation inherits —
    # the test agrees by construction and can never disagree
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`sum(prices)`); the strongest form is section 1's hand-picked worked examples.

**Implementation-coupled** — patching the implementation's internals:

```python
from unittest.mock import patch

@patch("order_processor.sum")                        # reaches inside the implementation
def test_sums_the_prices(fake_sum):
    gateway = FakeGateway()
    order_processor = setup(gateway)
    fake_sum.return_value = 100
    order_processor(order_with([100, 40]))
    fake_sum.assert_called_once()
```

The tell: swap `sum()` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the interface's side of the seam. The fix: observation belongs at the seams the interface exposes — the fake gateway's `charges` — not inside the implementation's helpers. (Patching internals and asserting private attributes are this pattern's two common Python shapes.)
