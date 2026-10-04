---
name: repo-explorer
description: Use this skill to explore codebases without cluttering the active workspace. Clones third-party repositories into a /tmp/repos/ cache and reuses existing checkouts.
---

# Repository Cache

Use the `/tmp/repos/` directory to store cloned repositories. This allows you to
explore codebases without cluttering your active workspace.

## Current Cache Contents

```bash
mkdir -p /tmp/repos
ls -la /tmp/repos
```

## Flow

1. Check whether the target repository is already present in `/tmp/repos/`.
  - Prefer a stable directory name based on the repository owner and name such as `owner__repo`.
  - If the repository is already there use that local checkout for exploration.
2. If the repository is not present, clone it into `/tmp/repos/`, then explore it there.
  - Clone with a clear destination path.

```bash
git clone <repo_url> /tmp/repos/<owner>__<repo>
```
