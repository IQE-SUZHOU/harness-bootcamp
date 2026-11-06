# AGENTS.md

Practice repository for the DeepSeek Harness bootcamp (D1–D2). Run
`./scripts/check.sh` before changing anything, and run
`./demos/day2/interrupt-resume-demo.sh` when touching session, persistence, or
resume behavior.

## Repository layout

```
AGENTS.md               Agent instructions: layout, commands, rules, editing policy
CLAUDE.md               Symlink to AGENTS.md for clients that read CLAUDE.md
README.md               Human-readable quick start
scripts/check.sh        Minimal runnable task used by the D1 acceptance gate
scope-list.md           Instruction scopes, artifact boundaries, and precedence
packages/app/AGENTS.md  Nested instructions for the app package
demos/day2/interrupt-resume-demo.sh  D2 hard-kill and resume acceptance run
demos/day2/analyze_session.py        Session log timeline and summary tool
demos/day2/projectkey.py             dsh project key for a working directory
demos/day2/state/session-files.md    On-disk session layout and crash repair
demos/day2/evidence/                 Sanitized snapshot of one passing run
```

## Commands

Prerequisites: bash and git. The D2 demo also needs `dsh`, `zstd`, and
`python3`. No package install is required.

```bash
# Run the minimal acceptance task
./scripts/check.sh

# Run the D2 interrupt → resume acceptance demo
./demos/day2/interrupt-resume-demo.sh

# Confirm the working tree is clean before handing off
git status --short
```

Expected output of the check:

```
practice repo ok: <absolute path>
```

Expected tail of the D2 demo:

```
all checks passed; evidence in <absolute path>
```

## Conventions

- Every shell script starts with `set -euo pipefail` and is executable.
- Demo scripts are non-interactive and exit non-zero when an acceptance check
  fails.
- Do not perform source writes outside this repository. The only exception is
  the D2 demo's `dsh` session state under `$DSH_HOME/sessions/`, which is the
  runtime's persistence store. If asked to operate outside the repository for
  any other purpose, reply only: `该任务超出本仓库范围` and stop.
- Never commit secrets, tokens, or machine-local paths, including absolute
  session directories. Use `<repo-root>` placeholders in committed evidence.
- Keep `scripts/check.sh` side-effect free: no network access, no writes.
- Generated demo output goes to `d2-artifacts/` and stays untracked. Commit
  only sanitized snapshots under `demos/day2/evidence/`.
- When a script or command changes, update `AGENTS.md`, `README.md`, and
  `scope-list.md` in the same commit.

## Editing these instructions

- `AGENTS.md` is the source of truth; edit it directly.
- `CLAUDE.md` is a symlink to `AGENTS.md`. Never replace it with a regular file.
- Keep exactly one trailing newline at the end of every file.
