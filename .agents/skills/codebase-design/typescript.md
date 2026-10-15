# Codebase Design in TypeScript

The vocabulary in [SKILL.md](SKILL.md) is language-agnostic. This file is its TypeScript spelling.

The style throughout: **no classes**. Entities are functions and object literals returned by their constructors; they satisfy an `interface` structurally. The one exception is an error: a subclass of `Error`.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Interface** | for object shapes, an `interface`; for functions, a type — `(order: Order) => Receipt` |
| **Port** | for object shapes, an `interface`; for functions, a type — `() => Date` |
| **Adapter** | an object literal or function satisfying the port's shape |
| **Constructor** | the function that takes the port and returns the entity |
| **Data carrier** | an `interface` or `type` of plain, `readonly` data, or a union of literals |
| **Error** | a subclass of `Error` |

With no classes, a constructor and a factory are both functions. They are told apart by name: a constructor is `new…` (`newOrderProcessor`), a factory is `create…` (`createOrderProcessor`).

## Module

Below illustrates an example of an `OrderProcessor` module in TypeScript.

The interface of a module can be spelled as an `interface` or as a type. Both of the below define the same interface; pick one.

```ts
interface OrderProcessor { // Interface for the module, as an interface
  (order: Order): Receipt;
}
```

```ts
type OrderProcessor = (order: Order) => Receipt; // Interface for the module, as a type
```

The rest of the module is the same whichever spelling is used.

```ts
type Currency = "GBP" | "USD" | "EUR"; // Data carrier: its only invariant is the one its type expresses

interface OrderProcessorPort { // The module's one port: everything it needs from outside itself
  charge(amount: number, currency: Currency): boolean;
}

class PaymentDeclined extends Error {} // An error the module's implementation determines, so the module owns it

function newOrderProcessor(
  port: OrderProcessorPort, // the port
  currency: Currency,       // configuration
): OrderProcessor { // Constructor for the module
  return function processOrder(order) { // Implementation of the module
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!port.charge(total, currency)) {
      throw new PaymentDeclined(order.id);
    }
    return { total, currency };
  };
}

function newStripeAdapter(apiKey: string, http: Http): OrderProcessorPort { // Constructor for the stripe adapter
  return { // Adapter for the port
    charge(amount, currency) { /* ... */ },
  };
}

function newPaypalAdapter(apiKey: string, http: Http): OrderProcessorPort { // Constructor for the paypal adapter
  return { // Adapter for the port
    charge(amount, currency) { /* ... */ },
  };
}

function createStripeAdapter(apiKey: string): OrderProcessorPort { // An adapter factory for the stripe adapter
  return newStripeAdapter(apiKey, newRealHttp());
}

function createPaypalAdapter(apiKey: string): OrderProcessorPort { // An adapter factory for the paypal adapter
  return newPaypalAdapter(apiKey, newRealHttp());
}

function createOrderProcessor(
  provider: "stripe" | "paypal",
  apiKey: string,
  currency: Currency,
): OrderProcessor { // A module factory for the order processor module
  switch (provider) {
    case "stripe":
      return newOrderProcessor(createStripeAdapter(apiKey), currency);
    case "paypal":
      return newOrderProcessor(createPaypalAdapter(apiKey), currency);
  }
}
```

Matching is structural: the object literals returned by `newStripeAdapter` and `newPaypalAdapter` both satisfy `OrderProcessorPort`. The declared return type checks each literal where it is built, so drift is a compile error at that point. No `class` and no `implements` are needed.

## Errors

The adapter handles what it can decide and lets everything else propagate:

```ts
function newStripeAdapter(apiKey: string, http: Http): OrderProcessorPort {
  return {
    charge(amount, currency) {
      const response = http({ /* ... */ }); // a network error propagates unchanged
      if (response.status === 402) {
        return false; // handled: a decline is an answer the port can give
      }
      return true;
    },
  };
}
```

Wrapping hides the error's origin:

```ts
    charge(amount, currency) {
      try {
        const response = http({ /* ... */ });
        /* ... */
      } catch (error) {
        throw new PaymentFailed({ cause: error }); // bad: wraps an error the adapter did not determine
      }
    },
```
