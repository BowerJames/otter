# Test-driven development in TypeScript

Below follows an example for a TDD approach towards building an `OrderProcessor` module. Nothing exists before the first test. Files are placed as [project-structure](../project-structure/SKILL.md) describes.

## First TDD Cycle

**Red**

The first behaviour to pin is that an order processor charges the total of the items in the order. Charging reaches outside the module, so this behaviour needs the module's port, and a test adapter for it is written in the same cycle:

```ts
// tests/unit/core/order-processor/adapters.ts
import type { OrderProcessorPort } from "../../../../src/core/order-processor";

export interface FakeOrderProcessorAdapter extends OrderProcessorPort {
  charges: number[];
}

export function newFakeOrderProcessorAdapter(): FakeOrderProcessorAdapter {
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
// tests/unit/core/order-processor/order-processor.test.ts
import { expect, test } from "vitest";

import { newOrderProcessor } from "../../../../src/core/order-processor";
import type { Order } from "../../../../src/core/order-processor";
import { newFakeOrderProcessorAdapter } from "./adapters";

function setup() {
  const port = newFakeOrderProcessorAdapter();
  const orderProcessor = newOrderProcessor(port);
  return { port, orderProcessor };
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
])("charges the port the order total ($costs)", ({ costs, expectedCharge }) => {
  const { port, orderProcessor } = setup();
  orderProcessor(orderWith(costs));
  expect(port.charges).toEqual([expectedCharge]);
});
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because nothing they import exists. A true red state requires that the type checker passes but the tests are failing. Vitest does not type check, so `tsc --noEmit` is the compile step and is run alongside the tests. So the module's package is created with just enough skeleton to get there. `Order` and `Receipt` appear in the module's interface, so they go in its data file:

```ts
// src/core/order-processor/data.ts
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
// src/core/order-processor/port.ts
export interface OrderProcessorPort {
  charge(amount: number): boolean;
}
```

```ts
// src/core/order-processor/interface.ts
import type { Order, Receipt } from "./data";

export interface OrderProcessor {
  (order: Order): Receipt;
}
```

```ts
// src/core/order-processor/implementation.ts
import type { OrderProcessor } from "./interface";
import type { OrderProcessorPort } from "./port";

export function newOrderProcessor(port: OrderProcessorPort): OrderProcessor {
  return function processOrder(order) {
    throw new Error("not implemented");
  };
}
```

```ts
// src/core/order-processor/index.ts
export type { Order, OrderItem, Receipt } from "./data";
export { newOrderProcessor } from "./implementation";
export type { OrderProcessor } from "./interface";
export type { OrderProcessorPort } from "./port";
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

Only enough implementation to pass:

```ts
// src/core/order-processor/implementation.ts
export function newOrderProcessor(port: OrderProcessorPort): OrderProcessor {
  return function processOrder(order) {
    let total = 0;
    for (const item of order.items) {
      total += item.cost;
    }
    port.charge(total);
    return { total };
  };
}
```

Green state achieved.

**Refactor**

With the suite green, the loop is replaced with `reduce`. No test changes, and the suite stays green:

```ts
// src/core/order-processor/implementation.ts
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    port.charge(total);
    return { total };
  };
```

## Second TDD Cycle

**Red**

The next behaviour to pin is that an order processor refuses an order the port declines. The test adapter learns to decline:

```ts
// tests/unit/core/order-processor/adapters.ts
export function newFakeOrderProcessorAdapter(accepts = true): FakeOrderProcessorAdapter {
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
// tests/unit/core/order-processor/order-processor.test.ts
import { PaymentDeclined } from "../../../../src/core/order-processor";

test("refuses an order the port declines", () => {
  const orderProcessor = newOrderProcessor(newFakeOrderProcessorAdapter(false));
  expect(() => orderProcessor(orderWith([100]))).toThrow(PaymentDeclined);
});
```

The refusal is determined by the module's implementation, so the module defines the error in its errors file and exports it:

```ts
// src/core/order-processor/errors.ts
export class PaymentDeclined extends Error {}
```

The type checker passes and the test fails because nothing is thrown: a proper red.

**Green**

```ts
// src/core/order-processor/implementation.ts
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!port.charge(total)) {
      throw new PaymentDeclined(order.id);
    }
    return { total };
  };
```

**Refactor**

Nothing is worth changing yet, so the refactor step is empty.

The cycles continue until the required behaviours are all pinned. A behaviour such as charging in a configured currency would add `currency` to the constructor as configuration and to the port's `charge` method, in the same cycle as its test.

## After the cycles

The module now exists in the core and has only ever been constructed with a test adapter. The Stripe adapter for `OrderProcessorPort` is driven by its own cycles, with a test adapter for its HTTP port. The adapter factories, the module factory and the startup code are written last: see [project-structure](../project-structure/SKILL.md) for where they go and [dependency-injection](../dependency-injection/SKILL.md) for what the factories do.
