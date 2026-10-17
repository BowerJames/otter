# Testing in Python

The sections in [testing.md](../testing.md) are language-agnostic. This file is its Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [python/codebase-design.md](codebase-design.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` component. Consider the setup:

```python
class Payments(Protocol): # The interface of the payments port
    def charge(self, amount: int, currency: Currency) -> bool: ...

type Clock = Callable[[], datetime] # The interface of the clock port

type OrderProcessor = Callable[[Order], Receipt]

class OrderProcessorImpl:
    def __init__(
        self,
        payments: Payments, # A port, passed to the constructor
        clock: Clock, # A port, passed to the constructor
        currency: Currency
    ):
        self.payments = payments
        self.clock = clock
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.payments.charge(total, self.currency):
            raise PaymentDeclined(order.id)
        return Receipt(total=total, currency=self.currency, at=self.clock())
```

The fake for the payments port — a working fake, no mock library:

```python
class FakePayments(Payments): # a fake: decides what comes in, records what goes out
    def __init__(self, accepts: bool = True) -> None:
        self.accepts = accepts
        self.charges: list[tuple[int, Currency]] = []

    def charge(self, amount: int, currency: Currency) -> bool: # satisfies the port; the inheritance is a reminder of which one
        self.charges.append((amount, currency)) # records what goes out through the port
        return self.accepts                     # decides what comes in
```

The clock's port is a function, so its fake is a function too: `lambda: NOON`.

The test:

```python
NOON = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

def order_with(costs: list[int]) -> Order:  # a harness helper: construction lives in the kit, not the test
    return Order(id="order_id", items=tuple(OrderItem(name=f"item_{i}", cost=cost) for i, cost in enumerate(costs)))

def setup(
    payments: Payments | None = None,
    clock: Clock = lambda: NOON,
    currency: Currency = "GBP"
) -> OrderProcessor: # Use a helper to wrap the component constructor so future changes to the constructor design can be localised in the test file
    return OrderProcessorImpl(payments or FakePayments(), clock, currency)

@pytest.mark.parametrize("costs, expected_charge", [
    ([100], 100),                            # worked examples, chosen by hand
    ([100, 40], 140),
])
def test_charges_the_payments_port_the_order_total(costs, expected_charge):
    payments = FakePayments()                    # the fake for the port this behaviour touches
    order_processor = setup(payments)            # constructed through the constructor, never a factory
    order_processor(order_with(costs))           # driven through the interface
    assert payments.charges == [(expected_charge, "GBP")]  # the outcome goes out through the port — seen by the fake that receives it

def test_stamps_the_receipt_with_the_time_from_the_clock():
    order_processor = setup(clock=lambda: NOON)  # only the clock's fake matters to this behaviour
    assert order_processor(order_with([100])).at == NOON
```

- The name is the behaviour, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each parametrize case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.
- Each port has its own fake, so a behaviour that touches one port is arranged through that fake alone, and the helper defaults the others.

An error the component determines is a behaviour, arranged through a fake and observed at the interface:

```python
def test_refuses_an_order_the_payments_port_declines():
    order_processor = setup(FakePayments(accepts=False))
    with pytest.raises(PaymentDeclined):
        order_processor(order_with([100]))
```

## Testing at the edge

### Adapters

An adapter is constructed with fakes of the interfaces of the components it calls, and driven through the port's interface it satisfies:

```python
class FakeOrderProcessor:                        # a fake of the interface the adapter takes: OrderProcessor
    def __init__(self) -> None:
        self.orders: list[Order] = []

    def __call__(self, order: Order) -> Receipt:
        self.orders.append(order)
        return Receipt(total=140, currency="GBP", at=NOON)

def test_pays_for_a_cart_by_ordering_each_line():
    order_processor = FakeOrderProcessor()
    payment = OrderProcessorAdapter(order_processor)  # the adapter's constructor, given a fake
    payment.pay(Cart(id="cart_id", lines=(CartLine("tea", 100), CartLine("cake", 40))))
    assert [item.cost for item in order_processor.orders[0].items] == [100, 40]
```

A decorator is constructed with a fake of the interface it wraps:

```python
def test_refuses_a_charge_over_the_limit_without_calling_the_payments_it_wraps():
    inner = FakePayments()
    payments = LimitedPayments(inner, limit=1_000)
    assert payments.charge(1_001, "GBP") is False
    assert inner.charges == []
```

### Outbound edge components

A `StripePayments` edge component that takes the library's own `httpx.Client` is unit tested with the library's own test hook, `httpx.MockTransport`: a real client that answers from a function, with no network:

```python
class StripePaymentsImpl:
    def __init__(self, http: httpx.Client, api_key: str): ... # everything required to measure its behaviours

    def charge(self, amount: int, currency: Currency) -> bool: ...
```

```python
def client_answering(status: int, sent: list[httpx.Request]) -> httpx.Client: # harness: a client on the library's test hook
    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)                     # records what goes out
        return httpx.Response(status)            # decides what comes in
    return httpx.Client(transport=httpx.MockTransport(answer))

def test_charge_sends_the_currency_in_lower_case():
    sent: list[httpx.Request] = []
    stripe = StripePaymentsImpl(http=client_answering(200, sent), api_key="test-key")
    stripe.charge(1250, "GBP")                   # driven through its interface
    assert parse_qs(sent[0].content.decode())["currency"] == ["gbp"]

def test_charge_answers_false_when_the_card_is_declined():
    stripe = StripePaymentsImpl(http=client_answering(402, []), api_key="test-key")
    assert stripe.charge(1250, "GBP") is False
