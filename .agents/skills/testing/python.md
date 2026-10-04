# Testing in Python

The sections in [SKILL.md](SKILL.md) are language-agnostic. This file is its Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## What makes a good test

```python
from typing import Protocol

class PaymentGateway(Protocol):              # the interface at the seam
    def charge(self, amount: float) -> bool: ...

def checkout(cart: Cart, gateway: PaymentGateway) -> Receipt: ...
                                             # the module under test — driven, never opened
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
def cart_with(prices: list[float]) -> Cart:  # a harness helper: construction lives in the kit, not the test
    return Cart([Item(f"Item {i}", price) for i, price in enumerate(prices)])

@pytest.mark.parametrize("prices, expected_charge", [
    ([100], 100),                            # worked examples, chosen by hand
    ([100, 40], 140),
])
def test_checking_out_charges_the_gateway_the_cart_total(prices, expected_charge):
    gateway = FakeGateway()                       # the test adapter at the seam
    checkout(cart_with(prices), gateway)          # driven through the interface
    assert gateway.charges == [expected_charge]    # the outcome crosses the seam — seen by the adapter that receives it
```

- The name is the capability, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each parametrize case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never recomputes them the way `checkout` does.
- Raised outcomes are the third observation route: `with pytest.raises(PaymentDeclined): checkout(...)` — assert the exception's shape (args, message), not just its type.

## Test through seams

```python
from datetime import datetime

def checkout(cart: Cart, gateway: PaymentGateway, clock: Callable[[], datetime]) -> Receipt:
    ...                                   # two seams: a collaborator and the clock
```

Fixtures wire the graph — the test's composition point:

```python
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)   # the clock's fixed reading — defined once

@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()

@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    return lambda: FIXED_NOW                 # a lambda fake: the clock's outcome, decided by the test
```

Every seam substituted — control at the clock, observation at the gateway:

```python
def test_checking_out_stamps_the_receipt_with_the_charge_time(fake_gateway, fixed_clock):
    receipt = checkout(cart_with([100]), fake_gateway, fixed_clock)
    assert receipt.charged_at == FIXED_NOW   # the clock's reading, stamped on the receipt
```

The exception, not the default — a real adapter kept in place:

```python
receipt = checkout(cart_with([100]), FakeGateway(), clock=datetime.now)
# the exception, not the default: the real clock widens the module under test past
# that seam — a resource now in play, so this is no longer a unit test. The price:
# charged_at is undecidable, and a clock failure fails this test. Take it only when
# the real adapter is cheap, fast, and trustworthy enough to earn its place.
```

- The fixture is the test's composition point (per dependency-injection's python.md): the only place the concretes — here, the test adapters — are named.
- The lambda is the smallest fake: a whole working substitute for a one-function seam.
- Substituting at every seam is the default — that is what makes the test a unit test: fast, decidable, localising. Widening past a seam is the exception: it buys real behaviour at the price of control and localisation there, and forfeits the unit test properties.

## Test-driven development

Section 1's test, written first — both conditions in one test, from the start:

```python
@pytest.mark.parametrize("prices, expected_charge", [
    ([100], 100),                            # worked examples, chosen by hand
    ([100, 40], 140),
])
def test_checking_out_charges_the_gateway_the_cart_total(prices, expected_charge):
    gateway = FakeGateway()
    checkout(cart_with(prices), gateway)
    assert gateway.charges == [expected_charge]
```

Python has no compiler — mypy stands in for one. It fails first, statically:

```python
# mypy: error: Name "checkout" is not defined
# a missing symbol, caught before any test runs — the wrong reason, at compile time
```

Just enough skeleton — a signature, a stub, nothing more. The symbol exists, mypy passes:

```python
def checkout(cart: Cart, gateway: PaymentGateway) -> Receipt: ...
```

Now run the test — red for the right reason: it runs, calls the interface, and fails at its assertion on the missing behaviour:

```python
# AssertionError: assert [] == [100]
```

