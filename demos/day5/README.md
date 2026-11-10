# Day 5 · Integration + Super-agent Demo

Reproducible evidence for **D5 · three super-agent dimensions**:

- **A · context inheritance** — `spawn_teammate(context="fork")` sees the Lead's
  completed turns; `context="fresh"` starts empty.
- **B · shared state** — one durable Team task board with compare-and-set
  ownership; a stale revision is rejected, not retried.
- **C · capability extension** — a repository skill (`d5-super-agent`) is
  discovered and loaded, and the nested `demos/day5/AGENTS.md` is injected.

The demo drives **one root session across four resumed turns**:

1. load the skill, create six Team tasks, complete `harness-foundation`, claim
   `cas-proof`, and seed `INTEGRATION_TOKEN=SA-WCF-D5-7F3A`;
2. spawn `fork-auditor` (fork), `carol` (fresh, runs `verify/static.sh`),
   `fresh-worker` (fresh, must answer `UNKNOWN`), and `bob` (fresh, sends a stale
   compare-and-set claim);
3. run the D4 fan-out/fan-in workflow and finish `loop-graph` and `integration`;
4. reload the skill, read the final board, and emit six falsifiable
   teach-back lines.

`render_evidence.py` derives the assessment log from `team/task`,
`team/member`, `subagent-settled`, and tool events. `verify/verify_d5.py`
re-derives V1–V17 without an LLM; the demo exits non-zero if either layer fails.

## Version note: experimental Team packages

The course document names `@deepseek-ai/dsh-agent-team` and
`@deepseek-ai/dsh-tool-agent-team`. The installed `dsh 0.2.0-rc.2` ships them as
**experimental** packages:

- `@deepseek-ai/dsh-experimental-agent-team`
- `@deepseek-ai/dsh-experimental-tool-agent-team`

[`team-patch.yml`](team-patch.yml) mounts those packages with an `insert:` row
(an unknown id cannot be replaced directly in a patch) and disables the legacy
`tool-subagent*` rows so `spawn_teammate` is the only delegation surface.

## Layout

```
demos/day5/
├── README.md
├── AGENTS.md                 # nested instructions, marker D5-NESTED-AGENTS-V1
├── dod.md                    # V1–V17, every item decidable
├── teachback.md              # six main lines and their evidence
├── super-agent-qa.md         # 28 oral-assessment questions and answers
├── team-patch.yml            # experimental Team service + tools
├── super-agent-demo.sh       # end-to-end runner
├── team_tools.py             # session-log parser and config helpers
├── render_evidence.py        # deterministic assessment + evidence renderer
├── verify/
│   ├── static.sh             # static DoD check used by Carol
│   ├── static_checks.py
│   └── verify_d5.py          # independent V1–V17 verifier
├── flow/
│   ├── workflow.js           # fan-out/fan-in script
│   └── limits.yml            # workflow + goal stop conditions
├── prompts/                  # turn1, turn2, turn3.txt.in, turn4
└── evidence/                 # committed sanitized snapshot
```

The repository skill lives at `.dsh/skills/d5-super-agent/SKILL.md`; dsh
discovers it at project rank, and the `skill` tool loads it by exact name.

## Mini-agent companion

`mini-agent/` is a dependency-free coding agent that mirrors the Harness
architecture — turn/step agent loop, durable session log, tool registry, and
provider adapters — without the Cordis plugin runtime, the GUI, or the
persistence backends. It is a companion deliverable for reading and
extending, not part of the D5 acceptance run.

```bash
# 56 behavior and wire-protocol tests; no network, no API key
./mini-agent/tests/run-tests.sh

# Run it against a provider
export MINIMAX_API_KEY=...
node --experimental-strip-types mini-agent/src/cli/main.ts \
  --provider minimax --model MiniMax-M3.1-Flash --max-steps 10 \
  "list the files in this directory"
```

See [`mini-agent/README.md`](mini-agent/README.md) and
[`mini-agent/docs/custom-model-api.md`](mini-agent/docs/custom-model-api.md).

## Run

```bash
./demos/day5/super-agent-demo.sh
```

Requirements: `dsh` on `PATH` (tested with `0.2.0-rc.2`), `zstd`, `python3`,
`timeout`, and a provider with quota. If the default provider is unavailable,
pass a model overlay:

```bash
DSH_PATCH=/path/to/model.yml DSH_TIMEOUT=900 ./demos/day5/super-agent-demo.sh
```

`DSH_TIMEOUT` (default 900 seconds) wraps each of the four turns. The four runs
share one session id; each run applies `team-patch.yml` and `flow/limits.yml`.

## What each check proves

| Check | Observation |
| --- | --- |
| V1 | the `skill` tool result contains `D5-SUPER-AGENT-SKILL-V1` |
| V2 | `agent-instructions` contains `D5-NESTED-AGENTS-V1` |
| V3 | one session id, four `turn/start` events, all closed |
| V4–V6 | six tasks, `integration` blocked by four, all completed with owners |
| V7 | Bob's `expected_revision=1` claim fails with `stale ... revision 2` |
| V8 | fork child is seeded and its closing message is the Lead's token |
| V9 | fresh child is unseeded, has no token, and answers `UNKNOWN` |
| V10–V11 | workflow `completed (4 agents)`, `count=3`, fan-in after all branches |
| V12–V13 | effective stop config matches `flow/limits.yml`; goal cap is 20 |
| V14 | Carol's child log shows `d5 static checks passed` before she completes |
| V15 | `assessment.md` has six tasks, six lines, and V1–V17 |
| V16 | the Lead's final answer has six lines with evidence refs |
| V17 | committed evidence has no home paths, API keys, or raw session logs |

## Failure semantics

- A stale revision is reported, never retried; the board keeps the newer work.
- A fresh teammate that cannot see the token must answer `UNKNOWN`.
- A failed workflow branch is `null`; fatal errors abort the whole run.
- Team write scopes are advisory. The Lead owns the final assessment and the
  demo's independent verifier, not a self-report.

## Output

Raw output goes to `d5-artifacts/` (git-ignored). The sanitized snapshot in
[`evidence/`](evidence/) contains `root.json`, `children.json`, `summary.json`,
`assessment.md`, `evidence.md`, `routing.md`, `graph.mmd`, `teachback.txt`,
`stop-condition.json`, `auto-loop.json`, and `verifier-result.json`.

## Tools

- `team_tools.py` — session id, project key, root/child event parsing,
  effective workflow and goal config.
- `render_evidence.py` — deterministic assessment log and evidence files.
- `verify/static.sh` — static artifact checks (Carol runs this inside the demo).
- `verify/verify_d5.py` — independent non-LLM verifier (V1–V17).
