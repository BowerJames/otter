---
name: resource-management
description: Patterns for resource managenment. Use this skill whenver designing or improving modules that handle resources.
---

# Resource

In software engineering, a resource is any limited system entity that must be explicitly requested, used, and explicitly released back to the operating system or environment.

If holding onto it without cleaning it up causes a leak, system slowdown, or crashed connection, it is a resource.

The 3 Defining Characteristics of a Resource

**Limited Availability** - The system only has a finite amount of them (e.g., available RAM, max file handles, open TCP ports).

**Explicit Lifecycle** - It requires a two-step handshake: an acquire/open step to start using it, and a release/close step when done.

**External Ownership** - The entity is typically managed by the operating system, a remote server, or a sub-system outside your immediate local scope.

## Glossary

**Acquisition** - The operation where a program gains exclusive access or ownership of a resource.

**Release** - The operation where a program notifies the system of environment that it no longer needs access to the resource so that it can be reclaimed.

## Principals

- Resources should be tied to the same scope that they are released.

## Patterns

```python
# GOOD: Acquisition tied to release
with open(file, 'r') as f:
    lines=f.readlines() 

# BAD: Acquisition not tied to release
f = open(file, 'r')
lines=f.readlines()
f.close()

# BAD: Release not in the same scope as acquisition
f, content = open_and_read_file(file)
content = content + '\n' + 'New line contnent'
write_new_content_and_close(content, f)
```

```python
# GOOD: Acquisition tied to release
async with websocket as ws:
    await run_session(ws)

# BAD: Release not in the same scope as acquisition
await ws = websocket.connect()
await run_session(ws)
await ws.close()

# BAD: Release not in the same scope as acquisition
await connect_and_run_session(websocket)
await websocket.close()
```