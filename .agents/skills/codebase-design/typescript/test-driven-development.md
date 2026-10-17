# Test-driven development in TypeScript

Below follows an example for a TDD approach towards building an `OrderProcessor` component. Nothing exists before the first test. Files are placed as [project-structure](../project-structure.md) describes.

## First TDD Cycle

**Red**

The first behaviour to pin is that an order processor charges the total of the items in the order. Charging is a new dependency of the component, so this behaviour adds its first port, `payments`, and a fake for it is written in the same cycle:

```ts
// tests/unit/components/order-processor/fakes.ts
import type { Payments } from "../../../../src/components/order-processor";

export interface FakePayments extends Payments {
  charges: number[];
}

export function newFakePayments(): FakePayments {
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

```ts
// tests/unit/components/order-processor/order-processor.test.ts
import { expect, test } from "vitest";

import { newOrderProcessor } from "../../../../src/components/order-processor";
import type { Order } from "../../../../src/components/order-processor";
import { newFakePayments } from "./fakes";

function setup() {
  const payments = newFakePayments();
  const orderProcessor = newOrderProcessor(payments);
  return { payments, orderProcessor };
}

function orderWith(costs: number[]): Order {
  return {
    id: "order_id",
    items: costs.map((cost, i) => ({ name: `item_${i}`, cost })),
  };
}

test.each([
  { costs: [100], expectedCharge: 100 },
  { costs: [100, 40], expectedCharge: 140 },
])("charges the payments port the order total ($costs)", ({ costs, expectedCharge }) => {
  const { payments, orderProcessor } = setup();
  orderProcessor(orderWith(costs));
  expect(payments.charges).toEqual([expectedCharge]);
});
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because nothing they import exists. A true red state requires that the type checker passes but the tests are failing. Vitest does not type check, so `tsc --noEmit` is the compile step and is run alongside the tests. So the component's package is created with just enough skeleton to get there. `Order` and `Receipt` appear in the component's interface, so they go in its data file:

```ts
// src/components/order-processor/data.ts
export interface OrderItem {
  readonly name: string;
  readonly cost: number;
}

export interface Order {
  readonly id: string;
  readonly items: readonly OrderItem[];
}

export interface Receipt {
  readonly total: number;
}
```

```ts
// src/components/order-processor/ports.ts
export interface Payments {
  charge(amount: number): boolean;
}
```

```ts
// src/components/order-processor/interface.ts
import type { Order, Receipt } from "./data";

export interface OrderProcessor {
  (order: Order): Receipt;
}
```

```ts
// src/components/order-processor/implementation.ts
import type { OrderProcessor } from "./interface";
import type { Payments } from "./ports";

export function newOrderProcessor(payments: Payments): OrderProcessor {
  return function processOrder(order) {
    throw new Error("not implemented");
  };
}
```

```ts
// src/components/order-processor/index.ts
export type { Order, OrderItem, Receipt } from "./data";
export { newOrderProcessor } from "./implementation";
export type { OrderProcessor } from "./interface";
export type { Payments } from "./ports";
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

Only enough implementation to pass:

```ts
// src/components/order-processor/implementation.ts
export function newOrderProcessor(payments: Payments): OrderProcessor {
  return function processOrder(order) {
    let total = 0;
    for (const item of order.items) {
      total += item.cost;
    }
    payments.charge(total);
    return { total };
  };
}
```

Green state achieved.

**Refactor**

With the suite green, the loop is replaced with `reduce`. No test changes, and the suite stays green:

```ts
// src/components/order-processor/implementation.ts
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    payments.charge(total);
    return { total };
  };
```

## Second TDD Cycle

**Red**

The next behaviour to pin is that an order processor refuses an order the payments port declines. It needs nothing new from outside the component, so no port is added: the fake learns to decline:

```ts
// tests/unit/components/order-processor/fakes.ts
export function newFakePayments(accepts = true): FakePayments {
  const charges: number[] = [];
  return {
    charges,
    charge(amount) {
      charges.push(amount);
      return accepts;
    },
  };
}
```

```ts
// tests/unit/components/order-processor/order-processor.test.ts
import { PaymentDeclined } from "../../../../src/components/order-processor";

test("refuses an order the payments port declines", () => {
  const orderProcessor = newOrderProcessor(newFakePayments(false));
  expect(() => orderProcessor(orderWith([100]))).toThrow(PaymentDeclined);
});
```

The refusal is determined by the component's implementation, so the component defines the error in its errors file and exports it:

```ts
// src/components/order-processor/errors.ts
export class PaymentDeclined extends Error {}
```

The type checker passes and the test fails because nothing is thrown: a proper red.

**Green**

```ts
// src/components/order-processor/implementation.ts
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!payments.charge(total)) {
      throw new PaymentDeclined(order.id);
    }
    return { total };
  };
```

**Refactor**

Nothing is worth changing yet, so the refactor step is empty.

The cycles continue until the required behaviours are all pinned. A behaviour such as charging in a configured currency would add `currency` to the constructor as configuration and to the payments port's `charge` method, in the same cycle as its test. A behaviour such as stamping the receipt with the time it was placed needs a new dependency, so it adds a second port, `clock: Clock`, and a fake for it, in the same cycle as its test: it never adds a `now` method to the payments port.

## After the cycles

The component now exists and has only ever been constructed with fakes. The `StripePayments` edge component that will satisfy its `payments` port is driven by its own cycles, with a fake of its `SyncFetch` view: the `sync-fetch` library it calls offers no test hook. The factories and the entrypoints are written last: see [project-structure](../project-structure.md) for where they go and [dependency-injection](../dependency-injection.md) for what the factories do.
