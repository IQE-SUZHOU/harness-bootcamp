# Agent_repo

Minimal agent-ready repository for D1 · Harness Foundation.

## Quick start

```bash
git clone git@github.com:IQE-SUZHOU/Agent_repo.git
cd Agent_repo
./scripts/check.sh
```

Expected output:

```
practice repo ok: <absolute path>
```

## Files

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Agent instructions: layout, commands, conventions, editing rules |
| `CLAUDE.md` | Symlink to `AGENTS.md` |
| `scripts/check.sh` | Minimal side-effect-free task |
| `scope-list.md` | Instruction scopes and precedence |
| `packages/app/AGENTS.md` | Nested instructions for the app package |

## Scope

All work stays inside this repository. Commands that write outside the repo are out of scope.
