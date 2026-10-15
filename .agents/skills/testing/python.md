# Testing in Python

The sections in [SKILL.md](SKILL.md) are language-agnostic. This file is its Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` module. Consider the setup:

```python
class OrderProcessorPort(Protocol): # The module's port
    def charge(self, amount: int, currency: Currency) -> bool: ...

type OrderProcessor = Callable[[Order], Receipt]

class OrderProcessorImpl:
    def __init__(
        self,
        port: OrderProcessorPort, # The port is passed to the constructor of the OrderProcessor module
        currency: Currency
    ):
        self.port = port
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.port.charge(total, self.currency):
            raise PaymentDeclined(order.id)
        return Receipt(total=total, currency=self.currency)
```

The test adapter — a working fake, no mock library:

```python
class FakeOrderProcessorAdapter(OrderProcessorPort): # a test adapter: decides what comes in, records what goes out
    def __init__(self, accepts: bool = True) -> None:
        self.accepts = accepts
        self.charges: list[tuple[int, Currency]] = []

    def charge(self, amount: int, currency: Currency) -> bool: # satisfies the port; the inheritance is a reminder of which one
        self.charges.append((amount, currency)) # records what goes out through the port
        return self.accepts                     # decides what comes in
```

The test:

```python
def order_with(costs: list[int]) -> Order:  # a harness helper: construction lives in the kit, not the test
    return Order(id="order_id", items=tuple(OrderItem(name=f"item_{i}", cost=cost) for i, cost in enumerate(costs)))

def setup(
    port: OrderProcessorPort,
    currency: Currency = "GBP"
) -> OrderProcessor: # Use a helper to wrap the module constructor so future changes to the constructor design can be localised in the test file
    return OrderProcessorImpl(port, currency)

@pytest.mark.parametrize("costs, expected_charge", [
    ([100], 100),                            # worked examples, chosen by hand
    ([100, 40], 140),
])
def test_charges_the_port_the_order_total(costs, expected_charge):
    port = FakeOrderProcessorAdapter()           # the test adapter for the port
    order_processor = setup(port)                # constructed through the constructor, never a factory
    order_processor(order_with(costs))           # driven through the interface
    assert port.charges == [(expected_charge, "GBP")]  # the outcome goes out through the port — seen by the adapter that receives it
```

- The name is the behaviour, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each parametrize case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.

An error the module determines is a behaviour, arranged through the test adapter and observed at the interface:

```python
def test_refuses_an_order_the_port_declines():
    order_processor = setup(FakeOrderProcessorAdapter(accepts=False))
    with pytest.raises(PaymentDeclined):
        order_processor(order_with([100]))
```

## Testing the infrastructure

An adapter is tested through the port it satisfies and its own constructor. A `StripeAdapter` that takes its HTTP dependency in the constructor can be unit tested with a test adapter:

```python
type HTTP = Callable[[Request], Response]

class StripeAdapter(OrderProcessorPort):
    def __init__(self, api_key: str, http: HTTP): ... # everything required to measure its behaviours

    def charge(self, amount: int, currency: Currency) -> bool: ...
```

```python
class FakeHTTP:                                  # a test adapter for the adapter's own port; HTTP is a type, so there is nothing to inherit
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        return Response(status=self.status)

def test_charge_sends_the_currency_in_lower_case():
    http = FakeHTTP()
    stripe = StripeAdapter(api_key="test-key", http=http)
    stripe.charge(1250, "GBP")                   # driven through the port it satisfies
    assert http.requests[0].body["currency"] == "gbp"

def test_charge_answers_false_when_the_card_is_declined():
    stripe = StripeAdapter(api_key="test-key", http=FakeHTTP(status=402))
    assert stripe.charge(1250, "GBP") is False
```

An entrypoint's constructor takes the interfaces it drives, so its translation is unit tested with a test adapter for each:

```python
class FakeOrderProcessor:                        # a test adapter for the entrypoint's port: the OrderProcessor interface
    def __init__(self) -> None:
        self.orders: list[Order] = []

    def __call__(self, order: Order) -> Receipt:
        self.orders.append(order)
        return Receipt(total=0, currency="GBP")

def test_cli_reads_each_cost_into_an_order_item():
    order_processor = FakeOrderProcessor()
    cli = Cli(order_processor)
    cli(["order_id", "100", "40"])
    assert [item.cost for item in order_processor.orders[0].items] == [100, 40]
```

Integration tests and end-to-end tests are kept apart from the unit tests with markers, so the default run needs no environment:

```python
@pytest.mark.integration                         # runs against the real resource
def test_saves_and_loads_an_order(connection):
    orders = PostgresAdapter(connection)
    orders.save(order_with([100]))
    assert orders.load("order_id").items[0].cost == 100

@pytest.mark.e2e                                 # optional: runs the startup code with the production factories
def test_cli_processes_an_order():
    result = subprocess.run(["python", "-m", "infrastructure.entrypoints.cli", "order_id", "100"], capture_output=True, text=True)
    assert "total=100" in result.stdout
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = ["integration", "e2e"]
addopts = "-m 'not integration and not e2e'"
```

## Anti-patterns

**Tautological** — the oracle is the source code:

```python
from core.order_processor.implementation import calculate_total   # a source-code helper

def test_totals_the_receipt():      # tautological
    order_processor = setup(FakeOrderProcessorAdapter())
    order = order_with([100, 40])
    assert order_processor(order).total == calculate_total(order)
    # whatever bug calculate_total carries, the expectation inherits —
    # the test agrees by construction and can never disagree
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`sum(costs)`); the strongest form is section 1's hand-picked worked examples.

**Implementation-coupled** — patching the implementation's internals:

```python
from unittest.mock import patch

@patch("core.order_processor.implementation.sum")    # reaches inside the implementation
def test_sums_the_costs(fake_sum):
    order_processor = setup(FakeOrderProcessorAdapter())
    fake_sum.return_value = 100
    order_processor(order_with([100, 40]))
    fake_sum.assert_called_once()
```

The tell: swap `sum()` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the outside of the interface. The fix: observation belongs at the interface and the port — the fake adapter's `charges` — not inside the implementation's helpers. (Patching internals and asserting private attributes are this pattern's two common Python shapes.)
