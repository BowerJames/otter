# Codebase Design in TypeScript

The vocabulary in [SKILL.md](SKILL.md) is language-agnostic. This file is its TypeScript spelling.

The style throughout: **no classes**. Entities are functions and object literals built by factories; they satisfy an `interface` structurally.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Interface** | for object shapes, an `interface`; for functions, a type — `() => Date` |
| **Adapter** | any object literal or function satisfying the interface's shape |
| **Seam** | a typed parameter capability varies through: an object interface, a function type, or a plain value |

## Example 1

Below illustrates an example of a `PaymentGateway` module in TypeScript.

```ts
type EnvVariableLoader = (name: string) => string;
type Http = (request: Request) => Response;

interface PaymentGateway {               // the interface for the PaymentGateway module
  charge(amount: number): boolean;
}

function createStripeGateway(apiKey: string, http: Http): PaymentGateway {
  return {
    charge(amount) { /* ... */ },
  };
}

function createPaypalGateway(apiKey: string, http: Http): PaymentGateway {
  return {
    charge(amount) { /* ... */ },
  };
}

function createPaymentGateway(
  type: "stripe" | "paypal",             // seam for the PaymentGateway module
  envVariableLoader: EnvVariableLoader,  // seam for the PaymentGateway module to access the environment variable resource for testing
  http: Http,
): PaymentGateway {                      // a factory for the PaymentGateway module
  switch (type) {
    case "stripe":
      return createStripeGateway(envVariableLoader("STRIPE_API_KEY"), http);
    case "paypal":
      return createPaypalGateway(envVariableLoader("PAYPAL_API_KEY"), http);
  }
}
```

Matching is structural: the object literals built by `createStripeGateway` and `createPaypalGateway` both satisfy the `PaymentGateway` interface.

The declared return type checks each literal where it is built, so drift is a compile error at that point. No `class` and no `implements` are needed. `createStripeGateway` and `createPaypalGateway` are themselves factories for the module: a module can have many.

This module is a well designed deep module:

**Leverage for the caller** - The module allows the caller to make payments through Stripe and PayPal through a simple interface with a single method with a single parameter.

**Flexibility for developers** - It is simple to extend the module's capabilities by adding another function returning an object that satisfies the `PaymentGateway` interface and adding a single extra `case` in the implementation of the factory.

**Testability for everyone** - The module can be tested easily through its factory and interface by providing test adapters for the env loader and http dependencies to observe behaviours through.

## Example 2

Below are 2 valid formulations of an `OrderProcessor` module built on top of example 1.

```ts
type OrderProcessor = (order: Order, gateway: PaymentGateway) => Receipt; // interface for the OrderProcessor module

function processOrder(
  order: Order,
  gateway: PaymentGateway, // seam through which capabilities of the OrderProcessor can vary
): Receipt {
  // implementation of the OrderProcessor module
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

```ts
type OrderProcessor = (order: Order) => Receipt; // interface for the OrderProcessor module

function createOrderProcessor(
  gateway: PaymentGateway, // a seam for the OrderProcessor module
): OrderProcessor {        // factory of the OrderProcessor module
  return function processOrder(order) {
    // implementation of the OrderProcessor module
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

Both are modules with a seam; they differ in where the seam sits. The first places it in the interface, so every caller must supply a gateway. The second places it in the factory, leaving the interface with only data. Prefer the second wherever the adapter is known when the entity is created (see dependency-injection, rule 2).

The second example exhibits:

**Leverage for Consumers** - Has the capability to total orders and process payments through Stripe and PayPal (thanks to the existing adapters).

**Locality for Maintainers** - Tests can be written with a fake payment gateway, allowing them to localise bugs in the order totalling vs the payment gateways. Any change to the order processing can be propagated to all payment gateway types through one place.

**Testability for Everyone** - A fake payment gateway allows tests to pin a single behaviour "Charges payment gateway with total equal to the sum of the cost of all items in the order" and the module gains the capability for all gateway types. One behaviour giving a range of capabilities.
