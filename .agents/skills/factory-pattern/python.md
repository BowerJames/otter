# Factory Pattern in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## Rule 1: return the interface

```python
def create_payment_gateway(config: Config, http: Requester) -> PaymentGateway:  # ingredients in the signature
    if config.use_stripe:
        return StripeGateway(config.stripe_key, http)   # the concretes named here are the products
    return PaypalGateway(config.paypal_env, http)

# at a composition point — the ingredient concrete is named where concretes are named
gateway = create_payment_gateway(config, HttpRequests())  # caller never learns the product concrete
```

## Rule 2: bind runtime data to root-chosen adapters

Injected factories are `Callable` types. Bind the root-time ingredient with a closure or `functools.partial`:

```python
from functools import partial

loader_factory = partial(create_entity_loader, config_source=config_source)  # bound at the root
loader_factory = lambda eid: create_entity_loader(eid, config_source)        # the same, as a closure

class EntityEndpoints:
    def __init__(self, loader_factory: Callable[[EntityId], EntityLoader]):
        self.loader_factory = loader_factory          # the factory is the seam

    def on_get(self, entity_id: EntityId):            # data arrives at the boundary
        return EntityService(self.loader_factory(entity_id)).handle()
```

A test injects a lambda fake and controls construction without touching globals:

```python
endpoints = EntityEndpoints(loader_factory=lambda eid: FakeLoader(eid))
```