```

Where a library offers no test hook, the edge component declares a view of the part of it that it uses, and the test passes a fake of the view:

```python
class Publisher(Protocol):                       # a view: the library's broker client satisfies it by shape
    def publish(self, topic: str, body: bytes) -> None: ...

class FakePublisher:                             # a fake of the view
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, body: bytes) -> None:
        self.published.append((topic, body))

def test_announces_each_receipt_on_the_receipts_topic():
    publisher = FakePublisher()
    BrokerReceipts(publisher).announce(Receipt(total=100, currency="GBP", at=NOON))
    assert [topic for topic, _ in publisher.published] == ["receipts"]
```

### A component that opens sessions

A lifecycle is tested the way a caller uses it, through the opening call. The realtime model's connection comes from a library with no test hook, so the edge component declares a view of it, and the test passes a fake:

```python
class FakeConnection:                            # a fake of the RealtimeConnection view
    def __init__(self, arriving: list[dict[str, Any]]) -> None:
        self.sent: list[dict[str, Any]] = []
        self.arriving = arriving
        self.closed = False

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)                  # records what goes out

    async def recv(self) -> dict[str, Any]:
        return self.arriving.pop(0)              # decides what comes in

def fake_connect(connection: FakeConnection) -> Connect: # a fake of the Connect view
    @asynccontextmanager
    async def connect(*, model: str) -> AsyncIterator[FakeConnection]:
        yield connection
        connection.closed = True
    return connect

async def test_a_session_sends_each_event_it_is_given():
    connection = FakeConnection(arriving=[])
    model = OpenAIRealtimeModel(fake_connect(connection), model_name="gpt-realtime")
    async with model.connect() as session:
        await session.send(SPEAK_HELLO)
    assert connection.sent == [SPEAK_HELLO_EVENT]

async def test_closing_the_session_closes_the_connection():
    connection = FakeConnection(arriving=[])
    model = OpenAIRealtimeModel(fake_connect(connection), model_name="gpt-realtime")
    async with model.connect():
        pass
    assert connection.closed
```

### Inbound edge components

An inbound edge component is driven the way its framework calls it. FastAPI's `TestClient` runs the app in-process, reaching no resource, so the test is a unit test. The router is built by its constructor with a fake for its port, never by its factory:

```python
class FakePlaceOrder:                            # a fake for the router's place_order port
    def __init__(self, placed: Placed | None) -> None:
        self.placed = placed
        self.orders: list[NewOrder] = []

    def __call__(self, new_order: NewOrder) -> Placed | None:
        self.orders.append(new_order)
        return self.placed

def client_for(router: APIRouter) -> TestClient: # harness: mounts the router as FastAPI would
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

def test_reads_each_cost_into_the_new_order():
    place_order = FakePlaceOrder(placed=Placed(total=140, currency="GBP"))
    client_for(orders_router(place_order)).post("/orders", json={"id": "order_id", "costs": [100, 40]})
    assert place_order.orders[0].costs == (100, 40)

def test_answers_402_when_the_order_is_declined():
    response = client_for(orders_router(FakePlaceOrder(placed=None))).post("/orders", json={"id": "order_id", "costs": [100]})
    assert response.status_code == 402
```

A Click command is driven the same way, through Click's `CliRunner`:

```python
def test_prints_the_total_of_the_placed_order():
    result = CliRunner().invoke(orders_cli(FakePlaceOrder(placed=Placed(total=140, currency="GBP"))), ["order_id", "100", "40"])
    assert "total=140 GBP" in result.output
```

### Integration and end-to-end tests

Integration tests and end-to-end tests are kept apart from the unit tests with markers, so the default run needs no environment:

```python
@pytest.mark.integration                         # runs an edge component against the real resource
def test_saves_and_loads_an_order(pool):
    orders = PostgresOrders(pool)
    orders.save(order_with([100]))
    assert orders.load("order_id").items[0].cost == 100

@pytest.mark.e2e                                 # optional: runs an entrypoint with the production factories
def test_cli_processes_an_order():
    result = subprocess.run(["shop", "order_id", "100"], capture_output=True, text=True)
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
from shop.components.order_processor.implementation import calculate_total   # a source-code helper

def test_totals_the_receipt():      # tautological
    order_processor = setup()
    order = order_with([100, 40])
    assert order_processor(order).total == calculate_total(order)
    # whatever bug calculate_total carries, the expectation inherits —
    # the test agrees by construction and can never disagree
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`sum(costs)`); the strongest form is the hand-picked worked examples above.

**Implementation-coupled** — patching the implementation's internals:

```python
from unittest.mock import patch

@patch("shop.components.order_processor.implementation.sum")    # reaches inside the implementation
def test_sums_the_costs(fake_sum):
    order_processor = setup()
    fake_sum.return_value = 100
    order_processor(order_with([100, 40]))
    fake_sum.assert_called_once()
```

The tell: swap `sum()` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the outside of the interface. The fix: observation belongs at the interface and the ports — the fake's `charges` — not inside the implementation's helpers. (Patching internals and asserting private attributes are this pattern's two common Python shapes.)

**Faked foreign component** — a hand-written stand-in for a library that has a test hook:

```python
class FakeHttpxClient:                           # agrees with what its author believed httpx does
    def post(self, url: str, data: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(status_code=200)

stripe = StripePaymentsImpl(http=FakeHttpxClient(), api_key="test-key")   # type: ignore
```

The fix: pass the library's own client on its test hook, `httpx.MockTransport`, as above. Declare a view and fake it only where the library has no hook.
