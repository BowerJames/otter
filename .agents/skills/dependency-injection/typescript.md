# Dependency Injection in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## Rule 1: code against interfaces

Bad example for an `OrderProcessor` module:

```ts
function createStripeGateway(apiKey: string, http: Http) {
  return {
    charge(amount: number): boolean { /* ... */ },
  };
}

type OrderProcessor = (order: Order) => Receipt;

function createOrderProcessor(
  gateway: ReturnType<typeof createStripeGateway>, // The factory for the OrderProcessor is using the type of the Stripe implementation.
): OrderProcessor {
  /* ... */
}
```

Good example for an `OrderProcessor` module:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}

type OrderProcessor = (order: Order) => Receipt;

function createOrderProcessor(
  gateway: PaymentGateway, // The factory for the OrderProcessor is using the PaymentGateway interface which can be substituted for any PaymentGateway.
): OrderProcessor {
  /* ... */
}
```

## Rule 2: declare seams in factories

Avoid for an `OrderProcessor` module:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}

type OrderProcessor = (order: Order, gateway: PaymentGateway) => Receipt;

function processOrder(
  order: Order,
  gateway: PaymentGateway, // The seam that changes the capability of the order processor exists in the interface
): Receipt {
  let total = 0;
  for (const item of order.items) {
    total += item.cost;
  }
  const paymentSuccessful = gateway.charge(total);
  if (!paymentSuccessful) {
    throw new Error(/* ... */);
  }
  return { total };
}
```

Prefer for an `OrderProcessor` module:

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