Green, minimally. The test observes one outcome — the charge crossing the seam — so the implementation fixes exactly that and nothing else:

```python
def checkout(cart: Cart, gateway: PaymentGateway) -> Receipt:
    gateway.charge(sum(item.price for item in cart.items))   # the asserted behaviour
    return Receipt()   # the returned total is not fixed — no test has asked for it yet
```

Cycle 2 — the next behaviour: the receipt totals the charge. The same worked examples, observed at a different point:

```python
@pytest.mark.parametrize("prices, expected_total", [
    ([100], 100),
    ([100, 40], 140),
])
def test_checking_out_totals_the_receipt(prices, expected_total):
    receipt = checkout(cart_with(prices), FakeGateway())
    assert receipt.total == expected_total
```

Red for the right reason — checkout exists, so mypy passes; the test runs and fails at its assertion on the unfixed total:

```python
# AssertionError: assert None == 100
```

Green — fix exactly what this test asked for:

```python
def checkout(cart: Cart, gateway: PaymentGateway) -> Receipt:
    total = sum(item.price for item in cart.items)
    gateway.charge(total)
    return Receipt(total=total)          # fixed — by the test that asked for it
```

- Python has no compiler; the type checker is the compile step. A missing symbol is a mypy error before it is ever a runtime `NameError` — the skeleton exists to pass that check, moving the failure to the assertion, where the behaviour is actually asked.
- The `...` stub is Python's "just enough skeleton": mypy accepts the signature, the test runs, and it fails *at its assertion* — never on a missing symbol. (`raise NotImplementedError` also marks absence, but it fails at the call, before the assertion.)
- Minimal means only the asserted outcome exists: the charge is correct because the test observes it; the unfixed receipt total is "no speculative features" made visible — nothing is implemented the suite hasn't asked for.
- The two cycles observe through both routes: cycle 1's outcome crosses a seam (seen by the test adapter), cycle 2's outcome returns through the interface.
- Green stays green: the first test passes unchanged through cycle 2 — a new red elsewhere means fix backwards before writing forwards.

## Anti-patterns

**Tautological** — the oracle is the source code:

```python
from orders import calculate_total           # a source-code helper

def test_checkout_totals_the_receipt():      # tautological
    cart = cart_with([100, 40])
    assert checkout(cart, FakeGateway()).total == calculate_total(cart)
    # whatever bug calculate_total carries, the expectation inherits —
    # the test agrees by construction and can never disagree
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`sum(prices)`); the strongest form is section 1's hand-picked worked examples.

**Implementation-coupled** — patching the implementation's internals:

```python
from unittest.mock import patch

@patch("orders.sum")                        # reaches inside the implementation
def test_checkout_sums_the_prices(fake_sum):
    fake_sum.return_value = 100
    checkout(cart_with([100, 40]), FakeGateway())
    fake_sum.assert_called_once()           # verifies how, not what
```

The tell: swap `sum()` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the interface's side of the seam. The fix: observation belongs at the seams the interface exposes — the fake gateway's `charges` — not inside the implementation's helpers. (Patching internals and asserting private attributes are this pattern's two common Python shapes.)

## Gotchas

- **Unspecced `MagicMock` satisfies any Protocol silently.** It auto-creates every attribute, so a renamed method on the interface drifts by unnoticed — a hand-rolled fake fails loudly on the missing shape. Using the mock library at a seam: `spec=` (or `create_autospec`) is the minimum.
- **`Test*`-prefixed classes are collected as tests.** Name a fake `TestGateway` and pytest tries to run it. Fakes are `Fake...`, mocks are `Mock...`.
- **A shared mutable fake leaks state across tests.** A function-scoped fixture (the default) constructs a fresh fake per test — our `fake_gateway` does. A wider-scoped fixture carrying `FakeGateway.charges` makes each test see the previous one's crossings.
- **Float equality.** `assert total == 0.3` fails on binary rounding — `pytest.approx(total) == 0.3` compares what was meant. (Or take the real fix: don't represent money as floats.)
