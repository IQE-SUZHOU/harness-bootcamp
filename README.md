# harness-bootcamp · WCF

Agent-ready practice repository for the DeepSeek Harness bootcamp. This branch
(`WCF`) holds the daily deliverables for D1–D4.

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
| D3 · Verification / Reliability | Definition of Done, maker-checker loop, human gate | `./demos/day3/maker-checker-demo.sh` |
| D4 · Loop / Graph / Automation | Three-way fan-out/fan-in, stop conditions, failure propagation | `./demos/day4/loop-graph-demo.sh` |

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

## D3 demo

The D3 demo plants failures in a fixture repository, has a maker claim the
work is done, and sends an independent checker to execute every Definition of
Done command. The checker rejects the claim, the maker repairs the workspace in
a bounded loop (max 2 retries), a human issues the approval token, and a final
blind spawn checker plus a non-LLM verifier confirm the result.

```bash
./demos/day3/maker-checker-demo.sh
```

Output goes to `d3-artifacts/` (git-ignored). See
[`demos/day3/README.md`](demos/day3/README.md) for the fixture, planted
failures, acceptance checks, and the fork-vs-spawn contrast. A sanitized
snapshot of one passing run is in
[`demos/day3/evidence/`](demos/day3/evidence/).

## D4 demo

The D4 demo runs five real headless sessions against the `workflow` tool: a
three-way fan-out with one fan-in summary, an ordinary branch failure, an
illegal `agent()` option, a two-agent total cap, and a synchronous timeout. It
proves that routing is observable, ordinary failures become `null`, and fatal
errors plus engine stop conditions terminate the whole run without reporting a
partial success. A separate overlay also pins the goal round cap as the
auto-loop exit condition.

```bash
./demos/day4/loop-graph-demo.sh
```

Output goes to `d4-artifacts/` (git-ignored). See
[`demos/day4/README.md`](demos/day4/README.md) for the stop-condition table,
routing explanation, failure semantics, and goal layering. A sanitized snapshot
of one passing run is in
[`demos/day4/evidence/`](demos/day4/evidence/).

## Files

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Agent instructions: layout, commands, conventions, editing rules |
| `CLAUDE.md` | Symlink to `AGENTS.md` |
| `scripts/check.sh` | Minimal side-effect-free task |
| `scope-list.md` | Instruction scopes, artifact boundaries, and precedence |
| `packages/app/AGENTS.md` | Nested instructions for the app package |
| `demos/day2/` | D2 interrupt → resume demo, analysis tools, and evidence |
| `demos/day3/` | D3 maker-checker demo, DoD verifier, fixture, and evidence |
| `demos/day4/` | D4 fan-out/fan-in demo, stop-condition overlays, verifier, and evidence |

## Scope

All source changes stay inside this repository. The D2, D3, and D4 demos
additionally write `dsh` session state under `$DSH_HOME/sessions/` (default
`~/.dsh/sessions/`), because that is where the runtime persists sessions.
