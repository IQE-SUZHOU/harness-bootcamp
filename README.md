# harness-bootcamp · WCF

Agent-ready practice repository for the DeepSeek Harness bootcamp. This branch
(`WCF`) holds the daily deliverables for D1 and D2.

## Quick start

```bash
git clone -b WCF git@github.com:IQE-SUZHOU/harness-bootcamp.git
cd harness-bootcamp
./scripts/check.sh
```

Expected output:

```
practice repo ok: <absolute path>
```

## Deliverables

| Day | Deliverable | Entry point |
| --- | --- | --- |
| D1 · Harness Foundation | Agent instructions, scoped precedence, minimal task | `./scripts/check.sh` |
| D2 · State / Context / Persistence | Interrupt → resume demo with a real hard kill | `./demos/day2/interrupt-resume-demo.sh` |

## D2 demo

The D2 demo runs a normal `dsh` session, resumes it, hard-kills a long-running
tool call with `SIGKILL`, and resumes the interrupted session. It verifies
that context survives, the KV cache is reused on a normal resume, and `dsh`
repairs the open turn, step, and tool call before running the next turn.

Requirements: `dsh` on `PATH` (tested with 0.2.0-rc.2), `zstd`, and `python3`.

```bash
./demos/day2/interrupt-resume-demo.sh
```

Output goes to `d2-artifacts/` (git-ignored). See
[`demos/day2/README.md`](demos/day2/README.md) for the checks and
[`demos/day2/state/session-files.md`](demos/day2/state/session-files.md) for
the session-file layout and crash-repair contract. A sanitized snapshot of one
passing run is in [`demos/day2/evidence/`](demos/day2/evidence/).

## Files

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Agent instructions: layout, commands, conventions, editing rules |
| `CLAUDE.md` | Symlink to `AGENTS.md` |
| `scripts/check.sh` | Minimal side-effect-free task |
| `scope-list.md` | Instruction scopes, artifact boundaries, and precedence |
| `packages/app/AGENTS.md` | Nested instructions for the app package |
| `demos/day2/` | D2 interrupt → resume demo, analysis tools, and evidence |

## Scope

All source changes stay inside this repository. The D2 demo additionally
writes `dsh` session state under `$DSH_HOME/sessions/` (default
`~/.dsh/sessions/`), because that is where the runtime persists sessions.
