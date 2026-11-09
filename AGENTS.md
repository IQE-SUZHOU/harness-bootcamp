# AGENTS.md

Practice repository for the DeepSeek Harness bootcamp (D1–D4). Run
`./scripts/check.sh` before changing anything, run
`./demos/day2/interrupt-resume-demo.sh` when touching session, persistence, or
resume behavior, run `./demos/day3/maker-checker-demo.sh` when touching
verification, retries, or approval gates, and run
`./demos/day4/loop-graph-demo.sh` when touching workflow scripts, fan-out,
stop conditions, or failure propagation.

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
demos/day3/maker-checker-demo.sh     D3 maker-checker acceptance run
demos/day3/fixture/                  Planted-failure target workspace
demos/day3/verify_dod.py             Authoritative DoD verifier (no LLM)
demos/day3/checker_tools.py          Checker JSON, todo, timeline, child tools
demos/day3/evidence/                 Sanitized snapshot of one passing run
demos/day4/loop-graph-demo.sh        D4 fan-out/fan-in and stop-condition run
demos/day4/prompts/                  One prompt per positive/negative control
demos/day4/stop-condition.yml        Workflow engine and goal round-cap overlay
demos/day4/stop-condition-cap.yml    Two-agent cap overlay for the cap control
demos/day4/workflow_tools.py         Result, routing, runtime, and config tools
demos/day4/render_evidence.py        Evidence renderer
demos/day4/verify_d4.py              Independent non-LLM verifier (V1–V13)
demos/day4/evidence/                 Sanitized snapshot of one passing run
```

## Commands

Prerequisites: bash and git. The D2, D3, and D4 demos also need `dsh`, `zstd`,
and `python3`. No package install is required.

```bash
# Run the minimal acceptance task
./scripts/check.sh

# Run the D2 interrupt → resume acceptance demo
./demos/day2/interrupt-resume-demo.sh

# Run the D3 maker-checker acceptance demo
./demos/day3/maker-checker-demo.sh

# Run the D4 fan-out/fan-in and stop-condition demo
./demos/day4/loop-graph-demo.sh

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

Expected tail of the D3 demo:

```
  finalAllPassed  PASS
evidence: <absolute path>/demos/day3/evidence
```

Expected tail of the D4 demo:

```
  PASS  resultIsPureJson
evidence: <absolute path>/demos/day4/evidence
```

## Conventions

- Every shell script starts with `set -euo pipefail` and is executable.
- Demo scripts are non-interactive and exit non-zero when an acceptance check
  fails.
- Do not perform source writes outside this repository. The only exception is
  the D2, D3, and D4 demos' `dsh` session state under `$DSH_HOME/sessions/`,
  which is the runtime's persistence store. If asked to operate outside the
  repository for any other purpose, reply only: `该任务超出本仓库范围` and stop.
- Never commit secrets, tokens, or machine-local paths, including absolute
  session directories. Use `<repo-root>` placeholders in committed evidence.
  The D3 human-approval token is generated at run time and is never committed;
  committed evidence redacts it as `<human-token>`.
- Keep `scripts/check.sh` side-effect free: no network access, no writes.
- Generated demo output goes to `d2-artifacts/`, `d3-artifacts/`, and
  `d4-artifacts/` and stays untracked. Commit only sanitized snapshots under
  `demos/day2/evidence/`, `demos/day3/evidence/`, and `demos/day4/evidence/`.
- The D4 negative-control prompts intentionally contain a throwing branch, an
  unknown `agent()` option, and a busy loop. Do not "fix" them; the demo must
  keep failing those runs on purpose.
- When a script or command changes, update `AGENTS.md`, `README.md`, and
  `scope-list.md` in the same commit.

## Editing these instructions

- `AGENTS.md` is the source of truth; edit it directly.
- `CLAUDE.md` is a symlink to `AGENTS.md`. Never replace it with a regular file.
- Keep exactly one trailing newline at the end of every file.
