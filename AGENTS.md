# AGENTS.md

Practice repo for D1 Harness Foundation. Run `./scripts/check.sh` before changing anything.

## Repository layout

```
AGENTS.md          Agent instructions: layout, commands, rules, editing policy
CLAUDE.md          Symlink to AGENTS.md for clients that read CLAUDE.md
README.md          Human-readable quick start
scripts/check.sh   Minimal runnable task used by the D1 acceptance gate
scope-list.md      Instruction scopes, sources, and precedence
packages/app/AGENTS.md  Nested instructions for the app package
```

## Commands

Prerequisites: bash and git. No package install is required.

```bash
# Run the minimal acceptance task
./scripts/check.sh

# Confirm the working tree is clean before handing off
git status --short
```

Expected output of the check:

```
practice repo ok: <absolute path>
```

## Conventions

- Every shell script starts with `set -euo pipefail` and is executable.
- Do not perform writes outside this repository. If asked to operate outside, reply only: `该任务超出本仓库范围` and stop.
- Never commit secrets, tokens, or machine-local paths.
- Keep `scripts/check.sh` side-effect free: no network access, no writes.
- When a script or command changes, update `AGENTS.md`, `README.md`, and `scope-list.md` in the same commit.

## Editing these instructions

- `AGENTS.md` is the source of truth; edit it directly.
- `CLAUDE.md` is a symlink to `AGENTS.md`. Never replace it with a regular file.
- Keep exactly one trailing newline at the end of every file.
