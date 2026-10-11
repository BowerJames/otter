# Test-driven development in TypeScript

Below follows an example for a TDD approach towards building an `OrderProcessor` module. We can assume elsewhere in the codebase the following `PaymentGateway` module has already been designed and has the following interface:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}
```

## First TDD Cycle

**Red**

The first thing we need is a factory for producing order processors:

```ts
import { test } from "vitest";

import { createOrderProcessor } from "./order-processor";

function setup() {
  return { orderProcessor: createOrderProcessor() };
}

test("can create an order processor", () => {
  setup();
});
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because `createOrderProcessor` does not exist to import. A true red state requires that the type checker passes but the tests are failing. Vitest does not type check, so `tsc --noEmit` is the compile step and is run alongside the tests. So the following is added to the source code.

```ts
export interface OrderProcessor {}

export function createOrderProcessor(): OrderProcessor {
  throw new Error("not implemented");
}
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

```ts
export interface OrderProcessor {}

export function createOrderProcessor(): OrderProcessor {
  return {};
}
```

Green state achieved.

## Second TDD Cycle

**Red**

The next behaviour to pin would be that an order processor charges the payment gateway with the total of the items in the order. To do this we need to introduce a seam for the `PaymentGateway` interface and the `Order` data carrier. Start with creating a fake payment gateway:

```ts
export interface FakePaymentGateway extends PaymentGateway {
  charges: number[];
}

export function createFakePaymentGateway(): FakePaymentGateway {
  const charges: number[] = [];
  return {
    charges,
    charge(amount) {
      charges.push(amount);
      return true;
    },
  };
}
```

Then update the tests:

```ts
import { expect, test } from "vitest";

import { createOrderProcessor } from "./order-processor";
import { createFakePaymentGateway } from "./fakes";

function setup() {
  const paymentGateway = createFakePaymentGateway();
  const orderProcessor = createOrderProcessor(paymentGateway);
  return { paymentGateway, orderProcessor };
}

function orderWith(prices: number[]): Order {
  return {
    id: "order_id",
    items: prices.map((price, i) => ({ name: `item_${i}`, cost: price })),
  };
}

test("can create an order processor", () => {
  setup();
});

test.each([
  { prices: [100], expectedCharge: 100 },
  { prices: [100, 40], expectedCharge: 140 },
])("charges total of all order items ($prices)", ({ prices, expectedCharge }) => {
  const { paymentGateway, orderProcessor } = setup();
  const order = orderWith(prices);
  orderProcessor(order);
  expect(paymentGateway.charges).toEqual([expectedCharge]);
});
```

Now the type checker needs to be made to pass:

```ts
import type { PaymentGateway } from "./payment-gateway";

export interface OrderProcessor {
  (order: Order): Receipt;
}

export function createOrderProcessor(paymentGateway: PaymentGateway): OrderProcessor {
  return function processOrder(order) {
    throw new Error("not implemented");
  };
}
```

**Green**

```ts
import type { PaymentGateway } from "./payment-gateway";

export interface OrderProcessor {
  (order: Order): Receipt;
}

export function createOrderProcessor(paymentGateway: PaymentGateway): OrderProcessor {
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    paymentGateway.charge(total);
    return { total };
  };
}
```

This completes the second cycle. And the cycles would continue until the required behaviours are all pinned.
