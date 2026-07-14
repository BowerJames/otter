#!/usr/bin/env bash
# Delete local git branches that don't exist on origin.
#
# Usage:
#   scripts/git-branch-cleanup.sh            # safe delete (git branch -d)
#   scripts/git-branch-cleanup.sh --force    # force delete (git branch -D)
#
# - Fetches & prunes origin first so the comparison is up to date.
# - Never deletes the currently checked-out branch.
# - In safe mode, git refuses to delete unmerged branches (the script
#   stops with git's own error in that case).
set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    "") ;;  # ignore empty args (e.g. from empty justfile parameter)
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ "$FORCE" -eq 1 ]; then
  FLAG="-D"
else
  FLAG="-d"
fi

# Reflect origin's current state (prune deleted remote branches)
git fetch --prune origin

current="$(git rev-parse --abbrev-ref HEAD)"

deleted=0
while read -r branch; do
  # Never delete the currently checked-out branch
  if [ "$branch" = "$current" ]; then
    continue
  fi
  # Delete if no matching origin/<branch> exists
  if ! git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "Deleting local branch '$branch' (not found on origin)..."
    git branch "$FLAG" "$branch"
    deleted=$((deleted + 1))
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads)

if [ "$deleted" -eq 0 ]; then
  echo "No local branches to clean up."
else
  echo "Deleted $deleted branch(es)."
fi
