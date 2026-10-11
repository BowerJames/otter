# Testing in TypeScript

The sections in [SKILL.md](SKILL.md) are language-agnostic. This file is its TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` module. Consider the setup:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}

type OrderProcessor = (order: Order) => Receipt;

function createOrderProcessor(
  gateway: PaymentGateway, // Seam is passed in the factory for the OrderProcessor module
): OrderProcessor {
  return function processOrder(order) {
    let total = 0;
    for (const item of order.items) {
      total += item.cost;
    }
    const paymentSuccessful = gateway.charge(total);
    if (!paymentSuccessful) {
      throw new Error(/* ... */);
    }
    return { total };
  };
}
```

The test adapter — a working fake, no mock library:

```ts
interface FakeGateway extends PaymentGateway { // a test adapter: decides inward, records outward
  charges: number[];
}

function createFakeGateway(): FakeGateway {
  const charges: number[] = [];
  return {
    charges,
    charge(amount) {        // satisfies PaymentGateway by shape
      charges.push(amount); // records what crosses the seam outward
      return true;          // decides what crosses inward
    },
  };
}
```

The test:

```ts
import { expect, test } from "vitest";

function orderWith(prices: number[]): Order { // a harness helper: construction lives in the kit, not the test
  return {
    id: "order_id",
    items: prices.map((price, i) => ({ name: `Item ${i}`, cost: price })),
  };
}

function setup(gateway: PaymentGateway): OrderProcessor { // Use a helper to wrap the module factory so future changes to the factory design can be localised in the test file
  return createOrderProcessor(gateway);
}

test.each([
  { prices: [100], expectedCharge: 100 },      // worked examples, chosen by hand
  { prices: [100, 40], expectedCharge: 140 },
])("charges the gateway the order total ($prices)", ({ prices, expectedCharge }) => {
  const gateway = createFakeGateway();               // the test adapter at the seam
  const orderProcessor = setup(gateway);
  orderProcessor(orderWith(prices));                 // driven through the interface
  expect(gateway.charges).toEqual([expectedCharge]); // the outcome crosses the seam — seen by the adapter that receives it
});
```

- The name is the capability, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each `test.each` case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.

## Anti-patterns

**Tautological** — the oracle is the source code:

```ts
import { calculateTotal } from "./order-processor"; // a source-code helper

test("totals the receipt", () => { // tautological
  const gateway = createFakeGateway();
  const orderProcessor = setup(gateway);
  const order = orderWith([100, 40]);
  expect(orderProcessor(order).total).toBe(calculateTotal(order));
  // whatever bug calculateTotal carries, the expectation inherits —
  // the test agrees by construction and can never disagree
});
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`prices.reduce((sum, price) => sum + price, 0)`); the strongest form is section 1's hand-picked worked examples.

**Implementation-coupled** — mocking the implementation's internals:

```ts
import { expect, test, vi } from "vitest";
import { sumCosts } from "./totals"; // a helper the implementation calls internally

vi.mock("./totals");                 // reaches inside the implementation

test("sums the prices", () => {
  const gateway = createFakeGateway();
  const orderProcessor = setup(gateway);
  vi.mocked(sumCosts).mockReturnValue(100);
  orderProcessor(orderWith([100, 40]));
  expect(sumCosts).toHaveBeenCalledOnce();
});
```

The tell: swap `sumCosts` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the interface's side of the seam. The fix: observation belongs at the seams the interface exposes — the fake gateway's `charges` — not inside the implementation's helpers. (Module mocking and exporting internals just so a test can reach them are this pattern's two common TypeScript shapes.)
