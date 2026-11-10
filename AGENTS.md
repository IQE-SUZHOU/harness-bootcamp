# AGENTS.md

Practice repository for the DeepSeek Harness bootcamp (D1–D5). Run
`./scripts/check.sh` before changing anything, run
`./demos/day2/interrupt-resume-demo.sh` when touching session, persistence, or
resume behavior, run `./demos/day3/maker-checker-demo.sh` when touching
verification, retries, or approval gates, run
`./demos/day4/loop-graph-demo.sh` when touching workflow scripts, fan-out,
stop conditions, or failure propagation, and run
`./demos/day5/super-agent-demo.sh` when touching Team tasks, fork/fresh
delegation, skills, or the integration assessment.

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
.dsh/skills/d5-super-agent/SKILL.md  Project skill loaded by the D5 demo
demos/day5/super-agent-demo.sh       D5 Team, fork/fresh, skill, integration run
demos/day5/AGENTS.md                 Nested D5 instructions (marker check)
demos/day5/team-patch.yml            Experimental Team service and tools
demos/day5/flow/limits.yml           Workflow and goal stop-condition overlay
demos/day5/team_tools.py             Session-log parser and config helpers
demos/day5/render_evidence.py        Deterministic assessment and evidence renderer
demos/day5/verify/static.sh          Static DoD check Carol runs inside the demo
demos/day5/verify/verify_d5.py       Independent non-LLM verifier (V1–V17)
demos/day5/evidence/                 Sanitized snapshot of one passing run
```

## Commands

Prerequisites: bash and git. The D2, D3, D4, and D5 demos also need `dsh`,
`zstd`, and `python3`. No package install is required.

```bash
# Run the minimal acceptance task
./scripts/check.sh

# Run the D2 interrupt → resume acceptance demo
./demos/day2/interrupt-resume-demo.sh

# Run the D3 maker-checker acceptance demo
./demos/day3/maker-checker-demo.sh

# Run the D4 fan-out/fan-in and stop-condition demo
./demos/day4/loop-graph-demo.sh

# Run the D5 super-agent integration demo
./demos/day5/super-agent-demo.sh

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

Expected tail of the D5 demo:

```
  PASS  V17
evidence: <absolute path>/demos/day5/evidence
```

## Conventions

- Every shell script starts with `set -euo pipefail` and is executable.
- Demo scripts are non-interactive and exit non-zero when an acceptance check
  fails.
- Do not perform source writes outside this repository. The only exception is
  the D2, D3, D4, and D5 demos' `dsh` session state under
  `$DSH_HOME/sessions/`, which is the runtime's persistence store. If asked to
  operate outside the repository for any other purpose, reply only:
  `该任务超出本仓库范围` and stop.
- Never commit secrets, tokens, or machine-local paths, including absolute
  session directories. Use `<repo-root>` placeholders in committed evidence.
  The D3 human-approval token is generated at run time and is never committed;
  committed evidence redacts it as `<human-token>`.
- Keep `scripts/check.sh` side-effect free: no network access, no writes.
- Generated demo output goes to `d2-artifacts/`, `d3-artifacts/`,
  `d4-artifacts/`, and `d5-artifacts/` and stays untracked. Commit only
  sanitized snapshots under `demos/day2/evidence/`, `demos/day3/evidence/`,
  `demos/day4/evidence/`, and `demos/day5/evidence/`. The D5 assessment log is
  generated from `team/task`, `team/member`, and session events, not from a
  model self-report.
- The D4 negative-control prompts intentionally contain a throwing branch, an
  unknown `agent()` option, and a busy loop. Do not "fix" them; the demo must
  keep failing those runs on purpose. The D5 prompts intentionally include a
  stale compare-and-set claim and a fresh teammate that must answer `UNKNOWN`;
  keep both failures visible.
- `dsh 0.2.0-rc.2` ships the Team packages as `dsh-experimental-agent-team` and
  `dsh-experimental-tool-agent-team`. `demos/day5/team-patch.yml` mounts them
  with an `insert:` row; do not rewrite it as a plain `- id:` replacement.
- When a script or command changes, update `AGENTS.md`, `README.md`, and
  `scope-list.md` in the same commit.

## Editing these instructions

- `AGENTS.md` is the source of truth; edit it directly.
- `CLAUDE.md` is a symlink to `AGENTS.md`. Never replace it with a regular file.
- Keep exactly one trailing newline at the end of every file.
