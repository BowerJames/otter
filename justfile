set dotenv-load

# Show available recipes
default:
    @just --list

# Delete local git branches that don't exist on origin.
# Safe by default (git branch -d); use --force to force delete (git branch -D).
git-branch-cleanup force="":
    ./scripts/git-branch-cleanup.sh {{ force }}
