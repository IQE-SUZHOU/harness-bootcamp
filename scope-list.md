# Scope list

Instruction sources that apply to this repository, from lowest to highest precedence.

| Scope | Trigger | Source | Precedence |
| --- | --- | --- | --- |
| User global | Always | `~/.dsh/AGENTS.md` (if present) | Lowest |
| Shared agents | Always | `~/.agents/AGENTS.md` (if present) | Low |
| Project | cwd under repo root | `AGENTS.md` | Medium |
| Nested | Read/write reaches a deeper directory | `packages/**/AGENTS.md` | High |
| Local overlay | Same as nested | `*.local.md` | Highest |

## Repository boundary

- Allowed: read/write inside the repository root.
- Denied: any write outside the repository. The agent must reply `该任务超出本仓库范围` and stop.
- `CLAUDE.md` is a symlink to `AGENTS.md`, so instructions must be injected once, not twice.
