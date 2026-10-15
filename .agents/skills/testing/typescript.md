# Testing in TypeScript

The sections in [SKILL.md](SKILL.md) are language-agnostic. This file is its TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` module. Consider the setup:

```ts
interface OrderProcessorPort { // The module's port
  charge(amount: number, currency: Currency): boolean;
}

type OrderProcessor = (order: Order) => Receipt;

function newOrderProcessor(
  port: OrderProcessorPort, // The port is passed to the constructor of the OrderProcessor module
  currency: Currency,
): OrderProcessor {
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!port.charge(total, currency)) {
      throw new PaymentDeclined(order.id);
    }
    return { total, currency };
  };
}
```

The test adapter — a working fake, no mock library:

```ts
interface FakeOrderProcessorAdapter extends OrderProcessorPort { // a test adapter: decides what comes in, records what goes out
  charges: [number, Currency][];
}

function newFakeOrderProcessorAdapter(accepts = true): FakeOrderProcessorAdapter {
  const charges: [number, Currency][] = [];
  return {
    charges,
    charge(amount, currency) {        // satisfies the port by shape
      charges.push([amount, currency]); // records what goes out through the port
      return accepts;                   // decides what comes in
    },
  };
}
```

The test:

```ts
import { expect, test } from "vitest";

function orderWith(costs: number[]): Order { // a harness helper: construction lives in the kit, not the test
  return {
    id: "order_id",
    items: costs.map((cost, i) => ({ name: `item_${i}`, cost })),
  };
}

function setup(port: OrderProcessorPort, currency: Currency = "GBP"): OrderProcessor { // Use a helper to wrap the module constructor so future changes to the constructor design can be localised in the test file
  return newOrderProcessor(port, currency);
}

test.each([
  { costs: [100], expectedCharge: 100 },      // worked examples, chosen by hand
  { costs: [100, 40], expectedCharge: 140 },
])("charges the port the order total ($costs)", ({ costs, expectedCharge }) => {
  const port = newFakeOrderProcessorAdapter();          // the test adapter for the port
  const orderProcessor = setup(port);                   // constructed through the constructor, never a factory
  orderProcessor(orderWith(costs));                     // driven through the interface
  expect(port.charges).toEqual([[expectedCharge, "GBP"]]); // the outcome goes out through the port — seen by the adapter that receives it
});
```

- The name is the behaviour, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each `test.each` case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.

An error the module determines is a behaviour, arranged through the test adapter and observed at the interface:

```ts
test("refuses an order the port declines", () => {
  const orderProcessor = setup(newFakeOrderProcessorAdapter(false));
  expect(() => orderProcessor(orderWith([100]))).toThrow(PaymentDeclined);
});
```

## Testing the infrastructure

An adapter is tested through the port it satisfies and its own constructor. A Stripe adapter that takes its HTTP dependency in the constructor can be unit tested with a test adapter:

```ts
type Http = (request: HttpRequest) => HttpResponse;

function newStripeAdapter(apiKey: string, http: Http): OrderProcessorPort { // everything required to measure its behaviours
  return {
    charge(amount, currency) { /* ... */ },
  };
}
```

```ts
function newFakeHttp(status = 200) { // a test adapter for the adapter's own port
  const requests: HttpRequest[] = [];
  const http: Http = (request) => {
    requests.push(request);
    return { status };
  };
  return { http, requests };
}

test("charge sends the currency in lower case", () => {
  const { http, requests } = newFakeHttp();
  const stripe = newStripeAdapter("test-key", http);
  stripe.charge(1250, "GBP");                    // driven through the port it satisfies
  expect(requests[0].body.currency).toBe("gbp");
});

test("charge answers false when the card is declined", () => {
  const stripe = newStripeAdapter("test-key", newFakeHttp(402).http);
  expect(stripe.charge(1250, "GBP")).toBe(false);
});
```

An entrypoint's constructor takes the interfaces it drives, so its translation is unit tested with a test adapter for each:

```ts
function newFakeOrderProcessor() { // a test adapter for the entrypoint's port: the OrderProcessor interface
  const orders: Order[] = [];
  const orderProcessor: OrderProcessor = (order) => {
    orders.push(order);
    return { total: 0, currency: "GBP" };
  };
  return { orderProcessor, orders };
}

test("cli reads each cost into an order item", () => {
  const { orderProcessor, orders } = newFakeOrderProcessor();
  const cli = newCli(orderProcessor);
  cli(["order_id", "100", "40"]);
  expect(orders[0].items.map((item) => item.cost)).toEqual([100, 40]);
});
```

Integration tests and end-to-end tests are kept apart from the unit tests by directory, so the default run needs no environment:

```ts
// tests/integration/infrastructure/adapters/order-processor/postgres/postgres.test.ts
test("saves and loads an order", () => { // runs against the real resource
  const orders = newPostgresAdapter(pool);
  orders.save(orderWith([100]));
  expect(orders.load("order_id").items[0].cost).toBe(100);
});
```

```ts
// tests/e2e/cli.test.ts
test("cli processes an order", () => { // optional: runs the startup code with the production factories
  const output = execFileSync("tsx", ["src/infrastructure/entrypoints/cli.start.ts", "order_id", "100"], { encoding: "utf8" });
  expect(output).toContain("total=100");
});
```

```json
// package.json
{
  "scripts": {
    "test": "vitest run tests/unit",
    "test:integration": "vitest run tests/integration",
    "test:e2e": "vitest run tests/e2e"
  }
}
```

## Anti-patterns

**Tautological** — the oracle is the source code:

```ts
import { calculateTotal } from "../../../../src/core/order-processor/implementation"; // a source-code helper

test("totals the receipt", () => { // tautological
  const orderProcessor = setup(newFakeOrderProcessorAdapter());
  const order = orderWith([100, 40]);
  expect(orderProcessor(order).total).toBe(calculateTotal(order));
  // whatever bug calculateTotal carries, the expectation inherits —
  // the test agrees by construction and can never disagree
});
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`costs.reduce((sum, cost) => sum + cost, 0)`); the strongest form is section 1's hand-picked worked examples.

**Implementation-coupled** — mocking the implementation's internals:

```ts
import { expect, test, vi } from "vitest";
import { sumCosts } from "../../../../src/core/order-processor/totals"; // a helper the implementation calls internally

vi.mock("../../../../src/core/order-processor/totals");                 // reaches inside the implementation

test("sums the costs", () => {
  const orderProcessor = setup(newFakeOrderProcessorAdapter());
  vi.mocked(sumCosts).mockReturnValue(100);
  orderProcessor(orderWith([100, 40]));
  expect(sumCosts).toHaveBeenCalledOnce();
});
```

The tell: swap `sumCosts` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the outside of the interface. The fix: observation belongs at the interface and the port — the fake adapter's `charges` — not inside the implementation's helpers. (Module mocking and exporting internals just so a test can reach them are this pattern's two common TypeScript shapes.)
